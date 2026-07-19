from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import mimetypes
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.elevation import ElevationApplyJob, ElevationDataImportJob, ElevationDataset, ElevationDatasetFileMeta, ElevationFileRecord
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.user import User
from ..schemas.elevation import (
    ElevationApplyJobCreateRequest,
    ElevationApplyJobCreateResponse,
    ElevationApplyJobListResponse,
    ElevationApplyJobSummary,
    ElevationDataImportJobListResponse,
    ElevationDataImportJobSummary,
    ElevationDatasetAnalysisTaskStatusResponse,
    ElevationDatasetAnalyzeResponse,
    ElevationDatasetBatchImportResponse,
    ElevationDatasetDataImportResponse,
    ElevationDatasetTerrainBuildResponse,
    ElevationDatasetTerrainTaskStatusResponse,
    ElevationFileRecordTaskStatusResponse,
    ElevationFileRecordTerrainTaskStatusResponse,
    ElevationTerrainLayerResponse,
    ElevationDatasetPreviewCell,
    ElevationDatasetPreviewDiagnostics,
    ElevationDatasetCreateRequest,
    ElevationDatasetFileItem,
    ElevationDatasetFileListResponse,
    ElevationDatasetListResponse,
    ElevationDatasetPreviewPoint,
    ElevationDatasetPreviewResponse,
    ElevationDatasetSummary,
    ElevationDatasetUpdateRequest,
)
from .file_service import _build_driver_or_400, _require_mount, list_enabled_mounts
from .line_preparation_service import record_line_preparation_source
from .push_service import publish_topic
from .storage_driver import StorageDriverError, StorageInvalidPathError, StoragePathNotFoundError, join_virtual_path, normalize_virtual_path

ELEVATION_TOPIC = "admin.elevation"
POWER_LINES_TOPIC = "admin.power-lines"
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
CSV_IMPORT_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
NEAREST_MATCH_MAX_DISTANCE_M = 2000.0
ELEVATION_DATASET_ROOT = "/elevation/datasets"
ELEVATION_FILE_EXT_FORMAT_MAP = {
    ".tif": "tif",
}
RASTER_FILE_FORMATS = {"tif"}
IMPORTABLE_ELEVATION_EXTENSIONS = set(ELEVATION_FILE_EXT_FORMAT_MAP.keys())
IMPORTABLE_ARCHIVE_EXTENSIONS: set[str] = {".zip"}
MAX_SAMPLE_COUNT_INT = 2_147_483_647
TERRAIN_TILE_SIZE = 65
TERRAIN_ROOT_DIRNAME = "terrain"
TERRAIN_TILE_VERSION = "1.0.0"
TERRAIN_TILE_FORMAT = "heightmap-1.0"
TERRAIN_TILE_PROJECTION = "EPSG:4326"
TERRAIN_DEFAULT_MIN_ZOOM = 0
TERRAIN_DEFAULT_MAX_ZOOM = 6
TERRAIN_MAX_ALLOWED_ZOOM = 10
TERRAIN_TILE_COUNT_LIMIT = 100000  # 瓦片总数上限（gdal2tiles --profile=raster 按像素切分）
TERRAIN_CHILD_MASK_SW = 1
TERRAIN_CHILD_MASK_SE = 2
TERRAIN_CHILD_MASK_NW = 4
TERRAIN_CHILD_MASK_NE = 8
TERRAIN_WATER_MASK_ALL_LAND = b"\x00"
TERRAIN_CONTENT_TYPE = "application/octet-stream"
TERRAIN_SUPPORTED_DATASET_FORMATS = RASTER_FILE_FORMATS
TERRAIN_BUILD_TOOL = "gdal2tiles"
TERRAIN_BATCH_SIZE = 5000  # 每个 tar.gz 包包含的瓦片数
TERRAIN_STAGING_DIRNAME = "_staging"  # staging 暂存子目录名
TERRAIN_ARCHIVE_PREFIX = "batch"  # tar.gz 包文件名前缀
TERRAIN_UNPACK_ENDPOINT = "/api/v1/internal/elevation/records/{record_id}/terrain/unpack"
LOCAL_TERRAIN_ROOT = "/app/data/terrain"  # API 容器中 mount 的 terrain 目录（Nginx 直接服务）
IMPORT_JOB_STAGE_DIRNAME = ".imports"
GDEM_FILENAME_PATTERNS = [
    r"ASTGTMV003_[NS]\d{2}[EW]\d{3}_dem\.tif",  # GDEM V3
    r"ASTGTM2_[NS]\d{2}[EW]\d{3}_dem\.tif",      # GDEM V2
]
GDEM_DEFAULT_RESOLUTION_M = 30.0


@dataclass
class ElevationSamplePoint:
    lon: float
    lat: float
    altitude_m: float


@dataclass
class _OpenedRasterDataset:
    rasterio: Any
    dataset: Any
    temp_path: str

    def __enter__(self) -> "_OpenedRasterDataset":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            self.dataset.close()
        finally:
            try:
                Path(self.temp_path).unlink(missing_ok=True)
            except Exception:
                pass
        return False


@dataclass
class ElevationDatasetBatchImportStats:
    imported_count: int = 0
    analyzed_count: int = 0
    skipped_count: int = 0
    warnings: list[str] | None = None
    items: list[ElevationDatasetSummary] | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []
        if self.items is None:
            self.items = []


@dataclass
class _TerrainBuildArtifacts:
    min_zoom: int
    max_zoom: int
    bounds: dict[str, float]
    metadata: dict[str, Any]


def _detect_gdem_dataset(filename: str) -> dict[str, Any] | None:
    """
    检测是否为GDEM数据集文件

    Args:
        filename: 文件名，如 ASTGTM2_N30E120_dem.tif

    Returns:
        GDEM信息字典，包含 source_type, tile_lat, tile_lon, resolution_m, bounds
        如果不是GDEM文件则返回None
    """
    import re

    for pattern in GDEM_FILENAME_PATTERNS:
        if re.match(pattern, filename, re.IGNORECASE):
            # 解析瓦片编号: ASTGTM2_N30E120_dem.tif -> lat=30, lon=120
            match = re.search(r"([NS])(\d{2})([EW])(\d{3})", filename)
            if match:
                lat_dir, lat_val, lon_dir, lon_val = match.groups()
                lat = int(lat_val) * (1 if lat_dir == "N" else -1)
                lon = int(lon_val) * (1 if lon_dir == "E" else -1)

                # 判断版本
                if "V003" in filename.upper() or "V3" in filename.upper():
                    source_type = "gdemv3"
                else:
                    source_type = "gdemv2"

                return {
                    "source_type": source_type,
                    "tile_lat": lat,
                    "tile_lon": lon,
                    "resolution_m": GDEM_DEFAULT_RESOLUTION_M,
                    "bounds": {
                        "west": float(lon),
                        "east": float(lon + 1),
                        "south": float(lat),
                        "north": float(lat + 1),
                    },
                }
    return None


def serialize_dataset(item: ElevationDataset) -> ElevationDatasetSummary:
    return ElevationDatasetSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        source=item.source,
        file_format=item.file_format,
        mount_code=item.mount_code,
        dataset_dir=item.dataset_dir,
        file_path=item.file_path,
        resolution_m=item.resolution_m,
        status=item.status,  # type: ignore[arg-type]
        usage_status=item.usage_status,  # type: ignore[arg-type]
        sample_count=item.sample_count,
        bbox_min_lon=item.bbox_min_lon,
        bbox_max_lon=item.bbox_max_lon,
        bbox_min_lat=item.bbox_min_lat,
        bbox_max_lat=item.bbox_max_lat,
        data_source_type=item.data_source_type,
        analysis_task_id=item.analysis_task_id,
        analysis_status=item.analysis_status,
        analysis_error_message=item.analysis_error_message,
        analysis_started_at=item.analysis_started_at,
        analysis_finished_at=item.analysis_finished_at,
        terrain_status=item.terrain_status,  # type: ignore[arg-type]
        terrain_task_id=item.terrain_task_id,
        terrain_error_message=item.terrain_error_message,
        terrain_root_path=item.terrain_root_path,
        terrain_url_template=item.terrain_url_template,
        terrain_min_zoom=item.terrain_min_zoom,
        terrain_max_zoom=item.terrain_max_zoom,
        terrain_bounds=item.terrain_bounds,
        terrain_metadata=item.terrain_metadata,
        notes=item.notes,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_job(item: ElevationApplyJob) -> ElevationApplyJobSummary:
    line = item.line
    dataset = item.dataset
    file_record = item.file_record
    return ElevationApplyJobSummary(
        id=item.id,
        line_id=item.line_id,
        line_code=line.code if line else None,
        line_name=line.name if line else None,
        file_record_id=item.file_record_id,
        file_record_name=file_record.file_name if file_record else None,
        dataset_id=item.dataset_id,
        dataset_code=dataset.code if dataset else None,
        dataset_name=dataset.name if dataset else None,
        mode=item.mode,  # type: ignore[arg-type]
        status=item.status,  # type: ignore[arg-type]
        task_id=item.task_id,
        total_tower_count=item.total_tower_count,
        updated_tower_count=item.updated_tower_count,
        skipped_tower_count=item.skipped_tower_count,
        missing_geo_count=item.missing_geo_count,
        unmatched_count=item.unmatched_count,
        error_message=item.error_message,
        started_at=item.started_at,
        finished_at=item.finished_at,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_data_import_job(item: ElevationDataImportJob) -> ElevationDataImportJobSummary:
    dataset = item.dataset
    file_record = item.file_record
    return ElevationDataImportJobSummary(
        id=item.id,
        dataset_id=item.dataset_id,
        file_record_id=item.file_record_id,
        file_record_name=file_record.file_name if file_record else None,
        dataset_code=dataset.code if dataset else None,
        dataset_name=dataset.name if dataset else None,
        status=item.status,  # type: ignore[arg-type]
        task_id=item.task_id,
        progress_percent=item.progress_percent,
        current_stage=item.current_stage,
        detail_message=item.detail_message,
        trigger_analysis=item.trigger_analysis,
        analysis_task_queued=item.analysis_task_queued,
        analysis_task_id=item.analysis_task_id,
        uploaded_file_count=item.uploaded_file_count,
        extracted_file_count=item.extracted_file_count,
        imported_file_count=item.imported_file_count,
        warning_count=item.warning_count,
        warnings=list(item.warnings_json or []),
        imported_files=list(item.imported_files_json or []),
        started_at=item.started_at,
        finished_at=item.finished_at,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_datasets(
    db: Session,
    *,
    keyword: str | None,
    status_filter: str | None,
) -> ElevationDatasetListResponse:
    stmt = select(ElevationDataset)
    total_stmt = select(func.count()).select_from(ElevationDataset)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = (
            ElevationDataset.code.ilike(like)
            | ElevationDataset.name.ilike(like)
            | ElevationDataset.source.ilike(like)
        )
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    if status_filter in {"active", "disabled"}:
        stmt = stmt.where(ElevationDataset.status == status_filter)
        total_stmt = total_stmt.where(ElevationDataset.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(ElevationDataset.update_date.desc(), ElevationDataset.code.asc())
    ).scalars().all()
    return ElevationDatasetListResponse(
        items=[serialize_dataset(item) for item in items],
        total=total,
    )


def get_dataset_by_id(db: Session, dataset_id: str) -> ElevationDataset | None:
    return db.execute(
        select(ElevationDataset).where(ElevationDataset.id == dataset_id)
    ).scalar_one_or_none()


def get_file_record_by_id(db: Session, record_id: str) -> ElevationFileRecord | None:
    return db.execute(
        select(ElevationFileRecord).where(ElevationFileRecord.id == record_id)
    ).scalar_one_or_none()


def get_dataset_by_code(db: Session, code: str) -> ElevationDataset | None:
    normalized = code.strip()
    if not normalized:
        return None
    return db.execute(
        select(ElevationDataset).where(
            func.lower(ElevationDataset.code) == normalized.lower()
        )
    ).scalar_one_or_none()


def get_data_import_job_by_id(db: Session, job_id: str) -> ElevationDataImportJob | None:
    return db.execute(
        select(ElevationDataImportJob).where(ElevationDataImportJob.id == job_id)
    ).scalar_one_or_none()


def _get_active_data_import_job_for_dataset(db: Session, dataset_id: str) -> ElevationDataImportJob | None:
    return db.execute(
        select(ElevationDataImportJob)
        .where(
            ElevationDataImportJob.dataset_id == dataset_id,
            ElevationDataImportJob.status.in_(("pending", "running")),
        )
        .order_by(ElevationDataImportJob.create_date.desc(), ElevationDataImportJob.id.desc())
    ).scalars().first()


def _supports_terrain_build(dataset: ElevationDataset) -> bool:
    return _resolve_dataset_file_format(dataset) in TERRAIN_SUPPORTED_DATASET_FORMATS


def _supports_file_record_terrain_build(record: ElevationFileRecord) -> bool:
    return _resolve_file_record_format(record) in TERRAIN_SUPPORTED_DATASET_FORMATS


def _default_terrain_status_for_format(file_format: str) -> str:
    return "pending" if file_format in TERRAIN_SUPPORTED_DATASET_FORMATS else "not_supported"


def _sync_dataset_terrain_support(dataset: ElevationDataset) -> None:
    file_format = _resolve_dataset_file_format(dataset)
    if file_format in TERRAIN_SUPPORTED_DATASET_FORMATS:
        if dataset.terrain_status == "not_supported":
            dataset.terrain_status = "pending"
        return

    dataset.terrain_status = "not_supported"
    dataset.terrain_task_id = None
    dataset.terrain_error_message = None
    dataset.terrain_root_path = None
    dataset.terrain_url_template = None
    dataset.terrain_min_zoom = None
    dataset.terrain_max_zoom = None
    dataset.terrain_bounds = None
    dataset.terrain_metadata = None


def _resolve_dataset_terrain_dir(dataset_code: str) -> str:
    return join_virtual_path(_resolve_dataset_dir(dataset_code), TERRAIN_ROOT_DIRNAME)


def _resolve_dataset_terrain_tile_path(*, dataset_code: str, z: int, x: int, y: int) -> str:
    return join_virtual_path(join_virtual_path(join_virtual_path(_resolve_dataset_terrain_dir(dataset_code), str(z)), str(x)), f"{y}.terrain")


def _resolve_file_record_terrain_dir(record_id: str) -> str:
    return f"/elevation/terrain/records/{record_id[:2]}/{record_id[2:4]}/{record_id}"


def _resolve_file_record_terrain_layer_path(record_id: str) -> str:
    return join_virtual_path(_resolve_file_record_terrain_dir(record_id), "layer.json")


def _resolve_file_record_terrain_tile_path(*, record_id: str, z: int, x: int, y: int) -> str:
    return join_virtual_path(join_virtual_path(join_virtual_path(_resolve_file_record_terrain_dir(record_id), str(z)), str(x)), f"{y}.terrain")


def _build_dataset_terrain_url_template(dataset_id: str) -> str:
    return f"/api/v1/elevation/datasets/{dataset_id}/terrain/{{z}}/{{x}}/{{y}}.terrain?v={TERRAIN_TILE_VERSION}"


def _build_file_record_terrain_url_template(record_id: str) -> str:
    return f"/terrain/{record_id}/{{z}}/{{x}}/{{y}}.terrain"


def _map_dataset_task_status(status_value: str | None) -> str:
    status_map = {
        "queued": "queued",
        "pending": "queued",
        "running": "running",
        "processing": "running",
        "success": "success",
        "ready": "success",
        "failed": "failed",
        "unknown": "unknown",
        "not_started": "not_found",
        "not_supported": "not_found",
    }
    return status_map.get(status_value or "", "unknown")


def list_dataset_files(
    db: Session,
    *,
    dataset_id: str,
) -> ElevationDatasetFileListResponse:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")

    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    dataset_dir = _resolve_dataset_dir(dataset.code)
    try:
        entries = driver.list_dir(dataset_dir)
    except StoragePathNotFoundError:
        entries = []
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # Query file metadata with bbox information
    stmt = select(ElevationDatasetFileMeta).where(
        ElevationDatasetFileMeta.dataset_id == dataset_id
    )
    file_metas = {meta.file_path: meta for meta in db.execute(stmt).scalars().all()}

    files = [
        ElevationDatasetFileItem(
            path=item.path,
            name=item.name,
            size=max(0, int(item.size)),
            modified_at=item.modified_at,
            mime_type=item.mime_type,
            bbox_min_lon=file_metas[item.path].bbox_min_lon if item.path in file_metas else None,
            bbox_max_lon=file_metas[item.path].bbox_max_lon if item.path in file_metas else None,
            bbox_min_lat=file_metas[item.path].bbox_min_lat if item.path in file_metas else None,
            bbox_max_lat=file_metas[item.path].bbox_max_lat if item.path in file_metas else None,
        )
        for item in entries
        if not item.is_dir
    ]
    files.sort(key=lambda item: item.name.lower())

    return ElevationDatasetFileListResponse(
        dataset_id=dataset.id,
        dataset_code=dataset.code,
        dataset_dir=dataset_dir,
        mount_code=dataset.mount_code,
        items=files,
        total=len(files),
    )


def create_dataset(
    db: Session,
    payload: ElevationDatasetCreateRequest,
    *,
    actor: User,
) -> ElevationDatasetSummary | None:
    normalized_code = payload.code.strip()
    if get_dataset_by_code(db, normalized_code):
        return None

    mount_code = _resolve_dataset_mount_code(db, requested_mount_code=payload.mount_code)
    dataset_dir = _resolve_dataset_dir(normalized_code)
    normalized_file_path: str
    file_format: str
    data_source_type = "generic"
    source = _normalize_str(payload.source)
    resolution_m = payload.resolution_m

    has_bound_file = _normalize_str(payload.file_name) is not None
    if has_bound_file:
        normalized_file_path = _resolve_dataset_file_path(
            dataset_code=normalized_code,
            filename=payload.file_name,
        )
        file_format = _detect_file_format(normalized_file_path)
        if file_format in RASTER_FILE_FORMATS:
            _require_rasterio_available()
        _ensure_dataset_file_exists(
            db,
            mount_code=mount_code,
            file_path=normalized_file_path,
        )

        # Detect GDEM data source type from filename
        gdem_info = _detect_gdem_dataset(payload.file_name)
        if gdem_info:
            data_source_type = gdem_info["source_type"]
            if resolution_m is None:
                resolution_m = gdem_info["resolution_m"]
            if source is None:
                source = "ASTER GDEM"
    else:
        normalized_file_path = _resolve_dataset_file_path(
            dataset_code=normalized_code,
            filename="dataset.csv",
        )
        file_format = "csv"

    now = utcnow()
    item = ElevationDataset(
        code=normalized_code,
        name=payload.name.strip(),
        source=source,
        file_format=file_format,
        mount_code=mount_code,
        dataset_dir=dataset_dir,
        file_path=normalized_file_path,
        resolution_m=resolution_m,
        status="active",
        usage_status="idle",
        data_source_type=data_source_type,
        terrain_status=_default_terrain_status_for_format(file_format),
        notes=_normalize_str(payload.notes),
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(item)
    db.commit()
    saved = get_dataset_by_id(db, item.id)
    if not saved:
        return None

    _publish_elevation_change(
        "elevation.dataset.created",
        {"action": "dataset_created", "dataset_id": saved.id},
    )
    return serialize_dataset(saved)


def import_datasets_from_csv(
    db: Session,
    *,
    file: UploadFile,
    actor: User,
) -> ElevationDatasetBatchImportResponse:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    text = _decode_text_bytes_for_import(content)
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV 文件没有可导入的数据行")

    stats = ElevationDatasetBatchImportStats()
    batch_created_ids: list[tuple[str, bool]] = []

    for row_index, row in enumerate(rows, start=2):
        normalized_row = {
            str(key).strip(): value
            for key, value in row.items()
            if key is not None
        }
        if all(not str(value or "").strip() for value in normalized_row.values()):
            continue

        code = _pick_csv_value(normalized_row, ["code", "编码"])
        name = _pick_csv_value(normalized_row, ["name", "名称"])
        mount_code = _pick_csv_value(normalized_row, ["mount_code", "挂载编码", "挂载"])
        file_name = _pick_csv_value(normalized_row, ["file_name", "文件名", "filename"])
        file_path = _pick_csv_value(normalized_row, ["file_path", "文件路径", "路径"])
        if not file_name and file_path:
            file_name = Path(file_path).name
        source = _pick_csv_value(normalized_row, ["source", "来源"])
        notes = _pick_csv_value(normalized_row, ["notes", "备注"])
        resolution_text = _pick_csv_value(normalized_row, ["resolution_m", "分辨率", "分辨率m", "分辨率(米)"])

        if not code or not name:
            stats.skipped_count += 1
            if stats.warnings is not None:
                stats.warnings.append(f"第 {row_index} 行缺少必填字段（code/name），已跳过")
            continue

        try:
            payload = ElevationDatasetCreateRequest(
                code=code,
                name=name,
                source=source,
                mount_code=mount_code,
                file_name=file_name,
                resolution_m=_parse_csv_optional_positive_float(resolution_text),
                notes=notes,
            )
            created = create_dataset(db, payload, actor=actor)
            if created is None:
                stats.skipped_count += 1
                if stats.warnings is not None:
                    stats.warnings.append(f"第 {row_index} 行编码重复（{code}），已跳过")
                continue
            stats.imported_count += 1
            if stats.items is not None:
                stats.items.append(created)
            batch_created_ids.append((created.id, bool(_normalize_str(file_name))))
        except HTTPException as exc:
            stats.skipped_count += 1
            detail = str(exc.detail) if exc.detail else "未知错误"
            if stats.warnings is not None:
                stats.warnings.append(f"第 {row_index} 行导入失败（{code}）：{detail}")
            continue

    for dataset_id, should_analyze in batch_created_ids:
        if not should_analyze:
            continue
        try:
            analyze_dataset(db, dataset_id=dataset_id, actor=actor)
            stats.analyzed_count += 1
        except HTTPException as exc:
            detail = str(exc.detail) if exc.detail else "未知错误"
            if stats.warnings is not None:
                stats.warnings.append(f"数据集 {dataset_id} 自动分析失败：{detail}")
        except Exception as exc:
            if stats.warnings is not None:
                stats.warnings.append(f"数据集 {dataset_id} 自动分析异常：{exc}")

    return ElevationDatasetBatchImportResponse(
        imported_count=stats.imported_count,
        analyzed_count=stats.analyzed_count,
        skipped_count=stats.skipped_count,
        warning_count=len(stats.warnings or []),
        warnings=stats.warnings or [],
        items=stats.items or [],
    )


def import_dataset_data_files(
    db: Session,
    *,
    dataset_id: str,
    files: list[UploadFile],
    actor: User,
    trigger_analysis: bool = True,
) -> ElevationDatasetDataImportResponse:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if dataset.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少上传一个文件")

    existing_job = _get_active_data_import_job_for_dataset(db, dataset_id)
    if existing_job is not None:
        return ElevationDatasetDataImportResponse(
            job=serialize_data_import_job(existing_job),
            queued=False,
            detail="导入任务已存在，无需重复提交。",
            warnings=list(existing_job.warnings_json or []),
        )

    now = utcnow()
    job = ElevationDataImportJob(
        dataset_id=dataset.id,
        status="pending",
        progress_percent=0,
        current_stage="pending",
        detail_message="导入任务已创建，等待上传文件。",
        trigger_analysis=trigger_analysis,
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(job)
    db.commit()

    saved = get_data_import_job_by_id(db, job.id)
    if saved is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建导入任务失败")

    upload_result: dict[str, Any] | None = None
    try:
        upload_result = _prepare_upload_files_for_staging(files=files)
        saved.uploaded_file_count = upload_result["uploaded_file_count"]
        saved.warning_count = len(upload_result["warnings"])
        saved.warnings_json = list(upload_result["warnings"])
        saved.staged_files_json = list(upload_result["upload_files"])
        saved.current_stage = "queued"
        saved.detail_message = "导入任务已提交，等待执行。"
        saved.progress_percent = 0
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()

        task = _dispatch_elevation_dataset_data_import_task(import_job_id=saved.id, actor_user_id=actor.id)
        saved.task_id = str(task.id)
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()
    except HTTPException as exc:
        db.rollback()
        failed = get_data_import_job_by_id(db, saved.id)
        if failed is not None:
            failed.status = "failed"
            failed.progress_percent = 100
            failed.current_stage = "failed"
            failed.detail_message = str(exc.detail)
            if upload_result is not None:
                failed.uploaded_file_count = upload_result["uploaded_file_count"]
                failed.warning_count = len(upload_result["warnings"])
                failed.warnings_json = list(upload_result["warnings"])
            failed.staged_files_json = []
            failed.finished_at = utcnow()
            failed.update_date = utcnow()
            failed.update_user = actor.id
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.import.failed",
                {"action": "dataset_import_failed", "dataset_id": dataset.id, "import_job_id": failed.id},
            )
        raise
    except Exception as exc:
        db.rollback()
        failed = get_data_import_job_by_id(db, saved.id)
        if failed is not None:
            failed.status = "failed"
            failed.progress_percent = 100
            failed.current_stage = "failed"
            failed.detail_message = f"导入任务派发失败：{exc}"
            if upload_result is not None:
                failed.uploaded_file_count = upload_result["uploaded_file_count"]
                failed.warning_count = len(upload_result["warnings"])
                failed.warnings_json = list(upload_result["warnings"])
            failed.staged_files_json = []
            failed.finished_at = utcnow()
            failed.update_date = utcnow()
            failed.update_user = actor.id
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.import.failed",
                {"action": "dataset_import_failed", "dataset_id": dataset.id, "import_job_id": failed.id},
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入任务派发失败: {exc}",
        ) from exc

    queued = get_data_import_job_by_id(db, saved.id)
    if queued is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="导入任务保存失败")

    _publish_elevation_change(
        "elevation.dataset.import.queued",
        {"action": "dataset_import_queued", "dataset_id": dataset.id, "import_job_id": queued.id, "task_id": queued.task_id},
    )
    return ElevationDatasetDataImportResponse(
        job=serialize_data_import_job(queued),
        queued=True,
        detail="导入任务已提交，等待执行。",
        warnings=list(queued.warnings_json or []),
    )


def get_dataset_analysis_task_status(
    db: Session,
    *,
    dataset_id: str,
) -> ElevationDatasetAnalysisTaskStatusResponse:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")

    status_value = dataset.analysis_status or "not_started"
    status_map = {
        "queued": "queued",
        "running": "running",
        "success": "success",
        "failed": "failed",
        "unknown": "unknown",
        "not_started": "not_found",
    }
    mapped_status = status_map.get(status_value, "unknown")
    detail = dataset.analysis_error_message
    if detail is None:
        if mapped_status == "queued":
            detail = "分析任务已提交，等待执行。"
        elif mapped_status == "running":
            detail = "分析任务执行中。"
        elif mapped_status == "success":
            detail = "最近一次分析已完成。"

    return ElevationDatasetAnalysisTaskStatusResponse(
        dataset_id=dataset.id,
        dataset_code=dataset.code,
        task_id=dataset.analysis_task_id,
        status=mapped_status,  # type: ignore[arg-type]
        detail=detail,
        started_at=dataset.analysis_started_at,
        finished_at=dataset.analysis_finished_at,
        update_date=dataset.update_date,
    )


def get_dataset_terrain_task_status(
    db: Session,
    *,
    dataset_id: str,
) -> ElevationDatasetTerrainTaskStatusResponse:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")

    mapped_status = _map_dataset_task_status(dataset.terrain_status)
    detail = dataset.terrain_error_message
    if detail is None:
        if mapped_status == "queued":
            detail = "地形瓦片任务已提交，等待执行。"
        elif mapped_status == "running":
            detail = "地形瓦片生成中。"
        elif mapped_status == "success":
            detail = "地形瓦片已就绪。"
        elif dataset.terrain_status == "not_supported":
            detail = "当前数据集格式不支持地形瓦片生成。"

    return ElevationDatasetTerrainTaskStatusResponse(
        dataset_id=dataset.id,
        dataset_code=dataset.code,
        task_id=dataset.terrain_task_id,
        status=mapped_status,  # type: ignore[arg-type]
        detail=detail,
        terrain_url_template=dataset.terrain_url_template,
        terrain_min_zoom=dataset.terrain_min_zoom,
        terrain_max_zoom=dataset.terrain_max_zoom,
        update_date=dataset.update_date,
    )


def list_data_import_jobs(
    db: Session,
    *,
    dataset_id: str | None,
    status_filter: str | None,
    limit: int,
) -> ElevationDataImportJobListResponse:
    stmt = select(ElevationDataImportJob)
    total_stmt = select(func.count()).select_from(ElevationDataImportJob)

    if dataset_id:
        stmt = stmt.where(ElevationDataImportJob.dataset_id == dataset_id)
        total_stmt = total_stmt.where(ElevationDataImportJob.dataset_id == dataset_id)
    if status_filter in {"pending", "running", "success", "failed"}:
        stmt = stmt.where(ElevationDataImportJob.status == status_filter)
        total_stmt = total_stmt.where(ElevationDataImportJob.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(ElevationDataImportJob.create_date.desc(), ElevationDataImportJob.id.desc()).limit(limit)
    ).scalars().all()
    return ElevationDataImportJobListResponse(
        items=[serialize_data_import_job(item) for item in items],
        total=total,
    )


def _resolve_dataset_import_stage_root_dir(dataset_code: str) -> str:
    return join_virtual_path(_resolve_dataset_dir(dataset_code), IMPORT_JOB_STAGE_DIRNAME)


def _resolve_dataset_import_stage_dir(*, dataset_code: str, import_job_id: str) -> str:
    return join_virtual_path(_resolve_dataset_import_stage_root_dir(dataset_code), import_job_id)


def _build_dataset_import_stage_filename(*, index: int, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f"{index:03d}-{uuid4().hex}{suffix}"


def _close_upload_file(upload: UploadFile) -> None:
    try:
        upload.file.close()
    except Exception:
        pass


def _prepare_upload_files_for_staging(
    *,
    files: list[UploadFile],
) -> dict[str, Any]:
    import base64

    upload_files: list[dict[str, str | None]] = []
    warnings: list[str] = []
    uploaded_file_count = 0

    for upload in files:
        filename = (upload.filename or "").strip()
        if not filename:
            warnings.append("存在空文件名上传项，已跳过")
            _close_upload_file(upload)
            continue

        suffix = Path(filename).suffix.lower()
        if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS and suffix not in IMPORTABLE_ARCHIVE_EXTENSIONS:
            warnings.append(f"文件 {filename} 类型不支持，已跳过（仅支持 TIF 格式）")
            _close_upload_file(upload)
            continue

        content = _read_upload_content(upload)
        content_base64 = base64.b64encode(content).decode("utf-8")

        upload_files.append(
            {
                "filename": filename,
                "content_type": upload.content_type,
                "content_base64": content_base64,
            }
        )
        uploaded_file_count += 1

    if not upload_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提交任何可用高程文件")

    return {
        "uploaded_file_count": uploaded_file_count,
        "warnings": warnings,
        "upload_files": upload_files,
    }


def _stage_dataset_import_job_uploads(
    *,
    driver: Any,
    dataset: ElevationDataset,
    import_job_id: str,
    files: list[UploadFile],
) -> dict[str, Any]:
    stage_root_dir = _resolve_dataset_import_stage_root_dir(dataset.code)
    stage_dir = _resolve_dataset_import_stage_dir(dataset_code=dataset.code, import_job_id=import_job_id)
    try:
        driver.ensure_directory(stage_root_dir)
        driver.ensure_directory(stage_dir)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    staged_files: list[dict[str, str | None]] = []
    warnings: list[str] = []
    uploaded_file_count = 0

    for index, upload in enumerate(files, start=1):
        filename = (upload.filename or "").strip()
        if not filename:
            warnings.append("存在空文件名上传项，已跳过")
            _close_upload_file(upload)
            continue

        suffix = Path(filename).suffix.lower()
        if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS and suffix not in IMPORTABLE_ARCHIVE_EXTENSIONS:
            warnings.append(f"文件 {filename} 类型不支持，已跳过（仅支持 TIF 格式）")
            _close_upload_file(upload)
            continue

        content = _read_upload_content(upload)
        stage_filename = _build_dataset_import_stage_filename(index=index, filename=filename)
        stage_path = join_virtual_path(stage_dir, stage_filename)
        try:
            driver.write_file(
                stage_path,
                content=content,
                content_type=upload.content_type or mimetypes.guess_type(filename)[0],
            )
        except StorageInvalidPathError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except StorageDriverError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        staged_files.append(
            {
                "path": stage_path,
                "filename": filename,
                "content_type": upload.content_type,
            }
        )
        uploaded_file_count += 1

    if not staged_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提交任何可用高程文件")

    return {
        "uploaded_file_count": uploaded_file_count,
        "warnings": warnings,
        "staged_files": staged_files,
    }


def _stage_dataset_import_job_uploads_from_serialized(
    *,
    driver: Any,
    dataset: ElevationDataset,
    import_job_id: str,
    upload_files: list[dict[str, str | None]],
) -> dict[str, Any]:
    import base64

    stage_root_dir = _resolve_dataset_import_stage_root_dir(dataset.code)
    stage_dir = _resolve_dataset_import_stage_dir(dataset_code=dataset.code, import_job_id=import_job_id)
    try:
        driver.ensure_directory(stage_root_dir)
        driver.ensure_directory(stage_dir)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    staged_files: list[dict[str, str | None]] = []
    warnings: list[str] = []
    uploaded_file_count = 0

    for index, upload_file in enumerate(upload_files, start=1):
        filename = _normalize_str(upload_file.get("filename"))
        if not filename:
            warnings.append("存在空文件名上传项，已跳过")
            continue

        suffix = Path(filename).suffix.lower()
        if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS and suffix not in IMPORTABLE_ARCHIVE_EXTENSIONS:
            warnings.append(f"文件 {filename} 类型不支持，已跳过（仅支持 csv/img/tif/tiff/zip）")
            continue

        content_base64 = _normalize_str(upload_file.get("content_base64"))
        if not content_base64:
            warnings.append(f"文件 {filename} 内容缺失，已跳过")
            continue

        try:
            content = base64.b64decode(content_base64)
        except Exception as exc:
            warnings.append(f"文件 {filename} 内容解码失败，已跳过")
            continue

        stage_filename = _build_dataset_import_stage_filename(index=index, filename=filename)
        stage_path = join_virtual_path(stage_dir, stage_filename)
        try:
            driver.write_file(
                stage_path,
                content=content,
                content_type=upload_file.get("content_type") or mimetypes.guess_type(filename)[0],
            )
        except StorageInvalidPathError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except StorageDriverError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        staged_files.append(
            {
                "path": stage_path,
                "filename": filename,
                "content_type": upload_file.get("content_type"),
            }
        )
        uploaded_file_count += 1

    if not staged_files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提交任何可用高程文件")

    return {
        "uploaded_file_count": uploaded_file_count,
        "warnings": warnings,
        "staged_files": staged_files,
    }


def _cleanup_staged_dataset_import_files(*, driver: Any, dataset_code: str, import_job_id: str) -> None:
    stage_dir = _resolve_dataset_import_stage_dir(dataset_code=dataset_code, import_job_id=import_job_id)
    try:
        driver.delete_path(stage_dir, is_dir=True, recursive=True)
    except StoragePathNotFoundError:
        return
    except Exception:
        return


def _perform_dataset_data_import(
    db: Session,
    *,
    dataset: ElevationDataset,
    driver: Any,
    actor_user_id: str | None,
    staged_files: list[dict[str, str | None]],
    trigger_analysis: bool,
    progress_hook: Callable[[int, str, str], None] | None = None,
) -> dict[str, Any]:
    dataset_dir = _resolve_dataset_dir(dataset.code)
    _ensure_dataset_directory(driver=driver, dataset_dir=dataset_dir)

    uploaded_file_count = 0
    extracted_file_count = 0
    warnings: list[str] = []
    imported_files: list[str] = []
    total_files = max(len(staged_files), 1)

    for index, staged_file in enumerate(staged_files, start=1):
        filename = _normalize_str(staged_file.get("filename")) or Path(str(staged_file.get("path") or "")).name
        staged_path = _normalize_str(staged_file.get("path"))
        if staged_path is None:
            warnings.append("存在缺少暂存路径的导入文件，已跳过")
            continue

        if progress_hook is not None:
            file_percent = 15 + math.floor((index - 1) * 55 / total_files)
            progress_hook(file_percent, "importing", f"正在处理文件 {index}/{total_files}：{filename}")

        try:
            staged_payload = driver.read_file(staged_path)
        except StoragePathNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"导入暂存文件不存在：{filename}") from exc
        except StorageInvalidPathError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except StorageDriverError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        suffix = Path(filename).suffix.lower()
        if suffix in IMPORTABLE_ARCHIVE_EXTENSIONS:
            zip_result = _extract_zip_to_dataset_directory(
                driver=driver,
                dataset_dir=dataset_dir,
                zip_content=staged_payload.content,
            )
            extracted_file_count += zip_result["extracted_count"]
            imported_files.extend(zip_result["imported_files"])
            warnings.extend(zip_result["warnings"])
            uploaded_file_count += 1
            continue

        if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS:
            warnings.append(f"文件 {filename} 类型不支持，已跳过（仅支持 csv/img/tif/tiff/zip）")
            continue

        target_path = _write_dataset_file(
            driver=driver,
            dataset_dir=dataset_dir,
            filename=filename,
            content=staged_payload.content,
            content_type=staged_file.get("content_type") or staged_payload.mime_type,
        )
        uploaded_file_count += 1
        imported_files.append(target_path)

    if progress_hook is not None:
        progress_hook(75, "finalizing", "正在刷新数据集元信息。")

    available_file_paths = _list_dataset_imported_file_paths(driver=driver, dataset_dir=dataset_dir)
    preferred_file_path = _pick_preferred_dataset_file_path(paths=available_file_paths, current_path=dataset.file_path)
    if preferred_file_path is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未导入任何可用高程文件")

    # Detect GDEM data source type from preferred file
    gdem_info = _detect_gdem_dataset(Path(preferred_file_path).name)
    if gdem_info:
        dataset.data_source_type = gdem_info["source_type"]
        if dataset.resolution_m is None:
            dataset.resolution_m = gdem_info["resolution_m"]
        if dataset.source is None:
            dataset.source = "ASTER GDEM"

    dataset.dataset_dir = dataset_dir
    dataset.file_path = preferred_file_path
    dataset.file_format = _detect_file_format(preferred_file_path)
    dataset.sample_count = 0
    dataset.bbox_min_lon = None
    dataset.bbox_max_lon = None
    dataset.bbox_min_lat = None
    dataset.bbox_max_lat = None
    dataset.usage_status = "idle"
    dataset.terrain_status = _default_terrain_status_for_format(dataset.file_format)
    dataset.terrain_task_id = None
    dataset.terrain_error_message = None
    dataset.terrain_root_path = None
    dataset.terrain_url_template = None
    dataset.terrain_min_zoom = None
    dataset.terrain_max_zoom = None
    dataset.terrain_bounds = None
    dataset.terrain_metadata = None
    dataset.analysis_task_id = None
    dataset.analysis_status = "not_started"
    dataset.analysis_error_message = None
    dataset.analysis_started_at = None
    dataset.analysis_finished_at = None
    dataset.update_user = actor_user_id
    dataset.update_date = utcnow()
    db.commit()

    if progress_hook is not None:
        progress_hook(85, "analyzing", "正在派发分析任务。")

    analysis_task_queued = False
    analysis_task_id: str | None = None
    if trigger_analysis:
        try:
            task = _dispatch_elevation_dataset_analysis_task(dataset_id=dataset.id, actor_user_id=actor_user_id)
            analysis_task_queued = True
            analysis_task_id = str(task.id)
            dataset.analysis_task_id = analysis_task_id
            dataset.analysis_status = "queued"
            dataset.analysis_error_message = None
            dataset.analysis_started_at = None
            dataset.analysis_finished_at = None
            dataset.update_date = utcnow()
            dataset.update_user = actor_user_id
            db.commit()
        except Exception as exc:  # pragma: no cover
            warnings.append(f"自动分析任务派发失败：{exc}")

    refreshed = get_dataset_by_id(db, dataset.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="数据集刷新失败")

    _publish_elevation_change(
        "elevation.dataset.data_imported",
        {"action": "dataset_data_imported", "dataset_id": refreshed.id},
    )

    imported_files_unique = sorted(set(imported_files))
    detail = (
        f"导入完成：上传 {uploaded_file_count} 个、解压 {extracted_file_count} 个、可用 {len(imported_files)} 个"
    )
    if progress_hook is not None:
        progress_hook(95, "completed", detail)

    return {
        "dataset": refreshed,
        "uploaded_file_count": uploaded_file_count,
        "extracted_file_count": extracted_file_count,
        "imported_file_count": len(imported_files),
        "analysis_task_queued": analysis_task_queued,
        "analysis_task_id": analysis_task_id,
        "warning_count": len(warnings),
        "warnings": warnings,
        "imported_files": imported_files_unique,
        "detail": detail,
    }


def queue_dataset_terrain_build(
    db: Session,
    *,
    dataset_id: str,
    actor: User,
) -> ElevationDatasetTerrainBuildResponse:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")
    if not _supports_terrain_build(item):
        item.terrain_status = "not_supported"
        item.terrain_task_id = None
        item.terrain_error_message = None
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前数据集格式不支持地形瓦片生成")

    if item.terrain_status == "processing" or (item.terrain_status == "pending" and item.terrain_task_id):
        return ElevationDatasetTerrainBuildResponse(
            dataset=serialize_dataset(item),
            task_id=item.terrain_task_id,
            queued=False,
            detail="地形瓦片任务已存在，无需重复提交。",
            warnings=[],
        )

    item.terrain_status = "pending"
    item.terrain_error_message = None
    item.terrain_root_path = None
    item.terrain_url_template = None
    item.terrain_min_zoom = None
    item.terrain_max_zoom = None
    item.terrain_bounds = None
    item.terrain_metadata = None
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    try:
        task = _dispatch_elevation_dataset_terrain_task(dataset_id=item.id, actor_user_id=actor.id)
    except Exception as exc:
        item.terrain_status = "failed"
        item.terrain_error_message = str(exc)
        item.terrain_task_id = None
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"地形瓦片任务派发失败: {exc}") from exc

    item.terrain_task_id = str(task.id)
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_dataset_by_id(db, dataset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="地形瓦片任务保存失败")

    _publish_elevation_change(
        "elevation.dataset.terrain.queued",
        {"action": "dataset_terrain_queued", "dataset_id": saved.id, "task_id": saved.terrain_task_id},
    )
    return ElevationDatasetTerrainBuildResponse(
        dataset=serialize_dataset(saved),
        task_id=saved.terrain_task_id,
        queued=True,
        detail="地形瓦片任务已提交，等待执行。",
        warnings=[],
    )


def get_dataset_terrain_layer(
    db: Session,
    *,
    dataset_id: str,
) -> ElevationTerrainLayerResponse:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if dataset.terrain_status != "ready" or not dataset.terrain_root_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片尚未就绪")

    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    layer_path = _resolve_dataset_terrain_layer_path(dataset.code)
    try:
        payload = driver.read_file(layer_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形 layer.json 不存在") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        data = json.loads(payload.content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="地形 layer.json 解析失败") from exc
    data.setdefault("minzoom", 0)
    return ElevationTerrainLayerResponse.model_validate(data)


def get_dataset_terrain_tile(
    db: Session,
    *,
    dataset_id: str,
    z: int,
    x: int,
    y: int,
) -> bytes:
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if dataset.terrain_status != "ready" or not dataset.terrain_root_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片尚未就绪")

    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    tile_path = _resolve_dataset_terrain_tile_path(dataset_code=dataset.code, z=z, x=x, y=y)
    try:
        payload = driver.read_file(tile_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片不存在") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return payload.content


def get_dataset_heightmap(
    db: Session,
    *,
    dataset_id: str,
    resolution: int = 513,
) -> dict:
    """导出 DEM 高度数组供 Three.js 前端使用"""
    from numpy import floor, linspace, meshgrid, minimum
    dataset = get_dataset_by_id(db, dataset_id)
    if not dataset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    with _open_raster_dataset(db, dataset) as opened:
        rasterio = _require_rasterio_available()
        src = opened.dataset
        data = src.read(1).astype(float)
        h, w = data.shape

        # Bilinear interpolation resampling to target resolution
        ys = linspace(0, h - 1, resolution)
        xs = linspace(0, w - 1, resolution)
        yv, xv = meshgrid(ys, xs, indexing="ij")
        y0 = floor(yv).astype(int)
        x0 = floor(xv).astype(int)
        y1 = minimum(y0 + 1, h - 1)
        x1 = minimum(x0 + 1, w - 1)
        dy = yv - y0
        dx = xv - x0
        resampled = (
            (1 - dy) * (1 - dx) * data[y0, x0]
            + (1 - dy) * dx * data[y0, x1]
            + dy * (1 - dx) * data[y1, x0]
            + dy * dx * data[y1, x1]
        )

        # Compute WGS84 bounds
        bounds = _compute_raster_wgs84_bounds(rasterio=rasterio, src=src)

    return {
        "width": resolution,
        "height": resolution,
        "west": bounds["west"],
        "south": bounds["south"],
        "east": bounds["east"],
        "north": bounds["north"],
        "minHeight": float(resampled.min()),
        "maxHeight": float(resampled.max()),
        "heights": resampled.ravel().tolist(),
    }


def get_file_record_analysis_task_status(
    db: Session,
    *,
    record_id: str,
) -> ElevationFileRecordTaskStatusResponse:
    record = get_file_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
    return ElevationFileRecordTaskStatusResponse(
        record_id=record.id,
        file_name=record.file_name,
        task_id=record.analysis_task_id,
        status=_map_dataset_task_status(record.analysis_status),  # type: ignore[arg-type]
        detail=record.analysis_error_message,
        started_at=record.analysis_started_at,
        finished_at=record.analysis_finished_at,
        update_date=record.update_date,
    )


def get_file_record_terrain_task_status(
    db: Session,
    *,
    record_id: str,
) -> ElevationFileRecordTerrainTaskStatusResponse:
    record = get_file_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
    return ElevationFileRecordTerrainTaskStatusResponse(
        record_id=record.id,
        file_name=record.file_name,
        task_id=record.terrain_task_id,
        status=_map_dataset_task_status(record.terrain_status),  # type: ignore[arg-type]
        detail=record.terrain_error_message,
        terrain_url_template=record.terrain_url_template,
        terrain_min_zoom=record.terrain_min_zoom,
        terrain_max_zoom=record.terrain_max_zoom,
        update_date=record.update_date,
    )


def get_file_record_terrain_layer(
    db: Session,
    *,
    record_id: str,
) -> ElevationTerrainLayerResponse:
    record = get_file_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
    if record.terrain_status != "ready" or not record.terrain_root_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片尚未就绪")

    mount = _require_mount(db, record.mount_code)
    driver = _build_driver_or_400(mount)
    layer_path = _resolve_file_record_terrain_layer_path(record.id)
    try:
        payload = driver.read_file(layer_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形 layer.json 不存在") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    try:
        data = json.loads(payload.content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="地形 layer.json 解析失败") from exc
    data.setdefault("minzoom", 0)
    return ElevationTerrainLayerResponse.model_validate(data)


def get_file_record_terrain_tile(
    db: Session,
    *,
    record_id: str,
    z: int,
    x: int,
    y: int,
) -> bytes:
    record = get_file_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
    if record.terrain_status != "ready" or not record.terrain_root_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片尚未就绪")

    mount = _require_mount(db, record.mount_code)
    driver = _build_driver_or_400(mount)
    tile_path = _resolve_file_record_terrain_tile_path(record_id=record.id, z=z, x=x, y=y)
    try:
        payload = driver.read_file(tile_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地形瓦片不存在") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return payload.content


def update_dataset(
    db: Session,
    dataset_id: str,
    payload: ElevationDatasetUpdateRequest,
    *,
    actor: User,
) -> ElevationDatasetSummary | None:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        item.name = str(update_data["name"]).strip()
    if "source" in update_data:
        item.source = _normalize_str(update_data["source"])
    if "resolution_m" in update_data:
        item.resolution_m = update_data["resolution_m"]
    if "status" in update_data and update_data["status"] is not None:
        item.status = str(update_data["status"]).strip().lower()
    if "notes" in update_data:
        item.notes = _normalize_str(update_data["notes"])

    _sync_dataset_terrain_support(item)
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()
    saved = get_dataset_by_id(db, dataset_id)
    if not saved:
        return None
    _publish_elevation_change(
        "elevation.dataset.updated",
        {"action": "dataset_updated", "dataset_id": saved.id},
    )
    return serialize_dataset(saved)


def delete_dataset(
    db: Session,
    dataset_id: str,
) -> bool:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        return False

    running_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(ElevationApplyJob)
            .where(
                ElevationApplyJob.dataset_id == dataset_id,
                ElevationApplyJob.status == "running",
            )
        )
        or 0
    )
    if running_job_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该数据集存在 {running_job_count} 个运行中的回填任务，暂不能删除",
        )

    db.execute(delete(ElevationApplyJob).where(ElevationApplyJob.dataset_id == dataset_id))
    db.delete(item)
    db.commit()
    _publish_elevation_change(
        "elevation.dataset.deleted",
        {"action": "dataset_deleted", "dataset_id": dataset_id},
    )
    return True


def analyze_dataset(
    db: Session,
    *,
    dataset_id: str,
    actor: User,
) -> ElevationDatasetAnalyzeResponse:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")

    item.analysis_status = "running"
    item.analysis_error_message = None
    if item.analysis_started_at is None:
        item.analysis_started_at = utcnow()
    item.analysis_finished_at = None
    item.update_date = utcnow()
    db.commit()

    try:
        stats, warnings = _analyze_dataset_content(db, item)
    except Exception as exc:
        item.analysis_status = "failed"
        item.analysis_error_message = str(exc)
        item.analysis_finished_at = utcnow()
        item.update_date = utcnow()
        db.commit()
        raise

    item.sample_count = stats["sample_count"]
    item.bbox_min_lon = stats["bbox_min_lon"]
    item.bbox_max_lon = stats["bbox_max_lon"]
    item.bbox_min_lat = stats["bbox_min_lat"]
    item.bbox_max_lat = stats["bbox_max_lat"]
    if _supports_terrain_build(item) and item.terrain_status == "not_supported":
        item.terrain_status = "pending"
    item.analysis_status = "success"
    item.analysis_error_message = None
    item.analysis_finished_at = utcnow()
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_dataset_by_id(db, dataset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="高程数据集分析保存失败")

    _publish_elevation_change(
        "elevation.dataset.analyzed",
        {"action": "dataset_analyzed", "dataset_id": saved.id},
    )
    _queue_dataset_terrain_build_after_analysis(db, dataset=saved, actor_user_id=actor.id)
    return ElevationDatasetAnalyzeResponse(
        dataset=serialize_dataset(saved),
        task_id=saved.analysis_task_id,
        queued=False,
        detail="最近一次分析已完成。",
        warnings=warnings,
    )


def queue_dataset_analysis(
    db: Session,
    *,
    dataset_id: str,
    actor: User,
) -> ElevationDatasetAnalyzeResponse:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")

    if item.analysis_status in {"queued", "running"}:
        return ElevationDatasetAnalyzeResponse(
            dataset=serialize_dataset(item),
            task_id=item.analysis_task_id,
            queued=False,
            detail="分析任务已存在，无需重复提交。",
            warnings=[],
        )

    item.analysis_status = "queued"
    item.analysis_error_message = None
    item.analysis_started_at = None
    item.analysis_finished_at = None
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    try:
        task = _dispatch_elevation_dataset_analysis_task(dataset_id=item.id, actor_user_id=actor.id)
    except Exception as exc:
        item.analysis_status = "failed"
        item.analysis_error_message = str(exc)
        item.analysis_finished_at = utcnow()
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"分析任务派发失败: {exc}") from exc

    item.analysis_task_id = str(task.id)
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_dataset_by_id(db, dataset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="高程数据集分析任务保存失败")

    _publish_elevation_change(
        "elevation.dataset.analysis.queued",
        {"action": "dataset_analysis_queued", "dataset_id": saved.id, "task_id": saved.analysis_task_id},
    )
    return ElevationDatasetAnalyzeResponse(
        dataset=serialize_dataset(saved),
        task_id=saved.analysis_task_id,
        queued=True,
        detail="分析任务已提交，等待执行。",
        warnings=[],
    )


def preview_dataset(
    db: Session,
    *,
    dataset_id: str,
    max_points: int,
) -> ElevationDatasetPreviewResponse:
    item = get_dataset_by_id(db, dataset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")

    preview_limit = max(1, min(max_points, 5000))
    file_format = _resolve_dataset_file_format(item)
    if file_format == "csv":
        points, warnings = _load_dataset_points(db, item)
        sampled = _sample_preview_points_from_csv(points=points, limit=preview_limit)
        return ElevationDatasetPreviewResponse(
            dataset=serialize_dataset(item),
            preview_mode="point_cloud",
            total_points=len(points),
            sampled_points=len(sampled),
            points=[ElevationDatasetPreviewPoint(longitude=point.lon, latitude=point.lat, altitude_m=point.altitude_m) for point in sampled],
            cells=[],
            diagnostics=ElevationDatasetPreviewDiagnostics(
                source_crs="EPSG:4326",
                source_bounds_min_x=min(point.lon for point in points),
                source_bounds_max_x=max(point.lon for point in points),
                source_bounds_min_y=min(point.lat for point in points),
                source_bounds_max_y=max(point.lat for point in points),
                wgs84_bounds_min_lon=min(point.lon for point in points),
                wgs84_bounds_max_lon=max(point.lon for point in points),
                wgs84_bounds_min_lat=min(point.lat for point in points),
                wgs84_bounds_max_lat=max(point.lat for point in points),
                raster_width=None,
                raster_height=None,
                target_samples=preview_limit,
                sampling_step=max(1, len(points) // max(1, len(sampled))) if sampled else None,
                scanned_candidates=len(points),
                valid_preview_count=len(sampled),
            ),
            warnings=warnings,
        )

    if file_format in RASTER_FILE_FORMATS:
        return _build_raster_preview(db, dataset=item, limit=preview_limit)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"不支持的高程文件格式: {file_format}",
    )


def list_jobs(
    db: Session,
    *,
    line_id: str | None,
    dataset_id: str | None,
    status_filter: str | None,
    limit: int,
    file_record_id: str | None = None,
) -> ElevationApplyJobListResponse:
    stmt = select(ElevationApplyJob)
    total_stmt = select(func.count()).select_from(ElevationApplyJob)

    if line_id:
        stmt = stmt.where(ElevationApplyJob.line_id == line_id)
        total_stmt = total_stmt.where(ElevationApplyJob.line_id == line_id)
    if dataset_id:
        stmt = stmt.where(ElevationApplyJob.dataset_id == dataset_id)
        total_stmt = total_stmt.where(ElevationApplyJob.dataset_id == dataset_id)
    if file_record_id:
        stmt = stmt.where(ElevationApplyJob.file_record_id == file_record_id)
        total_stmt = total_stmt.where(ElevationApplyJob.file_record_id == file_record_id)
    if status_filter in {"pending", "running", "success", "failed"}:
        stmt = stmt.where(ElevationApplyJob.status == status_filter)
        total_stmt = total_stmt.where(ElevationApplyJob.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(ElevationApplyJob.create_date.desc(), ElevationApplyJob.id.desc()).limit(limit)
    ).scalars().all()
    return ElevationApplyJobListResponse(
        items=[serialize_job(item) for item in items],
        total=total,
    )


def get_job_by_id(db: Session, job_id: str) -> ElevationApplyJob | None:
    return db.execute(
        select(ElevationApplyJob).where(ElevationApplyJob.id == job_id)
    ).scalar_one_or_none()


def create_apply_job(
    db: Session,
    payload: ElevationApplyJobCreateRequest,
    *,
    actor: User,
) -> ElevationApplyJobCreateResponse:
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    dataset: ElevationDataset | None = None
    file_record: ElevationFileRecord | None = None
    if payload.file_record_id:
        file_record = get_file_record_by_id(db, payload.file_record_id)
        if not file_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
        if file_record.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程文件记录未启用")
    elif payload.dataset_id:
        dataset = get_dataset_by_id(db, payload.dataset_id)
        if not dataset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
        if dataset.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据集未启用")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 file_record_id 或 dataset_id")

    allowed_modes = {"fill_null_only", "overwrite_all"}
    if payload.mode not in allowed_modes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的回填模式")

    total_tower_count = int(
        db.scalar(
            select(func.count())
            .select_from(LineTower)
            .where(LineTower.line_id == line.id)
        )
        or 0
    )
    if total_tower_count <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可回填的杆塔数据")

    now = utcnow()
    job = ElevationApplyJob(
        line_id=line.id,
        dataset_id=dataset.id if dataset is not None else None,
        file_record_id=file_record.id if file_record is not None else None,
        mode=payload.mode,
        status="pending",
        total_tower_count=total_tower_count,
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(job)
    db.commit()
    saved = get_job_by_id(db, job.id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建任务失败")

    task = _dispatch_elevation_apply_task(job_id=saved.id, actor_user_id=actor.id)
    saved.task_id = task.id
    saved.update_user = actor.id
    saved.update_date = utcnow()
    db.commit()

    latest = get_job_by_id(db, saved.id)
    if not latest:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务派发失败")

    if latest.dataset_id:
        _refresh_dataset_usage_status(db, dataset_id=latest.dataset_id)

    _publish_elevation_change(
        "elevation.job.created",
        {
            "action": "job_created",
            "job_id": latest.id,
            "line_id": latest.line_id,
            "dataset_id": latest.dataset_id,
            "file_record_id": latest.file_record_id,
        },
    )
    return ElevationApplyJobCreateResponse(job=serialize_job(latest), queued=True)


def _dispatch_elevation_apply_task(*, job_id: str, actor_user_id: str | None):
    from ..tasks.elevation_tasks import apply_elevation_for_line_job

    return apply_elevation_for_line_job.delay(job_id, actor_user_id)


def _dispatch_elevation_dataset_analysis_task(*, dataset_id: str, actor_user_id: str | None):
    from ..tasks.elevation_tasks import analyze_elevation_dataset_job

    return analyze_elevation_dataset_job.delay(dataset_id, actor_user_id)


def _dispatch_elevation_dataset_terrain_task(*, dataset_id: str, actor_user_id: str | None):
    from ..tasks.elevation_tasks import build_elevation_dataset_terrain_job

    return build_elevation_dataset_terrain_job.delay(dataset_id, actor_user_id)


def _dispatch_elevation_dataset_data_import_task(*, import_job_id: str, actor_user_id: str | None):
    from ..tasks.elevation_tasks import import_elevation_dataset_data_job

    return import_elevation_dataset_data_job.delay(import_job_id, actor_user_id)


def execute_apply_job(job_id: str, actor_user_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            return
        if job.status in {"success", "failed"}:
            return
        resolved_actor_user_id = actor_user_id or job.create_user or job.update_user

        job.status = "running"
        job.started_at = utcnow()
        job.update_date = utcnow()
        db.commit()
        if job.dataset_id:
            _refresh_dataset_usage_status(db, dataset_id=job.dataset_id)
        _publish_elevation_change(
            "elevation.job.running",
            {
                "action": "job_running",
                "job_id": job.id,
                "line_id": job.line_id,
                "dataset_id": job.dataset_id,
                "file_record_id": job.file_record_id,
            },
        )

        line = db.execute(select(Line).where(Line.id == job.line_id)).scalar_one_or_none()
        dataset = get_dataset_by_id(db, job.dataset_id) if job.dataset_id else None
        file_record = get_file_record_by_id(db, job.file_record_id) if job.file_record_id else None
        elevation_source = file_record or dataset
        if not line or elevation_source is None:
            job.status = "failed"
            job.error_message = "线路或高程文件记录不存在"
            job.finished_at = utcnow()
            job.update_date = utcnow()
            db.commit()
            if job.dataset_id:
                _refresh_dataset_usage_status(db, dataset_id=job.dataset_id)
            _publish_elevation_change(
                "elevation.job.failed",
                {
                    "action": "job_failed",
                    "job_id": job.id,
                    "line_id": job.line_id,
                    "dataset_id": job.dataset_id,
                    "file_record_id": job.file_record_id,
                },
            )
            return

        file_format = _resolve_elevation_file_format(elevation_source)
        if file_format == "csv":
            points, warnings = _load_dataset_points(db, elevation_source)
            stats = _apply_points_to_line_towers(
                db,
                line_id=line.id,
                elevation_source=elevation_source,
                mode=job.mode,
                points=points,
            )
        elif file_format in RASTER_FILE_FORMATS:
            stats, warnings = _apply_raster_to_line_towers(
                db,
                line_id=line.id,
                elevation_source=elevation_source,
                mode=job.mode,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的高程文件格式: {file_format}",
            )

        if dataset is not None:
            _refresh_dataset_usage_status(db, dataset_id=dataset.id)

        warning_note = "; ".join(warnings[:5]) if warnings else None
        job.updated_tower_count = stats["updated_tower_count"]
        job.skipped_tower_count = stats["skipped_tower_count"]
        job.missing_geo_count = stats["missing_geo_count"]
        job.unmatched_count = stats["unmatched_count"]
        job.status = "success"
        job.error_message = warning_note
        job.finished_at = utcnow()
        job.update_date = utcnow()
        line.update_date = utcnow()
        line.update_user = resolved_actor_user_id
        record_line_preparation_source(
            line,
            component="ground_slope",
            payload={
                "prepared_at": utcnow().isoformat(),
                "prepared_by_user_id": resolved_actor_user_id,
                "dataset_id": dataset.id if dataset is not None else None,
                "dataset_code": dataset.code if dataset is not None else None,
                "file_record_id": file_record.id if file_record is not None else None,
                "file_record_name": file_record.file_name if file_record is not None else None,
                "job_id": job.id,
                "mode": job.mode,
                "updated_tower_count": job.updated_tower_count,
                "missing_geo_count": job.missing_geo_count,
                "unmatched_count": job.unmatched_count,
            },
        )
        db.commit()
        if job.dataset_id:
            _refresh_dataset_usage_status(db, dataset_id=job.dataset_id)

        _publish_elevation_change(
            "elevation.job.success",
            {
                "action": "job_success",
                "job_id": job.id,
                "line_id": line.id,
                "dataset_id": job.dataset_id,
                "file_record_id": job.file_record_id,
                "updated_tower_count": job.updated_tower_count,
                "skipped_tower_count": job.skipped_tower_count,
            },
        )
        _publish_line_change(
            "power-lines.elevation.updated",
            {"action": "elevation_updated", "line_id": line.id, "job_id": job.id},
        )
    except Exception as exc:
        db.rollback()
        failed = get_job_by_id(db, job_id)
        if failed:
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.finished_at = utcnow()
            failed.update_date = utcnow()
            db.commit()
            if failed.dataset_id:
                _refresh_dataset_usage_status(db, dataset_id=failed.dataset_id)
            _publish_elevation_change(
                "elevation.job.failed",
                {
                    "action": "job_failed",
                    "job_id": failed.id,
                    "line_id": failed.line_id,
                    "dataset_id": failed.dataset_id,
                    "file_record_id": failed.file_record_id,
                },
            )
        raise
    finally:
        db.close()


def execute_dataset_analysis_job(*, dataset_id: str, actor_user_id: str | None) -> None:
    db = SessionLocal()
    try:
        item = get_dataset_by_id(db, dataset_id)
        if not item:
            return

        item.analysis_status = "running"
        item.analysis_error_message = None
        item.analysis_started_at = utcnow()
        item.analysis_finished_at = None
        item.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.analysis.running",
            {"action": "dataset_analysis_running", "dataset_id": item.id},
        )

        actor = db.execute(select(User).where(User.id == actor_user_id)).scalar_one_or_none() if actor_user_id else None
        if actor is None:
            actor = db.execute(select(User).where(User.status == "active").order_by(User.id.asc())).scalars().first()
        if actor is None:
            item.analysis_status = "failed"
            item.analysis_error_message = "未找到可用用户执行分析"
            item.analysis_finished_at = utcnow()
            item.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.analysis.failed",
                {"action": "dataset_analysis_failed", "dataset_id": item.id},
            )
            return

        analyze_dataset(db, dataset_id=dataset_id, actor=actor)
        saved = get_dataset_by_id(db, dataset_id)
        if saved is None:
            return
        saved.analysis_status = "success"
        saved.analysis_error_message = None
        saved.analysis_finished_at = utcnow()
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.analysis.success",
            {"action": "dataset_analysis_success", "dataset_id": saved.id},
        )
    except Exception as exc:
        failed = get_dataset_by_id(db, dataset_id)
        if failed is not None:
            failed.analysis_status = "failed"
            failed.analysis_error_message = str(exc)
            failed.analysis_finished_at = utcnow()
            failed.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.analysis.failed",
                {"action": "dataset_analysis_failed", "dataset_id": failed.id},
            )
        raise
    finally:
        db.close()


def execute_dataset_data_import_job(*, import_job_id: str, actor_user_id: str | None) -> None:
    db = SessionLocal()
    try:
        job = get_data_import_job_by_id(db, import_job_id)
        if not job:
            return
        if job.status in {"success", "failed"}:
            return

        dataset = get_dataset_by_id(db, job.dataset_id)
        if dataset is None:
            job.status = "failed"
            job.progress_percent = 100
            job.current_stage = "failed"
            job.detail_message = "高程数据集不存在"
            job.finished_at = utcnow()
            job.update_date = utcnow()
            db.commit()
            return

        mount = _require_mount(db, dataset.mount_code)
        driver = _build_driver_or_400(mount)

        def progress_hook(progress_percent: int, stage: str, detail: str) -> None:
            saved = get_data_import_job_by_id(db, import_job_id)
            if saved is None:
                return
            saved.progress_percent = max(0, min(100, progress_percent))
            saved.current_stage = stage
            saved.detail_message = detail
            saved.update_date = utcnow()
            saved.update_user = actor_user_id or saved.update_user
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.import.progress",
                {
                    "action": "dataset_import_progress",
                    "dataset_id": saved.dataset_id,
                    "import_job_id": saved.id,
                    "progress_percent": saved.progress_percent,
                    "stage": saved.current_stage,
                },
            )

        job.status = "running"
        job.progress_percent = 5
        job.current_stage = "staging"
        job.detail_message = "正在暂存上传文件。"
        job.started_at = utcnow()
        job.finished_at = None
        job.update_date = utcnow()
        job.update_user = actor_user_id or job.update_user
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.import.running",
            {"action": "dataset_import_running", "dataset_id": job.dataset_id, "import_job_id": job.id},
        )

        upload_files = list(job.staged_files_json or [])
        if not upload_files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到待暂存的上传文件")

        stage_result = _stage_dataset_import_job_uploads_from_serialized(
            driver=driver,
            dataset=dataset,
            import_job_id=job.id,
            upload_files=upload_files,
        )

        combined_warnings = list(job.warnings_json or []) + list(stage_result["warnings"])
        job.uploaded_file_count = stage_result["uploaded_file_count"]
        job.warning_count = len(combined_warnings)
        job.warnings_json = combined_warnings
        job.staged_files_json = list(stage_result["staged_files"])
        job.progress_percent = 10
        job.current_stage = "running"
        job.detail_message = "开始导入数据文件。"
        job.update_date = utcnow()
        job.update_user = actor_user_id or job.update_user
        db.commit()

        result = _perform_dataset_data_import(
            db,
            dataset=dataset,
            driver=driver,
            actor_user_id=actor_user_id,
            staged_files=list(job.staged_files_json or []),
            trigger_analysis=job.trigger_analysis,
            progress_hook=progress_hook,
        )

        saved = get_data_import_job_by_id(db, import_job_id)
        if saved is None:
            return
        combined_warnings_final = list(saved.warnings_json or []) + list(result["warnings"])
        saved.status = "success"
        saved.progress_percent = 100
        saved.current_stage = "completed"
        saved.detail_message = result["detail"]
        saved.analysis_task_queued = result["analysis_task_queued"]
        saved.analysis_task_id = result["analysis_task_id"]
        saved.uploaded_file_count = result["uploaded_file_count"]
        saved.extracted_file_count = result["extracted_file_count"]
        saved.imported_file_count = result["imported_file_count"]
        saved.warning_count = len(combined_warnings_final)
        saved.warnings_json = combined_warnings_final
        saved.imported_files_json = list(result["imported_files"])
        saved.staged_files_json = []
        saved.finished_at = utcnow()
        saved.update_date = utcnow()
        saved.update_user = actor_user_id or saved.update_user
        db.commit()
        _cleanup_staged_dataset_import_files(driver=driver, dataset_code=dataset.code, import_job_id=saved.id)
        _publish_elevation_change(
            "elevation.dataset.import.success",
            {"action": "dataset_import_success", "dataset_id": saved.dataset_id, "import_job_id": saved.id},
        )
    except Exception as exc:
        db.rollback()
        failed = get_data_import_job_by_id(db, import_job_id)
        dataset = get_dataset_by_id(db, failed.dataset_id) if failed is not None else None
        if failed is not None:
            failed.status = "failed"
            failed.progress_percent = 100
            failed.current_stage = "failed"
            failed.detail_message = str(exc)
            failed.finished_at = utcnow()
            failed.update_date = utcnow()
            failed.update_user = actor_user_id or failed.update_user
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.import.failed",
                {
                    "action": "dataset_import_failed",
                    "dataset_id": failed.dataset_id,
                    "import_job_id": failed.id,
                },
            )
        if dataset is not None:
            try:
                mount = _require_mount(db, dataset.mount_code)
                driver = _build_driver_or_400(mount)
                _cleanup_staged_dataset_import_files(driver=driver, dataset_code=dataset.code, import_job_id=import_job_id)
            except Exception:
                pass
        raise
    finally:
        db.close()


def execute_dataset_terrain_build_job(*, dataset_id: str, actor_user_id: str | None) -> None:
    db = SessionLocal()
    try:
        item = get_dataset_by_id(db, dataset_id)
        if not item:
            return
        if not _supports_terrain_build(item):
            item.terrain_status = "not_supported"
            item.terrain_task_id = None
            item.terrain_error_message = None
            item.update_date = utcnow()
            db.commit()
            return

        item.terrain_status = "processing"
        item.terrain_error_message = None
        item.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.terrain.running",
            {"action": "dataset_terrain_running", "dataset_id": item.id},
        )

        actor = db.execute(select(User).where(User.id == actor_user_id)).scalar_one_or_none() if actor_user_id else None
        if actor is None:
            actor = db.execute(select(User).where(User.status == "active").order_by(User.id.asc())).scalars().first()
        if actor is None:
            item.terrain_status = "failed"
            item.terrain_error_message = "未找到可用用户执行地形瓦片生成"
            item.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.terrain.failed",
                {"action": "dataset_terrain_failed", "dataset_id": item.id},
            )
            return

        artifacts = _build_dataset_terrain_tiles(db, item)
        saved = get_dataset_by_id(db, dataset_id)
        if saved is None:
            return
        saved.terrain_status = "ready"
        saved.terrain_error_message = None
        saved.terrain_root_path = _resolve_dataset_terrain_dir(saved.code)
        saved.terrain_url_template = _build_dataset_terrain_url_template(saved.id)
        saved.terrain_min_zoom = artifacts.min_zoom
        saved.terrain_max_zoom = artifacts.max_zoom
        saved.terrain_bounds = artifacts.bounds
        saved.terrain_metadata = artifacts.metadata
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.terrain.ready",
            {"action": "dataset_terrain_ready", "dataset_id": saved.id},
        )
    except Exception as exc:
        failed = get_dataset_by_id(db, dataset_id)
        if failed is not None:
            failed.terrain_status = "failed"
            failed.terrain_error_message = str(exc)
            failed.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.dataset.terrain.failed",
                {"action": "dataset_terrain_failed", "dataset_id": failed.id},
            )
        raise
    finally:
        db.close()


def _queue_dataset_terrain_build_after_analysis(db: Session, *, dataset: ElevationDataset, actor_user_id: str | None) -> None:
    if not _supports_terrain_build(dataset):
        return
    if dataset.terrain_status in {"processing", "ready"}:
        return
    if dataset.terrain_status == "pending" and dataset.terrain_task_id:
        return
    dataset.terrain_status = "pending"
    dataset.terrain_error_message = None
    dataset.update_date = utcnow()
    db.commit()
    try:
        task = _dispatch_elevation_dataset_terrain_task(dataset_id=dataset.id, actor_user_id=actor_user_id)
        dataset.terrain_task_id = str(task.id)
        dataset.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.terrain.queued",
            {"action": "dataset_terrain_queued", "dataset_id": dataset.id, "task_id": dataset.terrain_task_id},
        )
    except Exception as exc:
        dataset.terrain_status = "failed"
        dataset.terrain_error_message = str(exc)
        dataset.update_date = utcnow()
        db.commit()


def _queue_file_record_terrain_build_after_analysis(db: Session, *, record: ElevationFileRecord, actor_user_id: str | None) -> None:
    if not _supports_file_record_terrain_build(record):
        return
    if record.terrain_status in {"processing", "ready"}:
        return
    if record.terrain_status == "pending" and record.terrain_task_id:
        return
    record.terrain_status = "pending"
    record.terrain_error_message = None
    record.update_date = utcnow()
    db.commit()
    try:
        from ..tasks.elevation_tasks import build_elevation_file_record_terrain_job

        task = build_elevation_file_record_terrain_job.delay(record.id, actor_user_id)
        record.terrain_task_id = str(task.id)
        record.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.file_record.terrain.queued",
            {"action": "file_record_terrain_queued", "file_record_id": record.id, "task_id": record.terrain_task_id},
        )
    except Exception as exc:
        record.terrain_status = "failed"
        record.terrain_error_message = str(exc)
        record.update_date = utcnow()
        db.commit()


def _ensure_dataset_file_exists(db: Session, *, mount_code: str, file_path: str) -> None:
    mount = _require_mount(db, mount_code.strip())
    driver = _build_driver_or_400(mount)
    normalized_path = normalize_virtual_path(file_path.strip())
    try:
        driver.read_file(normalized_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"数据文件不存在: {normalized_path}") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _resolve_dataset_mount_code(db: Session, *, requested_mount_code: str | None) -> str:
    code = _normalize_str(requested_mount_code)
    if code is not None:
        _require_mount(db, code)
        return code

    mounts = list_enabled_mounts(db)
    if not mounts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无可用文件挂载点")
    return mounts[0].code


def _resolve_dataset_dir(dataset_code: str) -> str:
    normalized_code = _normalize_dataset_code(dataset_code)
    return f"{ELEVATION_DATASET_ROOT}/{normalized_code}"


def _resolve_dataset_file_path(*, dataset_code: str, filename: str | None) -> str:
    normalized_name = _normalize_dataset_filename(filename)
    dataset_dir = _resolve_dataset_dir(dataset_code)
    return join_virtual_path(dataset_dir, normalized_name)


def _resolve_dataset_terrain_layer_path(dataset_code: str) -> str:
    return join_virtual_path(_resolve_dataset_terrain_dir(dataset_code), "layer.json")


def _normalize_dataset_code(value: str) -> str:
    code = value.strip()
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据集编码不能为空")
    if any(char in code for char in ("/", "\\")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="数据集编码不能包含路径分隔符")
    return code


def _normalize_dataset_filename(value: str | None) -> str:
    name = (value or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")
    name = Path(name).name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不合法")
    suffix = Path(name).suffix.lower()
    if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的高程文件类型: {suffix or 'unknown'}，仅支持 .csv/.img/.tif/.tiff",
        )
    return name


def _ensure_dataset_directory(*, driver: Any, dataset_dir: str) -> None:
    try:
        normalized_dir = normalize_virtual_path(dataset_dir)
        driver.ensure_directory(ELEVATION_DATASET_ROOT)
        driver.ensure_directory(normalized_dir)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _read_upload_content(upload: UploadFile) -> bytes:
    name = (upload.filename or "-").strip() or "-"
    try:
        content = upload.file.read()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"读取上传文件失败：{exc}") from exc
    finally:
        try:
            upload.file.close()
        except Exception:
            pass
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"上传文件为空：{name}")
    return content


def _write_dataset_file(
    *,
    driver: Any,
    dataset_dir: str,
    filename: str,
    content: bytes,
    content_type: str | None,
) -> str:
    normalized_name = _normalize_dataset_filename(filename)
    target_path = join_virtual_path(dataset_dir, normalized_name)
    try:
        driver.write_file(
            target_path,
            content=content,
            content_type=content_type or mimetypes.guess_type(normalized_name)[0],
        )
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return target_path


def _extract_zip_to_dataset_directory(
    *,
    driver: Any,
    dataset_dir: str,
    zip_content: bytes,
) -> dict[str, Any]:
    warnings: list[str] = []
    imported_files: list[str] = []
    extracted_count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_name = Path(member.filename).name
                if not member_name:
                    warnings.append(f"压缩包条目 {member.filename} 文件名无效，已跳过")
                    continue
                suffix = Path(member_name).suffix.lower()
                if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS:
                    warnings.append(f"压缩包条目 {member_name} 类型不支持，已跳过")
                    continue
                try:
                    data = archive.read(member)
                except Exception as exc:
                    warnings.append(f"压缩包条目 {member_name} 读取失败：{exc}")
                    continue
                if not data:
                    warnings.append(f"压缩包条目 {member_name} 内容为空，已跳过")
                    continue
                path = _write_dataset_file(
                    driver=driver,
                    dataset_dir=dataset_dir,
                    filename=member_name,
                    content=data,
                    content_type=mimetypes.guess_type(member_name)[0],
                )
                imported_files.append(path)
                extracted_count += 1
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"ZIP 文件损坏：{exc}") from exc
    return {
        "warnings": warnings,
        "imported_files": imported_files,
        "extracted_count": extracted_count,
    }


def _list_dataset_imported_file_paths(*, driver: Any, dataset_dir: str) -> list[str]:
    try:
        entries = driver.list_dir(dataset_dir)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"高程数据目录不存在: {dataset_dir}") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return [
        entry.path
        for entry in entries
        if not entry.is_dir and Path(entry.name).suffix.lower() in IMPORTABLE_ELEVATION_EXTENSIONS
    ]


def _pick_preferred_dataset_file_path(*, paths: list[str], current_path: str | None = None) -> str | None:
    if not paths:
        return None
    for extension in (".img", ".tif", ".tiff", ".csv"):
        matching_paths = [path for path in paths if path.lower().endswith(extension)]
        if not matching_paths:
            continue
        if current_path in matching_paths:
            return current_path
        return matching_paths[0]
    if current_path in paths:
        return current_path
    return paths[0]


def _refresh_dataset_usage_status(db: Session, *, dataset_id: str) -> None:
    dataset = get_dataset_by_id(db, dataset_id)
    if dataset is None:
        return
    running_count = int(
        db.scalar(
            select(func.count())
            .select_from(ElevationApplyJob)
            .where(
                ElevationApplyJob.dataset_id == dataset_id,
                ElevationApplyJob.status.in_(("pending", "running")),
            )
        )
        or 0
    )
    next_status = "in_use" if running_count > 0 else "idle"
    if dataset.usage_status != next_status:
        dataset.usage_status = next_status
        dataset.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.dataset.usage_status_changed",
            {"action": "dataset_usage_status_changed", "dataset_id": dataset_id},
        )


def _load_dataset_points(
    db: Session,
    dataset: ElevationDataset | ElevationFileRecord,
) -> tuple[list[ElevationSamplePoint], list[str]]:
    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    try:
        read_result = driver.read_file(dataset.file_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"高程数据文件不存在: {dataset.file_path}") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    text = _decode_csv_bytes(read_result.content)
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据文件为空")

    points: list[ElevationSamplePoint] = []
    warnings: list[str] = []
    for index, row in enumerate(rows, start=2):
        lon = _pick_float(row, ["longitude", "lon", "lng", "经度"])
        lat = _pick_float(row, ["latitude", "lat", "纬度"])
        altitude = _pick_float(row, ["altitude_m", "altitude", "elevation", "dem", "海拔m", "高程"])
        if lon is None or lat is None or altitude is None:
            warnings.append(f"第 {index} 行缺少经纬度或高程，已忽略")
            continue
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            warnings.append(f"第 {index} 行经纬度越界，已忽略")
            continue
        points.append(ElevationSamplePoint(lon=lon, lat=lat, altitude_m=altitude))

    if not points:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程数据文件没有有效样本点")
    return points, warnings


def _compute_dataset_stats(points: list[ElevationSamplePoint]) -> dict[str, float | int]:
    lon_values = [item.lon for item in points]
    lat_values = [item.lat for item in points]
    return {
        "sample_count": len(points),
        "bbox_min_lon": min(lon_values),
        "bbox_max_lon": max(lon_values),
        "bbox_min_lat": min(lat_values),
        "bbox_max_lat": max(lat_values),
    }


def _sample_preview_points_from_csv(
    *,
    points: list[ElevationSamplePoint],
    limit: int,
) -> list[ElevationSamplePoint]:
    if len(points) <= limit:
        return points
    if limit <= 1:
        return [points[0]]
    step = max(1, len(points) // limit)
    sampled = points[::step]
    if len(sampled) > limit:
        sampled = sampled[:limit]
    return sampled


def _analyze_dataset_content(
    db: Session,
    dataset: ElevationDataset,
) -> tuple[dict[str, float | int], list[str]]:
    # First, analyze the main dataset file (for overall stats)
    file_format = _resolve_dataset_file_format(dataset)
    if file_format == "csv":
        points, warnings = _load_dataset_points(db, dataset)
        overall_stats = _compute_dataset_stats(points)
    elif file_format in RASTER_FILE_FORMATS:
        overall_stats, warnings = _compute_raster_stats(db, dataset)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的高程文件格式: {file_format}",
        )

    # Detect GDEM data source type from main file
    gdem_info = _detect_gdem_dataset(Path(dataset.file_path).name)
    if gdem_info:
        dataset.data_source_type = gdem_info["source_type"]
        if dataset.resolution_m is None:
            dataset.resolution_m = gdem_info["resolution_m"]
        # Update source if not set
        if dataset.source is None:
            dataset.source = "ASTER GDEM" if gdem_info["source_type"] in ["gdemv2", "gdemv3"] else dataset.source

    # Then, analyze each file in the dataset directory for file-level metadata
    try:
        mount = _require_mount(db, dataset.mount_code)
        driver = _build_driver_or_400(mount)
        dataset_dir = _resolve_dataset_dir(dataset.code)

        try:
            entries = driver.list_dir(dataset_dir)
        except (StoragePathNotFoundError, StorageInvalidPathError, StorageDriverError):
            entries = []

        for entry in entries:
            if entry.is_dir:
                continue

            file_ext = Path(entry.path).suffix.lower()
            if file_ext not in ELEVATION_FILE_EXT_FORMAT_MAP:
                continue

            file_stats_result = _analyze_single_file(db, dataset, entry.path)
            if file_stats_result is not None:
                file_stats, _ = file_stats_result
                _store_file_metadata(
                    db,
                    dataset_id=dataset.id,
                    file_path=entry.path,
                    file_name=entry.name,
                    stats=file_stats,
                )
    except Exception:
        # If file-level analysis fails, don't fail the whole dataset analysis
        pass

    return overall_stats, warnings


def _apply_points_to_line_towers(
    db: Session,
    *,
    line_id: str,
    elevation_source: ElevationDataset | ElevationFileRecord,
    mode: str,
    points: list[ElevationSamplePoint],
) -> dict[str, int]:
    towers = db.execute(
        select(LineTower)
        .where(LineTower.line_id == line_id)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
    ).scalars().all()

    updated_tower_count = 0
    skipped_tower_count = 0
    missing_geo_count = 0
    unmatched_count = 0
    point_sampler = _build_points_sampler(points)

    for index, tower in enumerate(towers):
        if tower.longitude is None or tower.latitude is None:
            missing_geo_count += 1
            continue

        skip_altitude_update = mode == "fill_null_only" and tower.altitude_m is not None
        skip_slope_update = mode == "fill_null_only" and tower.slope_1 is not None and tower.slope_2 is not None
        if skip_altitude_update and skip_slope_update:
            skipped_tower_count += 1
            continue

        match = _find_nearest_point(
            lon=float(tower.longitude),
            lat=float(tower.latitude),
            points=points,
        )
        if match is None:
            unmatched_count += 1
            continue

        altitude, distance_m = match
        if distance_m > NEAREST_MATCH_MAX_DISTANCE_M:
            unmatched_count += 1
            continue

        changed = False
        sampled_altitude = round(float(altitude), 3)
        if not skip_altitude_update:
            tower.altitude_m = sampled_altitude
            changed = True

        slope_pair = _compute_tower_slope_pair(
            towers=towers,
            tower_index=index,
            center_altitude=sampled_altitude,
            sample_altitude=point_sampler,
        )
        if slope_pair is not None and not skip_slope_update:
            tower.slope_1 = round(slope_pair[0], 3)
            tower.slope_2 = round(slope_pair[1], 3)
            changed = True

        raw_extra = dict(tower.raw_extra_json or {})
        raw_extra["elevation"] = {
            **_elevation_source_metadata(elevation_source),
            "sample_method": "nearest",
            "sample_distance_m": round(distance_m, 3),
            "sample_distance_source": "computed",
            "sampled_at": utcnow().isoformat(),
        }
        tower.raw_extra_json = raw_extra
        tower.update_date = utcnow()
        if changed:
            updated_tower_count += 1
        else:
            skipped_tower_count += 1

    db.commit()
    return {
        "updated_tower_count": updated_tower_count,
        "skipped_tower_count": skipped_tower_count,
        "missing_geo_count": missing_geo_count,
        "unmatched_count": unmatched_count,
    }


def _find_nearest_point(
    *,
    lon: float,
    lat: float,
    points: list[ElevationSamplePoint],
) -> tuple[float, float] | None:
    best_altitude: float | None = None
    best_distance: float | None = None

    for point in points:
        distance = _haversine_distance_m(
            lon_a=lon,
            lat_a=lat,
            lon_b=point.lon,
            lat_b=point.lat,
        )
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_altitude = point.altitude_m

    if best_altitude is None or best_distance is None:
        return None
    return best_altitude, best_distance


def _build_points_sampler(points: list[ElevationSamplePoint]):
    def sample(lon: float, lat: float) -> float | None:
        match = _find_nearest_point(lon=lon, lat=lat, points=points)
        if match is None:
            return None
        altitude, distance_m = match
        if distance_m > NEAREST_MATCH_MAX_DISTANCE_M:
            return None
        return float(altitude)

    return sample


def _build_raster_sampler(*, rasterio: Any, src: Any, src_crs: Any, band_nodata: Any):
    def sample(lon: float, lat: float) -> float | None:
        transformed_lon = lon
        transformed_lat = lat

        if src_crs and str(src_crs) not in {"EPSG:4326", "OGC:CRS84"}:
            try:
                xs, ys = rasterio.warp.transform(
                    "EPSG:4326",
                    src_crs,
                    [lon],
                    [lat],
                )
                transformed_lon = float(xs[0])
                transformed_lat = float(ys[0])
            except Exception:
                return None

        if not _is_point_within_bounds(
            x=transformed_lon,
            y=transformed_lat,
            left=float(src.bounds.left),
            right=float(src.bounds.right),
            bottom=float(src.bounds.bottom),
            top=float(src.bounds.top),
        ):
            return None

        try:
            sampled = next(src.sample([(transformed_lon, transformed_lat)], masked=True), None)
        except Exception:
            sampled = None

        if sampled is None or len(sampled) == 0:
            return None

        value = sampled[0]
        if _is_masked_value(value):
            return None
        if band_nodata is not None and _almost_equal(float(value), float(band_nodata)):
            return None
        altitude = float(value)
        if not _is_finite_number(altitude):
            return None
        return altitude

    return sample


def _compute_tower_slope_pair(
    *,
    towers: list[LineTower],
    tower_index: int,
    center_altitude: float,
    sample_altitude: Any,
) -> tuple[float, float] | None:
    import math

    if len(towers) < 2:
        return None

    tower = towers[tower_index]
    if tower.longitude is None or tower.latitude is None:
        return None

    neighbor = _resolve_direction_neighbor(towers=towers, tower_index=tower_index)
    if neighbor is None or neighbor.longitude is None or neighbor.latitude is None:
        return None

    dx_m = _longitude_distance_m(
        lon_from=float(tower.longitude),
        lon_to=float(neighbor.longitude),
        latitude=float(tower.latitude),
    )
    dy_m = (float(neighbor.latitude) - float(tower.latitude)) * 111_320.0
    vector_length = math.hypot(dx_m, dy_m)
    if vector_length < 1e-6:
        return None

    unit_x = dx_m / vector_length
    unit_y = dy_m / vector_length
    negative_samples: list[float] = []
    positive_samples: list[float] = []
    for offset_m in (-200.0, -150.0, -100.0, -50.0, 50.0, 100.0, 150.0, 200.0):
        sample_lon = _offset_longitude(
            lon=float(tower.longitude),
            latitude=float(tower.latitude),
            offset_m=offset_m * unit_x,
        )
        sample_lat = _offset_latitude(lat=float(tower.latitude), offset_m=offset_m * unit_y)
        altitude = sample_altitude(sample_lon, sample_lat)
        if altitude is None:
            return None
        if offset_m < 0:
            negative_samples.append(float(altitude))
        else:
            positive_samples.append(float(altitude))

    slope_1 = sum(math.degrees(math.atan((center_altitude - altitude) / 50.0)) for altitude in negative_samples) / 4.0
    slope_2 = sum(math.degrees(math.atan((center_altitude - altitude) / 50.0)) for altitude in positive_samples) / 4.0
    return slope_1, slope_2


def _resolve_direction_neighbor(*, towers: list[LineTower], tower_index: int) -> LineTower | None:
    if tower_index >= len(towers) - 1:
        return towers[tower_index - 1] if tower_index > 0 else None
    return towers[tower_index + 1]


def _longitude_distance_m(*, lon_from: float, lon_to: float, latitude: float) -> float:
    import math

    km_per_degree = max(111.32 * abs(math.cos(math.radians(latitude))), 1e-6)
    return (lon_to - lon_from) * km_per_degree * 1000.0


def _offset_longitude(*, lon: float, latitude: float, offset_m: float) -> float:
    import math

    km_per_degree = max(111.32 * abs(math.cos(math.radians(latitude))), 1e-6)
    return lon + offset_m / (km_per_degree * 1000.0)


def _offset_latitude(*, lat: float, offset_m: float) -> float:
    return lat + offset_m / 111_320.0


def _haversine_distance_m(
    *,
    lon_a: float,
    lat_a: float,
    lon_b: float,
    lat_b: float,
) -> float:
    import math

    r = 6371000.0
    lon1 = math.radians(lon_a)
    lat1 = math.radians(lat_a)
    lon2 = math.radians(lon_b)
    lat2 = math.radians(lat_b)
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1

    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _detect_file_format(file_path: str) -> str:
    extension = Path(file_path).suffix.lower()
    file_format = ELEVATION_FILE_EXT_FORMAT_MAP.get(extension)
    if not file_format:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的高程文件类型: {extension or 'unknown'}，仅支持 .csv/.img/.tif/.tiff",
        )
    return file_format


def _resolve_dataset_file_format(dataset: ElevationDataset) -> str:
    declared = (dataset.file_format or "").strip().lower()
    detected = _detect_file_format(dataset.file_path)
    if declared and declared in ELEVATION_FILE_EXT_FORMAT_MAP.values():
        if declared == detected:
            return declared
        if declared in {"img", "tif", "tiff"} and detected in RASTER_FILE_FORMATS:
            return detected
    return detected


def _resolve_file_record_format(record: ElevationFileRecord) -> str:
    declared = (record.file_format or "").strip().lower()
    detected = _detect_file_format(record.file_path)
    if declared and declared in ELEVATION_FILE_EXT_FORMAT_MAP.values():
        if declared == detected:
            return declared
        if declared in RASTER_FILE_FORMATS and detected in RASTER_FILE_FORMATS:
            return detected
    return detected


def _resolve_elevation_file_format(elevation_source: ElevationDataset | ElevationFileRecord) -> str:
    if isinstance(elevation_source, ElevationFileRecord):
        return _resolve_file_record_format(elevation_source)
    return _resolve_dataset_file_format(elevation_source)


def _elevation_source_metadata(elevation_source: Any) -> dict[str, str | None]:
    if isinstance(elevation_source, ElevationFileRecord) or hasattr(elevation_source, "file_name"):
        return {
            "dataset_id": None,
            "dataset_code": None,
            "file_record_id": getattr(elevation_source, "id", None),
            "file_record_name": getattr(elevation_source, "file_name", None),
        }
    return {
        "dataset_id": getattr(elevation_source, "id", None),
        "dataset_code": getattr(elevation_source, "code", None),
        "file_record_id": None,
        "file_record_name": None,
    }


def _require_rasterio_available() -> Any:
    try:
        import rasterio
        import rasterio.warp as rasterio_warp

        if not hasattr(rasterio, "warp"):
            setattr(rasterio, "warp", rasterio_warp)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前服务未启用 rasterio 栅格能力，请联系管理员重建 API 镜像后重试 IMG/TIF 分析与回填",
        ) from exc
    return rasterio


def _open_raster_dataset(
    db: Session,
    dataset: ElevationDataset | ElevationFileRecord,
) -> _OpenedRasterDataset:
    file_format = _resolve_elevation_file_format(dataset)
    if file_format not in RASTER_FILE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前文件不是栅格高程文件: {dataset.file_path}",
        )

    rasterio = _require_rasterio_available()

    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    try:
        read_result = driver.read_file(dataset.file_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"高程数据文件不存在: {dataset.file_path}") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    suffix = Path(dataset.file_path).suffix.lower() or ".img"
    temp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(read_result.content)
            temp_path = tmp.name
        opened = rasterio.open(temp_path)
        return _OpenedRasterDataset(
            rasterio=rasterio,
            dataset=opened,
            temp_path=temp_path,
        )
    except Exception as exc:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"高程栅格文件解析失败: {dataset.file_path}",
        ) from exc


def _append_non_wgs84_bounds_warning(*, rasterio: Any, src: Any) -> str | None:
    src_crs = src.crs
    if src_crs is None:
        return "栅格缺少 CRS 定义，默认按 WGS84 经度/纬度采样"
    try:
        src_crs_obj = rasterio.crs.CRS.from_user_input(src_crs)
    except Exception:
        return "栅格 CRS 无法识别，默认按 WGS84 经度/纬度采样，建议先校验源数据"
    if src_crs_obj.to_string() in {"EPSG:4326", "OGC:CRS84"}:
        return None
    if bool(getattr(src_crs_obj, "is_geographic", False)):
        return None
    return (
        f"栅格 CRS 为 {src_crs_obj.to_string()}，数据集边界框基于该投影坐标，"
        "预览渲染会自动转换到 WGS84 经度/纬度"
    )


def _is_masked_value(value: Any) -> bool:
    try:
        import numpy as np
    except ImportError:
        return False
    return bool(np.ma.is_masked(value))


def _almost_equal(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6


def _is_finite_number(value: float) -> bool:
    import math

    return math.isfinite(value)


def _is_point_within_bounds(*, x: float, y: float, left: float, right: float, bottom: float, top: float) -> bool:
    return left <= x <= right and bottom <= y <= top


def _pick_float(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = row.get(key)
        number = _parse_float(value)
        if number is not None:
            return number
    return None


def _decode_csv_bytes(content: bytes) -> str:
    for encoding in CSV_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV 编码不受支持")


def _compute_raster_stats(
    db: Session,
    dataset: ElevationDataset,
) -> tuple[dict[str, float | int], list[str]]:
    warnings: list[str] = []
    with _open_raster_dataset(db, dataset) as opened:
        rasterio = opened.rasterio
        src = opened.dataset
        bounds = src.bounds
        warning_text = _append_non_wgs84_bounds_warning(rasterio=rasterio, src=src)
        if warning_text:
            warnings.append(warning_text)

        width = int(src.width or 0)
        height = int(src.height or 0)
        sample_count = width * height
        if sample_count > MAX_SAMPLE_COUNT_INT:
            sample_count = MAX_SAMPLE_COUNT_INT

        return (
            {
                "sample_count": sample_count,
                "bbox_min_lon": float(bounds.left),
                "bbox_max_lon": float(bounds.right),
                "bbox_min_lat": float(bounds.bottom),
                "bbox_max_lat": float(bounds.top),
            },
            warnings,
        )


def _compute_raster_wgs84_bounds(*, rasterio: Any, src: Any) -> dict[str, float]:
    source_bounds = src.bounds
    if src.crs is None or str(src.crs) in {"EPSG:4326", "OGC:CRS84"}:
        return _clamp_bounds_to_wgs84(
            {
                "west": float(source_bounds.left),
                "south": float(source_bounds.bottom),
                "east": float(source_bounds.right),
                "north": float(source_bounds.top),
            }
        )

    xs, ys = rasterio.warp.transform(
        src.crs,
        "EPSG:4326",
        [float(source_bounds.left), float(source_bounds.right), float(source_bounds.left), float(source_bounds.right)],
        [float(source_bounds.bottom), float(source_bounds.bottom), float(source_bounds.top), float(source_bounds.top)],
    )
    return _clamp_bounds_to_wgs84(
        {
            "west": float(min(xs)),
            "south": float(min(ys)),
            "east": float(max(xs)),
            "north": float(max(ys)),
        }
    )


def _clamp_bounds_to_wgs84(bounds: dict[str, float]) -> dict[str, float]:
    west = max(-180.0, min(180.0, float(bounds["west"])))
    east = max(-180.0, min(180.0, float(bounds["east"])))
    south = max(-90.0, min(90.0, float(bounds["south"])))
    north = max(-90.0, min(90.0, float(bounds["north"])))
    if east <= west:
        east = min(180.0, west + 1e-6)
    if north <= south:
        north = min(90.0, south + 1e-6)
    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
    }


def _resolve_terrain_zoom_limits(*, bounds: dict[str, float], resolution_m: float | None,
                                  raster_width: int | None = None, raster_height: int | None = None) -> tuple[int, int]:
    min_zoom = TERRAIN_DEFAULT_MIN_ZOOM
    if resolution_m is None or resolution_m <= 0:
        base_max_zoom = TERRAIN_DEFAULT_MAX_ZOOM
    else:
        meters_per_sample = max(float(resolution_m), 1.0)
        numerator = 180.0 * 111_320.0
        denominator = max((TERRAIN_TILE_SIZE - 1) * meters_per_sample, 1.0)
        base_max_zoom = int(math.floor(math.log2(max(numerator / denominator, 1.0))))
        base_max_zoom = max(TERRAIN_DEFAULT_MIN_ZOOM, min(TERRAIN_MAX_ALLOWED_ZOOM, base_max_zoom))

    max_zoom = max(min_zoom, base_max_zoom)

    if raster_width is not None and raster_height is not None:
        # 按像素维度计算 gdal2tiles --profile=raster 的实际瓦片数
        # 在 zoom z 生成 2^z × 2^z 瓦片，合计 = (4^(z+1)-1)/3
        while max_zoom > min_zoom:
            tile_count = (pow(4, max_zoom + 1) - 1) // 3
            if tile_count <= TERRAIN_TILE_COUNT_LIMIT:
                break
            max_zoom -= 1
    else:
        # 回退到地理范围计算（兼容旧逻辑）
        while max_zoom > min_zoom:
            availability = _build_terrain_available_ranges(bounds=bounds, max_zoom=max_zoom)
            tile_count = sum(
                (tile_range["endX"] - tile_range["startX"] + 1) * (tile_range["endY"] - tile_range["startY"] + 1)
                for ranges in availability.values() for tile_range in ranges
            )
            if tile_count <= TERRAIN_TILE_COUNT_LIMIT:
                break
            max_zoom -= 1

    return min_zoom, max_zoom


def _tile_counts(level: int) -> tuple[int, int]:
    return 1 << (level + 1), 1 << level


def _tile_span_degrees(level: int) -> float:
    return 180.0 / float(1 << level)


def _build_terrain_available_ranges(*, bounds: dict[str, float], max_zoom: int) -> dict[int, list[dict[str, int]]]:
    """根据地理范围计算瓦片 availability（基于全局地理网格）"""
    ranges: dict[int, list[dict[str, int]]] = {}
    epsilon = 1e-9
    for level in range(0, max_zoom + 1):
        x_count, y_count = _tile_counts(level)
        span = _tile_span_degrees(level)
        start_x = int(math.floor((bounds["west"] + 180.0) / span))
        end_x = int(math.floor((bounds["east"] + 180.0 - epsilon) / span))
        start_y = int(math.floor((bounds["south"] + 90.0) / span))
        end_y = int(math.floor((bounds["north"] + 90.0 - epsilon) / span))
        start_x = max(0, min(x_count - 1, start_x))
        end_x = max(0, min(x_count - 1, end_x))
        start_y = max(0, min(y_count - 1, start_y))
        end_y = max(0, min(y_count - 1, end_y))
        if end_x < start_x or end_y < start_y:
            continue
        ranges[level] = [{
            "startX": start_x,
            "endX": end_x,
            "startY": start_y,
            "endY": end_y,
        }]
    return ranges


def _compute_availability_from_tiles(*, temp_path: "Path", min_zoom: int, max_zoom: int) -> dict[int, list[dict[str, int]]]:
    """从 gdal2tiles 实际生成的瓦片目录结构扫描 availability

    不依赖地理范围推算，而是直接读取目录中的瓦片坐标，
    统计每 level 的 x/y 范围，确保 layer.json 只宣称实际存在的瓦片可用。
    """
    from pathlib import Path as _P
    ranges: dict[int, list[dict[str, int]]] = {}
    for level in range(min_zoom, max_zoom + 1):
        level_dir = _P(temp_path) / str(level)
        if not level_dir.is_dir():
            continue
        min_x, max_x = None, None
        min_y, max_y = None, None
        has_tiles = False
        for x_dir in sorted(level_dir.iterdir(), key=lambda p: p.name):
            if not x_dir.is_dir():
                continue
            try:
                tile_x = int(x_dir.name)
            except ValueError:
                continue
            tile_files = list(x_dir.glob("*.png")) + list(x_dir.glob("*.terrain"))
            for tile_file in tile_files:
                try:
                    tile_y = int(tile_file.stem)
                except ValueError:
                    continue
                has_tiles = True
                if min_x is None or tile_x < min_x:
                    min_x = tile_x
                if max_x is None or tile_x > max_x:
                    max_x = tile_x
                if min_y is None or tile_y < min_y:
                    min_y = tile_y
                if max_y is None or tile_y > max_y:
                    max_y = tile_y
        if has_tiles and min_x is not None and max_x is not None:
            ranges[level] = [{
                "startX": min_x,
                "endX": max_x,
                "startY": min_y,
                "endY": max_y,
            }]
    return ranges


def _tile_bounds_from_tms(level: int, x: int, y: int) -> dict[str, float]:
    span = _tile_span_degrees(level)
    west = -180.0 + x * span
    east = west + span
    south = -90.0 + y * span
    north = south + span
    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
    }


def _tile_intersects_bounds(tile_bounds: dict[str, float], bounds: dict[str, float]) -> bool:
    return not (
        tile_bounds["east"] <= bounds["west"]
        or tile_bounds["west"] >= bounds["east"]
        or tile_bounds["north"] <= bounds["south"]
        or tile_bounds["south"] >= bounds["north"]
    )


def _range_contains_tile(tile_range: dict[str, int], *, x: int, y: int) -> bool:
    return tile_range["startX"] <= x <= tile_range["endX"] and tile_range["startY"] <= y <= tile_range["endY"]


def _build_terrain_child_mask(*, availability: dict[int, list[dict[str, int]]], level: int, x: int, y: int, max_zoom: int) -> int:
    if level >= max_zoom:
        return 0

    next_ranges = availability.get(level + 1, [])
    if not next_ranges:
        return 0

    mask = 0
    children = (
        (TERRAIN_CHILD_MASK_SW, 2 * x, 2 * y),
        (TERRAIN_CHILD_MASK_SE, 2 * x + 1, 2 * y),
        (TERRAIN_CHILD_MASK_NW, 2 * x, 2 * y + 1),
        (TERRAIN_CHILD_MASK_NE, 2 * x + 1, 2 * y + 1),
    )
    for bit, child_x, child_y in children:
        if any(_range_contains_tile(tile_range, x=child_x, y=child_y) for tile_range in next_ranges):
            mask |= bit
    return mask


def _ensure_virtual_directory(driver: Any, path: str) -> None:
    try:
        driver.ensure_directory(path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _delete_virtual_directory_if_exists(driver: Any, path: str) -> None:
    try:
        driver.delete_path(path, is_dir=True, recursive=True)
    except StoragePathNotFoundError:
        return
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _write_virtual_file(driver: Any, *, path: str, content: bytes, content_type: str | None) -> None:
    parent_path = str(Path(path).parent).replace("\\", "/")
    if not parent_path.startswith("/"):
        parent_path = f"/{parent_path}"
    _ensure_virtual_directory(driver, parent_path)
    try:
        driver.write_file(path, content=content, content_type=content_type)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _ensure_8bit_raster(src_path: str, src_dtype: str) -> str:
    """
    如果栅格数据不是8-bit Byte，用gdal_translate转换为8-bit并返回临时文件路径。
    如果已经是8-bit，直接返回原路径。
    """
    if src_dtype in ("uint8",):
        return src_path

    import subprocess
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(delete=False, suffix=".tif") as tmp:
        scaled_path = tmp.name

    cmd = [
        "gdal_translate",
        "-of", "GTiff",
        "-ot", "Byte",
        "-scale",
        src_path,
        scaled_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        Path(scaled_path).unlink(missing_ok=True)
        raise RuntimeError(f"gdal_translate 8-bit conversion failed: {result.stderr}")
    return scaled_path


def _build_dataset_terrain_tiles(db: Session, dataset: ElevationDataset) -> _TerrainBuildArtifacts:
    """
    使用gdal2tiles生成数据集地形瓦片（Cesium heightmap-1.0格式）
    """
    import tempfile
    import subprocess
    from pathlib import Path as PathLib

    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    terrain_dir = _resolve_dataset_terrain_dir(dataset.code)

    _delete_virtual_directory_if_exists(driver, terrain_dir)
    _ensure_virtual_directory(driver, terrain_dir)

    with _open_raster_dataset(db, dataset) as opened:
        src = opened.dataset
        bounds = _compute_raster_wgs84_bounds(rasterio=opened.rasterio, src=src)
        min_zoom, max_zoom = _resolve_terrain_zoom_limits(
            bounds=bounds, resolution_m=dataset.resolution_m,
            raster_width=src.width, raster_height=src.height,
        )

        # 如果栅格不是8-bit，转成8-bit（gdal2tiles只支持8-bit Byte输入）
        input_path = opened.temp_path
        scaled_path = None
        try:
            input_path = _ensure_8bit_raster(opened.temp_path, str(src.dtypes[0]))
            if input_path != opened.temp_path:
                scaled_path = input_path

            # 使用临时目录运行gdal2tiles
            with tempfile.TemporaryDirectory() as temp_output_dir:
                # 调用gdal2tiles命令行工具生成Cesium terrain瓦片
                cmd = [
                    "gdal2tiles.py",
                    "--profile=raster",  # 使用栅格配置
                    f"--zoom={min_zoom}-{max_zoom}",
                    "--resampling=average",
                    "--tilesize=65",  # Cesium terrain标准尺寸
                    "--processes=4",
                    "--xyz",  # XYZ瓦片方案
                    input_path,  # 输入文件（已转为8-bit）
                    temp_output_dir,  # 输出目录
                ]

                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3600)
                if result.returncode != 0:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"gdal2tiles failed: {result.stdout}",
                    )

                # 将生成的瓦片上传到存储驱动
                tile_count = 0
                temp_path = PathLib(temp_output_dir)

                for level in range(min_zoom, max_zoom + 1):
                    level_dir = temp_path / str(level)
                    if not level_dir.exists():
                        continue

                    for x_dir in level_dir.iterdir():
                        if not x_dir.is_dir():
                            continue
                        tile_x = int(x_dir.name)

                        for tile_file in x_dir.glob("*.png"):
                            tile_y = int(tile_file.stem)

                            # 将PNG转换为Cesium heightmap-1.0格式
                            tile_bytes = _convert_png_to_heightmap(tile_file)

                            tile_path = _resolve_dataset_terrain_tile_path(
                                dataset_code=dataset.code, z=level, x=tile_x, y=tile_y
                            )
                            _write_virtual_file(
                                driver, path=tile_path, content=tile_bytes, content_type=TERRAIN_CONTENT_TYPE
                            )
                            tile_count += 1

                # 生成layer.json — 从实际生成的瓦片扫描 availability
                availability = _compute_availability_from_tiles(temp_path=temp_path, min_zoom=min_zoom, max_zoom=max_zoom)
                layer_payload = ElevationTerrainLayerResponse(
                    tiles=[f"{{z}}/{{x}}/{{y}}.terrain?v={TERRAIN_TILE_VERSION}"],
                    minzoom=0,
                    maxzoom=max_zoom,
                    attribution=f"{dataset.code} {dataset.name}",
                    bounds=[bounds["west"], bounds["south"], bounds["east"], bounds["north"]],
                    available=[availability.get(level, []) for level in range(0, max_zoom + 1)],
                ).model_dump(mode="json")
                _write_virtual_file(
                    driver,
                    path=_resolve_dataset_terrain_layer_path(dataset.code),
                    content=json.dumps(layer_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
                    content_type="application/json",
                )

                metadata = {
                    "tool": TERRAIN_BUILD_TOOL,
                    "format": TERRAIN_TILE_FORMAT,
                    "projection": TERRAIN_TILE_PROJECTION,
                    "tile_size": TERRAIN_TILE_SIZE,
                    "generated_at": utcnow().isoformat(),
                    "source_crs": str(src.crs) if src.crs is not None else None,
                    "source_nodata": src.nodatavals[0] if src.nodatavals else None,
                    "resolution_m": dataset.resolution_m,
                    "tile_count": tile_count,
                    "layer_url": f"/api/v1/elevation/datasets/{dataset.id}/terrain/layer.json",
                    "terrain_url_template": _build_dataset_terrain_url_template(dataset.id),
                }
                return _TerrainBuildArtifacts(
                    min_zoom=min_zoom,
                    max_zoom=max_zoom,
                    bounds=bounds,
                    metadata=metadata,
                )
        finally:
            if scaled_path:
                try:
                    Path(scaled_path).unlink(missing_ok=True)
                except Exception:
                    pass


def _build_file_record_terrain_tiles(db: Session, record: ElevationFileRecord) -> _TerrainBuildArtifacts:
    """
    使用gdal2tiles生成文件记录地形瓦片（Cesium heightmap-1.0格式）
    """
    import tempfile
    import subprocess
    from pathlib import Path as PathLib

    mount = _require_mount(db, record.mount_code)
    driver = _build_driver_or_400(mount)
    terrain_dir = _resolve_file_record_terrain_dir(record.id)

    _delete_virtual_directory_if_exists(driver, terrain_dir)
    _ensure_virtual_directory(driver, terrain_dir)

    with _open_raster_dataset(db, record) as opened:
        src = opened.dataset
        bounds = _compute_raster_wgs84_bounds(rasterio=opened.rasterio, src=src)
        min_zoom, max_zoom = _resolve_terrain_zoom_limits(
            bounds=bounds, resolution_m=record.resolution_m,
            raster_width=src.width, raster_height=src.height,
        )

        # 如果栅格不是8-bit，转成8-bit（gdal2tiles只支持8-bit Byte输入）
        input_path = opened.temp_path
        scaled_path = None
        try:
            input_path = _ensure_8bit_raster(opened.temp_path, str(src.dtypes[0]))
            if input_path != opened.temp_path:
                scaled_path = input_path

            # 使用临时目录运行gdal2tiles
            with tempfile.TemporaryDirectory() as temp_output_dir:
                # 调用gdal2tiles命令行工具生成Cesium terrain瓦片
                cmd = [
                    "gdal2tiles.py",
                    "--profile=raster",  # 使用栅格配置
                    f"--zoom={min_zoom}-{max_zoom}",
                    "--resampling=average",
                    "--tilesize=65",  # Cesium terrain标准尺寸
                    "--processes=4",
                    "--xyz",  # XYZ瓦片方案
                    input_path,  # 输入文件（已转为8-bit）
                    temp_output_dir,  # 输出目录
                ]

                # 使用临时文件替代 pipe，避免 gdal2tiles 多进程模式下
                # 子进程继承 pipe FD 导致父进程 communicate() 永不到达 EOF
                import tempfile as _tmpfile_module
                with _tmpfile_module.NamedTemporaryFile(delete=False, suffix=".out") as _out_f:
                    _gdal2tiles_out_path = _out_f.name
                try:
                    with open(_gdal2tiles_out_path, "wb") as _out_file:
                        result = subprocess.run(
                            cmd, stdout=_out_file, stderr=subprocess.STDOUT,
                            text=False, timeout=3600,
                        )
                    with open(_gdal2tiles_out_path, "r", errors="replace") as _out_file:
                        _gdal2tiles_output = _out_file.read()
                finally:
                    try:
                        Path(_gdal2tiles_out_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                if result.returncode != 0:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"gdal2tiles failed: {_gdal2tiles_output[:2000]}",
                    )

                # 将生成的PNG瓦片转换为.terrain格式并批量打包上传到staging
                tile_count = 0
                temp_path = PathLib(temp_output_dir)

                # 第一阶段：转换PNG为terrain文件到临时目录
                with tempfile.TemporaryDirectory() as convert_dir:
                    convert_path = PathLib(convert_dir)
                    for level in range(min_zoom, max_zoom + 1):
                        level_dir = temp_path / str(level)
                        if not level_dir.exists():
                            continue
                        for x_dir in level_dir.iterdir():
                            if not x_dir.is_dir():
                                continue
                            tile_x = x_dir.name
                            for tile_file in x_dir.glob("*.png"):
                                tile_y = tile_file.stem
                                tile_bytes = _convert_png_to_heightmap(tile_file)
                                # 保持 z/x/y.terrain 目录结构
                                dst_dir = convert_path / str(level) / tile_x
                                dst_dir.mkdir(parents=True, exist_ok=True)
                                (dst_dir / f"{tile_y}.terrain").write_bytes(tile_bytes)
                                tile_count += 1

                    # 第二阶段：打包为 tar.gz
                    archives = _batch_terrain_files_into_archives(
                        terrain_dir=convert_dir,
                        min_zoom=min_zoom,
                        max_zoom=max_zoom,
                    )

                    # 第三阶段：将 tar.gz 上传到 MinIO staging
                    staging_dir = _get_terrain_staging_dir(record.id)
                    _delete_virtual_directory_if_exists(driver, staging_dir)
                    _ensure_virtual_directory(driver, staging_dir)

                    for archive_path in archives:
                        archive_name = str(PathLib(archive_path).name)
                        remote_path = join_virtual_path(staging_dir, archive_name)
                        with open(archive_path, "rb") as f:
                            archive_bytes = f.read()
                        _write_virtual_file(
                            driver, path=remote_path,
                            content=archive_bytes, content_type="application/gzip",
                        )

                # 第四阶段：生成 layer.json — 从实际生成的瓦片扫描 availability
                layer_url = f"/api/v1/elevation/records/{record.id}/terrain/layer.json"
                terrain_url_template = _build_file_record_terrain_url_template(record.id)
                availability = _compute_availability_from_tiles(temp_path=temp_path, min_zoom=min_zoom, max_zoom=max_zoom)

                layer_payload = ElevationTerrainLayerResponse(
                    tiles=[f"{{z}}/{{x}}/{{y}}.terrain?v={TERRAIN_TILE_VERSION}"],
                    minzoom=0,
                    maxzoom=max_zoom,
                    attribution=record.file_name,
                    bounds=[bounds["west"], bounds["south"], bounds["east"], bounds["north"]],
                    available=[availability.get(level, []) for level in range(0, max_zoom + 1)],
                ).model_dump(mode="json")
                _write_virtual_file(
                    driver,
                    path=_get_terrain_staging_layer_path(record.id),
                    content=json.dumps(layer_payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
                    content_type="application/json",
                )

                # 暂停当前任务, 清理 DB 连接使其可用
                metadata = {
                    "tool": TERRAIN_BUILD_TOOL,
                    "format": TERRAIN_TILE_FORMAT,
                    "projection": TERRAIN_TILE_PROJECTION,
                    "tile_size": TERRAIN_TILE_SIZE,
                    "generated_at": utcnow().isoformat(),
                    "source_crs": str(src.crs) if src.crs is not None else None,
                    "source_nodata": src.nodatavals[0] if src.nodatavals else None,
                    "resolution_m": record.resolution_m,
                    "tile_count": tile_count,
                    "layer_url": layer_url,
                    "terrain_url_template": terrain_url_template,
                }

                # 更新 DB 状态为 staging_done 并提交
                record.terrain_status = "staging_done"
                record.terrain_min_zoom = min_zoom
                record.terrain_max_zoom = max_zoom
                record.terrain_metadata = metadata
                record.update_date = utcnow()
                db.commit()

                # 第五阶段：调用 84 API 触发解包
                _trigger_terrain_unpack_via_api(
                    record_id=record.id,
                    min_zoom=min_zoom,
                    max_zoom=max_zoom,
                    tile_count=tile_count,
                )

                return _TerrainBuildArtifacts(
                    min_zoom=min_zoom,
                    max_zoom=max_zoom,
                    bounds=bounds,
                    metadata=metadata,
                )
        finally:
            if scaled_path:
                try:
                    Path(scaled_path).unlink(missing_ok=True)
                except Exception:
                    pass


def _convert_png_to_heightmap(png_path: Path) -> bytes:
    """
    将gdal2tiles生成的PNG瓦片转换为Cesium heightmap-1.0格式

    Cesium heightmap-1.0格式:
    - 前8450字节: 65x65的16位小端无符号整数高程数据
    - 第8451字节: child mask (子瓦片可用性标记)
    - 第8452字节: water mask (水体掩码，全陆地为0x00)

    Args:
        png_path: gdal2tiles生成的PNG瓦片路径

    Returns:
        heightmap-1.0格式的二进制数据
    """
    import numpy as np
    from PIL import Image

    # 读取PNG图像
    img = Image.open(png_path)

    # 如果是RGBA，取第一个通道作为高程数据
    if img.mode == "RGBA":
        img = img.getchannel(0)
    elif img.mode != "L":
        img = img.convert("L")

    # 调整大小为65x65
    if img.size != (TERRAIN_TILE_SIZE, TERRAIN_TILE_SIZE):
        img = img.resize((TERRAIN_TILE_SIZE, TERRAIN_TILE_SIZE), Image.Resampling.BILINEAR)

    # 转换为numpy数组
    heights = np.array(img, dtype="float32")

    # 将0-255的灰度值映射到高程范围
    # 假设PNG灰度值已经编码了高程信息（gdal2tiles的输出）
    # 简化处理：假设灰度值已经是归一化的高程数据
    heights = (heights / 255.0) * 1000.0 - 500.0  # 映射到-500m到+500m范围

    # 编码为Cesium heightmap-1.0格式
    # heightmap格式: (height + 1000.0) * 5.0, 范围[0, 65535]
    encoded = np.rint((heights + 1000.0) * 5.0)
    encoded = np.clip(encoded, 0.0, float(256 * 256 - 1))
    encoded = encoded.astype("<u2")  # 16位小端无符号整数

    # 构建最终payload
    payload = bytearray(encoded.tobytes(order="C"))
    payload.extend(bytes([0]))  # child_mask: 暂时设为0（无子瓦片）
    payload.extend(TERRAIN_WATER_MASK_ALL_LAND)  # water mask: 全陆地
    return bytes(payload)


def _get_terrain_staging_dir(record_id: str) -> str:
    """获取瓦片暂存目录路径（在 terrain 目录下的 _staging 子目录）"""
    return join_virtual_path(_resolve_file_record_terrain_dir(record_id), TERRAIN_STAGING_DIRNAME)


def _get_terrain_staging_archive_path(record_id: str, batch_index: int) -> str:
    """获取单个 tar.gz 暂存包的远程路径"""
    return join_virtual_path(
        _get_terrain_staging_dir(record_id),
        f"{TERRAIN_ARCHIVE_PREFIX}_{batch_index:04d}.tar.gz",
    )


def _get_terrain_staging_layer_path(record_id: str) -> str:
    """获取 staging 中的 layer.json 路径"""
    return join_virtual_path(_get_terrain_staging_dir(record_id), "layer.json")


def _get_terrain_staging_metadata_path(record_id: str) -> str:
    """获取 staging 中的 metadata.json 路径"""
    return join_virtual_path(_get_terrain_staging_dir(record_id), "metadata.json")


def _batch_terrain_files_into_archives(
    *,
    terrain_dir: str,
    min_zoom: int,
    max_zoom: int,
    batch_size: int = TERRAIN_BATCH_SIZE,
) -> list[str]:
    """将地形瓦片文件批量打包为 tar.gz 文件

    Args:
        terrain_dir: 包含地形瓦片的本地临时目录 (z/x/y.terrain 结构)
        min_zoom: 最小 zoom level
        max_zoom: 最大 zoom level
        batch_size: 每个 tar.gz 包含的瓦片数

    Returns:
        生成的 tar.gz 文件路径列表
    """
    import tarfile

    terrain_path = Path(terrain_dir)
    archives: list[str] = []
    current_batch: list[tuple[str, bytes]] = []
    batch_index = 0

    def _flush_batch():
        nonlocal batch_index
        if not current_batch:
            return
        archive_path = str(terrain_path / f"{TERRAIN_ARCHIVE_PREFIX}_{batch_index:04d}.tar.gz")
        with tarfile.open(archive_path, "w:gz") as tar:
            for arcname, content in current_batch:
                info = tarfile.TarInfo(name=arcname)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        archives.append(archive_path)
        current_batch.clear()
        batch_index += 1

    for level in range(min_zoom, max_zoom + 1):
        level_dir = terrain_path / str(level)
        if not level_dir.exists():
            continue
        for x_dir in sorted(level_dir.iterdir(), key=lambda p: p.name):
            if not x_dir.is_dir():
                continue
            for tile_file in sorted(x_dir.glob("*.terrain")):
                arcname = f"{level}/{x_dir.name}/{tile_file.name}"
                content = tile_file.read_bytes()
                current_batch.append((arcname, content))
                if len(current_batch) >= batch_size:
                    _flush_batch()

    # 最后一批
    _flush_batch()
    return archives


def _trigger_terrain_unpack_via_api(
    *,
    record_id: str,
    min_zoom: int,
    max_zoom: int,
    tile_count: int,
) -> None:
    """通过 HTTP API 触发 84 端瓦片解包

    Worker 打包上传 staging 后调用此函数，通知 84 API 进行解包。
    """
    import os

    unpack_secret = os.environ.get("UNPACK_SECRET_KEY", "")
    if not unpack_secret:
        raise RuntimeError("UNPACK_SECRET_KEY 未设置，无法触发远程解包")

    api_base_url = os.environ.get("LP_API_BASE_URL", "https://www.quizck.cn")
    if not api_base_url:
        raise RuntimeError("LP_API_BASE_URL 未设置，无法触发远程解包")

    url = f"{api_base_url}{TERRAIN_UNPACK_ENDPOINT.format(record_id=record_id)}"

    import httpx

    try:
        resp = httpx.post(
            url,
            headers={
                "X-Unpack-Secret": unpack_secret,
                "Content-Type": "application/json",
            },
            json={
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "tile_count": tile_count,
            },
            timeout=600.0,  # 10 minutes max
        )
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"触发远程解包失败: {exc}") from exc


def execute_file_record_terrain_unpack_job(
    *,
    record_id: str,
    min_zoom: int,
    max_zoom: int,
    tile_count: int,
) -> None:
    """执行地形瓦片解包作业（在 84 端运行）

    从 staging 读取 tar.gz 包，解压后写入本地 Nginx 服务目录，生成 layer.json。
    （不再写入 MinIO，改为写入宿主挂载卷）
    """
    import os as _os

    from .elevation_file_record_service import get_file_record_by_id as _get_record

    db = SessionLocal()
    try:
        record = _get_record(db, record_id)
        if not record:
            raise RuntimeError(f"记录不存在: {record_id}")

        mount = _require_mount(db, record.mount_code)
        driver = _build_driver_or_400(mount)
        staging_dir = _get_terrain_staging_dir(record_id)

        # 本地瓦片根目录
        local_terrain_root = str(_os.path.join(LOCAL_TERRAIN_ROOT, record_id))
        _os.makedirs(local_terrain_root, exist_ok=True)

        # 1. 读取 layer.json（从 staging）
        layer_payload_bytes = _read_virtual_file(driver, _get_terrain_staging_layer_path(record_id))
        layer_payload = json.loads(layer_payload_bytes.decode("utf-8"))

        # 2. 列出 staging 中所有 tar.gz
        archive_prefix = join_virtual_path(staging_dir, TERRAIN_ARCHIVE_PREFIX)
        archive_objects = _list_virtual_files_with_prefix(driver, archive_prefix)

        if not archive_objects:
            raise RuntimeError(f"未找到 staging tar.gz 包: {staging_dir}")

        # 3. 解压每个 tar.gz 并写入本地目录
        import tarfile

        uploaded_tile_count = 0
        for archive_obj in archive_objects:
            archive_data = _read_virtual_file(driver, archive_obj["path"])
            try:
                with tarfile.open(fileobj=io.BytesIO(archive_data), mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if not member.isfile() or not member.name.endswith(".terrain"):
                            continue
                        content = tar.extractfile(member).read()
                        # arcname 格式: z/x/y.terrain
                        parts = member.name.split("/")
                        if len(parts) != 3:
                            continue
                        z_str, x_str, y_name = parts
                        y_str = y_name.replace(".terrain", "")
                        # 写入本地文件：{local_terrain_root}/{z}/{x}/{y}.terrain
                        tile_dir = _os.path.join(local_terrain_root, z_str, x_str)
                        _os.makedirs(tile_dir, exist_ok=True)
                        tile_path = _os.path.join(tile_dir, y_name)
                        with open(tile_path, "wb") as f:
                            f.write(content)
                        uploaded_tile_count += 1
            except Exception as exc:
                raise RuntimeError(f"解包 {archive_obj['path']} 失败: {exc}") from exc

        # 4. 写入 layer.json 到本地目录
        layer_local_path = _os.path.join(local_terrain_root, "layer.json")
        with open(layer_local_path, "w", encoding="utf-8") as f:
            json.dump(layer_payload, f, ensure_ascii=True, separators=(",", ":"))

        # 5. 清理 staging 目录（MinIO）
        _delete_virtual_directory_if_exists(driver, staging_dir)

        # 6. 更新 DB
        saved = _get_record(db, record_id)
        if saved is not None:
            saved.terrain_status = "ready"
            saved.terrain_error_message = None
            saved.terrain_root_path = local_terrain_root
            saved.terrain_url_template = _build_file_record_terrain_url_template(record_id)
            saved.terrain_min_zoom = min_zoom
            saved.terrain_max_zoom = max_zoom
            # layer.json 的 bounds 是 [west, south, east, north] 列表，转为 dict
            layer_bounds = layer_payload.get("bounds", [])
            if isinstance(layer_bounds, list) and len(layer_bounds) >= 4:
                terrain_bounds = {
                    "west": layer_bounds[0],
                    "south": layer_bounds[1],
                    "east": layer_bounds[2],
                    "north": layer_bounds[3],
                }
            else:
                terrain_bounds = None
            saved.terrain_bounds = terrain_bounds
            saved.terrain_metadata = {
                "tool": TERRAIN_BUILD_TOOL,
                "format": TERRAIN_TILE_FORMAT,
                "projection": TERRAIN_TILE_PROJECTION,
                "tile_size": TERRAIN_TILE_SIZE,
                "generated_at": utcnow().isoformat(),
                "tile_count": uploaded_tile_count,
            }
            saved.update_date = utcnow()
            db.commit()

        _publish_elevation_change(
            "elevation.file_record.terrain.ready",
            {"action": "file_record_terrain_ready", "file_record_id": record_id},
        )
    except Exception:
        # 解包失败时设置 staging_failed
        failed = _get_record(db, record_id)
        if failed is not None:
            failed.terrain_status = "staging_failed"
            failed.terrain_error_message = f"解包失败: {traceback.format_exc()}"
            failed.update_date = utcnow()
            db.commit()
        raise
    finally:
        db.close()


def _read_virtual_file(driver: Any, path: str) -> bytes:
    """读取存储驱动的文件内容"""
    result = driver.read_file(path)
    return result.content


def _list_virtual_files_with_prefix(driver: Any, prefix: str) -> list[Any]:
    """列出存储驱动中指定前缀的文件"""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise RuntimeError("需要 boto3 依赖")

    # 通过 S3 driver 内部 client 直接列举
    if hasattr(driver, "_client") and hasattr(driver, "_bucket"):
        client = driver._client
        bucket = driver._bucket
        key_prefix = driver._key_for_path(prefix) if hasattr(driver, "_key_for_path") else prefix
        items: list[Any] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []):
                key = str(obj.get("Key", ""))
                items.append({
                    "path": key,
                    "name": str(Path(key).name),
                    "size": int(obj.get("Size", 0)),
                })
        return items
    raise RuntimeError("驱动不支持文件列举")


def _build_raster_preview(
    db: Session,
    *,
    dataset: ElevationDataset,
    limit: int,
) -> ElevationDatasetPreviewResponse:
    warnings: list[str] = []
    with _open_raster_dataset(db, dataset) as opened:
        rasterio = opened.rasterio
        src = opened.dataset
        warning_text = _append_non_wgs84_bounds_warning(rasterio=rasterio, src=src)
        if warning_text:
            warnings.append(warning_text)

        width = int(src.width or 0)
        height = int(src.height or 0)
        source_bounds = src.bounds
        source_crs_text = str(src.crs) if src.crs is not None else None
        diagnostics = ElevationDatasetPreviewDiagnostics(
            source_crs=source_crs_text,
            source_bounds_min_x=float(source_bounds.left),
            source_bounds_max_x=float(source_bounds.right),
            source_bounds_min_y=float(source_bounds.bottom),
            source_bounds_max_y=float(source_bounds.top),
            raster_width=width,
            raster_height=height,
        )

        if source_crs_text in {"EPSG:4326", "OGC:CRS84"}:
            diagnostics.wgs84_bounds_min_lon = float(source_bounds.left)
            diagnostics.wgs84_bounds_max_lon = float(source_bounds.right)
            diagnostics.wgs84_bounds_min_lat = float(source_bounds.bottom)
            diagnostics.wgs84_bounds_max_lat = float(source_bounds.top)
        elif src.crs is not None:
            try:
                xs, ys = rasterio.warp.transform(
                    src.crs,
                    "EPSG:4326",
                    [float(source_bounds.left), float(source_bounds.right), float(source_bounds.left), float(source_bounds.right)],
                    [float(source_bounds.bottom), float(source_bounds.bottom), float(source_bounds.top), float(source_bounds.top)],
                )
                diagnostics.wgs84_bounds_min_lon = float(min(xs))
                diagnostics.wgs84_bounds_max_lon = float(max(xs))
                diagnostics.wgs84_bounds_min_lat = float(min(ys))
                diagnostics.wgs84_bounds_max_lat = float(max(ys))
            except Exception:
                warnings.append("无法计算栅格转换后的 WGS84 边界范围")

        if width <= 0 or height <= 0:
            return ElevationDatasetPreviewResponse(
                dataset=serialize_dataset(dataset),
                preview_mode="terrain_grid",
                total_points=0,
                sampled_points=0,
                points=[],
                cells=[],
                diagnostics=diagnostics,
                warnings=warnings,
            )

        band_nodata = src.nodatavals[0] if src.nodatavals else None
        total_points = width * height
        sampled_points: list[ElevationDatasetPreviewPoint] = []
        sampled_cells: list[ElevationDatasetPreviewCell] = []

        target_count = max(1, limit)
        step = max(1, int((width * height / target_count) ** 0.5))
        diagnostics.target_samples = target_count
        diagnostics.sampling_step = step
        y = 0
        while y < height and len(sampled_points) < target_count:
            x = 0
            while x < width and len(sampled_points) < target_count:
                diagnostics.scanned_candidates = (diagnostics.scanned_candidates or 0) + 1
                try:
                    value = src.read(1, window=((y, y + 1), (x, x + 1)), masked=True)[0][0]
                except Exception:
                    diagnostics.skip_read_error += 1
                    x += step
                    continue

                if _is_masked_value(value):
                    diagnostics.skip_masked += 1
                    x += step
                    continue
                altitude = float(value)
                if band_nodata is not None and _almost_equal(altitude, float(band_nodata)):
                    diagnostics.skip_nodata += 1
                    x += step
                    continue
                if not _is_finite_number(altitude):
                    diagnostics.skip_nonfinite += 1
                    x += step
                    continue

                world_x, world_y = rasterio.transform.xy(src.transform, y, x, offset="center")
                lon = float(world_x)
                lat = float(world_y)
                if src.crs and str(src.crs) not in {"EPSG:4326", "OGC:CRS84"}:
                    try:
                        xs, ys = rasterio.warp.transform(src.crs, "EPSG:4326", [lon], [lat])
                        lon = float(xs[0])
                        lat = float(ys[0])
                    except Exception as exc:
                        diagnostics.skip_sample_transform_error += 1
                        if diagnostics.sample_tx_first_error is None:
                            diagnostics.sample_tx_first_error = str(exc)
                        x += step
                        continue
                if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                    diagnostics.skip_sample_out_of_range += 1
                    x += step
                    continue

                col_end = min(width - 1, x + step)
                row_end = min(height - 1, y + step)
                try:
                    lon_min, lat_min = rasterio.transform.xy(src.transform, row_end, x, offset="ll")
                    lon_max, lat_max = rasterio.transform.xy(src.transform, y, col_end, offset="ur")
                except Exception:
                    x += step
                    continue
                min_lon = float(min(lon_min, lon_max))
                max_lon = float(max(lon_min, lon_max))
                min_lat = float(min(lat_min, lat_max))
                max_lat = float(max(lat_min, lat_max))
                if src.crs and str(src.crs) not in {"EPSG:4326", "OGC:CRS84"}:
                    try:
                        xs, ys = rasterio.warp.transform(
                            src.crs,
                            "EPSG:4326",
                            [min_lon, max_lon, min_lon, max_lon],
                            [min_lat, min_lat, max_lat, max_lat],
                        )
                    except Exception:
                        diagnostics.skip_cell_transform_error += 1
                        x += step
                        continue
                    min_lon = float(min(xs))
                    max_lon = float(max(xs))
                    min_lat = float(min(ys))
                    max_lat = float(max(ys))
                if min_lon < -180 or max_lon > 180 or min_lat < -90 or max_lat > 90:
                    diagnostics.skip_cell_out_of_range += 1
                    x += step
                    continue
                sampled_cells.append(
                    ElevationDatasetPreviewCell(
                        min_longitude=round(min_lon, 6),
                        max_longitude=round(max_lon, 6),
                        min_latitude=round(min_lat, 6),
                        max_latitude=round(max_lat, 6),
                        altitude_m=round(altitude, 3),
                    )
                )
                sampled_points.append(
                    ElevationDatasetPreviewPoint(
                        longitude=round(lon, 6),
                        latitude=round(lat, 6),
                        altitude_m=round(altitude, 3),
                    )
                )
                x += step
            y += step

        diagnostics.valid_preview_count = len(sampled_cells)
        if not sampled_cells:
            warnings.append("未提取到有效地形网格（可能为 nodata 或投影定义不匹配）")

        return ElevationDatasetPreviewResponse(
            dataset=serialize_dataset(dataset),
            preview_mode="terrain_grid",
            total_points=total_points,
            sampled_points=len(sampled_cells),
            points=sampled_points,
            cells=sampled_cells,
            diagnostics=diagnostics,
            warnings=warnings,
        )


def _apply_raster_to_line_towers(
    db: Session,
    *,
    line_id: str,
    elevation_source: ElevationDataset | ElevationFileRecord,
    mode: str,
) -> tuple[dict[str, int], list[str]]:
    towers = db.execute(
        select(LineTower)
        .where(LineTower.line_id == line_id)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
    ).scalars().all()

    updated_tower_count = 0
    skipped_tower_count = 0
    missing_geo_count = 0
    unmatched_count = 0
    warnings: list[str] = []

    with _open_raster_dataset(db, elevation_source) as opened:
        rasterio = opened.rasterio
        src = opened.dataset
        warning_text = _append_non_wgs84_bounds_warning(rasterio=rasterio, src=src)
        if warning_text:
            warnings.append(warning_text)
        src_crs = src.crs
        band_nodata = src.nodatavals[0] if src.nodatavals else None
        raster_sampler = _build_raster_sampler(rasterio=rasterio, src=src, src_crs=src_crs, band_nodata=band_nodata)

        for index, tower in enumerate(towers):
            if tower.longitude is None or tower.latitude is None:
                missing_geo_count += 1
                continue

            skip_altitude_update = mode == "fill_null_only" and tower.altitude_m is not None
            skip_slope_update = mode == "fill_null_only" and tower.slope_1 is not None and tower.slope_2 is not None
            if skip_altitude_update and skip_slope_update:
                skipped_tower_count += 1
                continue

            lon = float(tower.longitude)
            lat = float(tower.latitude)
            altitude = raster_sampler(lon, lat)
            if altitude is None:
                unmatched_count += 1
                continue

            changed = False
            sampled_altitude = round(float(altitude), 3)
            if not skip_altitude_update:
                tower.altitude_m = sampled_altitude
                changed = True

            slope_pair = _compute_tower_slope_pair(
                towers=towers,
                tower_index=index,
                center_altitude=sampled_altitude,
                sample_altitude=raster_sampler,
            )
            if slope_pair is not None and not skip_slope_update:
                tower.slope_1 = round(slope_pair[0], 3)
                tower.slope_2 = round(slope_pair[1], 3)
                changed = True

            raw_extra = dict(tower.raw_extra_json or {})
            raw_extra["elevation"] = {
                **_elevation_source_metadata(elevation_source),
                "sample_method": "raster_pixel",
                "sample_distance_m": 0.0,
                "sample_distance_source": "pixel_lookup",
                "sampled_at": utcnow().isoformat(),
            }
            tower.raw_extra_json = raw_extra
            tower.update_date = utcnow()
            if changed:
                updated_tower_count += 1
            else:
                skipped_tower_count += 1

    db.commit()
    return (
        {
            "updated_tower_count": updated_tower_count,
            "skipped_tower_count": skipped_tower_count,
            "missing_geo_count": missing_geo_count,
            "unmatched_count": unmatched_count,
        },
        warnings,
    )


def _normalize_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_float(value: Any) -> float | None:
    text = _normalize_str(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _decode_text_bytes_for_import(content: bytes) -> str:
    for encoding in CSV_IMPORT_TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV 编码不受支持")


def _pick_csv_value(row: dict[str, Any], keys: list[str]) -> str | None:
    normalized_keys = {str(key).strip(): key for key in row.keys()}
    for key in keys:
        actual_key = normalized_keys.get(key)
        if actual_key is None:
            continue
        value = _normalize_str(row.get(actual_key))
        if value is not None:
            return value
    return None


def _parse_csv_optional_positive_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"无效分辨率：{value}") from exc
    if number <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"分辨率必须大于 0：{value}")
    return number


def _publish_elevation_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            ELEVATION_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=[
                "/api/v1/elevation/records",
                "/api/v1/elevation/datasets",
                "/api/v1/elevation/jobs",
                "/api/v1/elevation/import-jobs",
            ],
            dedupe_key=(
                f"{event_name}:"
                f"{payload.get('import_job_id') or payload.get('job_id') or payload.get('file_record_id') or payload.get('dataset_id') or 'unknown'}"
            ),
        )
    )


def _publish_line_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            POWER_LINES_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lines"],
            dedupe_key=f"{event_name}:{payload.get('line_id', 'unknown')}",
        )
    )


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)


def _analyze_single_file(
    db: Session,
    dataset: ElevationDataset,
    file_path: str,
) -> tuple[dict[str, float | int], list[str]] | None:
    """Analyze a single elevation file and return its bbox stats."""
    mount = _require_mount(db, dataset.mount_code)
    driver = _build_driver_or_400(mount)
    
    file_ext = Path(file_path).suffix.lower()
    if file_ext not in ELEVATION_FILE_EXT_FORMAT_MAP:
        return None
    
    file_format = ELEVATION_FILE_EXT_FORMAT_MAP[file_ext]
    
    try:
        if file_format == "csv":
            read_result = driver.read_file(file_path)
            text = _decode_csv_bytes(read_result.content)
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                return None
            
            points: list[ElevationSamplePoint] = []
            for row in rows:
                lon = _pick_float(row, ["longitude", "lon", "lng", "经度"])
                lat = _pick_float(row, ["latitude", "lat", "纬度"])
                altitude = _pick_float(row, ["altitude_m", "altitude", "elevation", "dem", "海拔m", "高程"])
                if lon is None or lat is None or altitude is None:
                    continue
                if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                    continue
                points.append(ElevationSamplePoint(lon=lon, lat=lat, altitude_m=altitude))
            
            if not points:
                return None
            
            lon_values = [p.lon for p in points]
            lat_values = [p.lat for p in points]
            return {
                "sample_count": len(points),
                "bbox_min_lon": min(lon_values),
                "bbox_max_lon": max(lon_values),
                "bbox_min_lat": min(lat_values),
                "bbox_max_lat": max(lat_values),
            }, []
        
        elif file_format in RASTER_FILE_FORMATS:
            # For raster files, open and extract bounds
            try:
                import rasterio
            except ImportError:
                return None
            
            read_result = driver.read_file(file_path)
            with NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                tmp_file.write(read_result.content)
                tmp_path = tmp_file.name
            
            try:
                with rasterio.open(tmp_path) as src:
                    bounds = src.bounds
                    wgs84_bounds = _compute_raster_wgs84_bounds(rasterio=rasterio, src=src)
                    width = int(src.width or 0)
                    height = int(src.height or 0)
                    sample_count = width * height
                    if sample_count > MAX_SAMPLE_COUNT_INT:
                        sample_count = MAX_SAMPLE_COUNT_INT
                    
                    return {
                        "sample_count": sample_count,
                        "bbox_min_lon": float(wgs84_bounds["west"]),
                        "bbox_max_lon": float(wgs84_bounds["east"]),
                        "bbox_min_lat": float(wgs84_bounds["south"]),
                        "bbox_max_lat": float(wgs84_bounds["north"]),
                    }, []
            finally:
                import os
                os.unlink(tmp_path)
        
        return None
    except Exception:
        return None


def _store_file_metadata(
    db: Session,
    dataset_id: str,
    file_path: str,
    file_name: str,
    stats: dict[str, float | int],
) -> None:
    """Store or update file metadata in database."""
    stmt = select(ElevationDatasetFileMeta).where(
        ElevationDatasetFileMeta.dataset_id == dataset_id,
        ElevationDatasetFileMeta.file_path == file_path,
    )
    existing = db.execute(stmt).scalar_one_or_none()
    
    if existing:
        existing.bbox_min_lon = stats.get("bbox_min_lon")
        existing.bbox_max_lon = stats.get("bbox_max_lon")
        existing.bbox_min_lat = stats.get("bbox_min_lat")
        existing.bbox_max_lat = stats.get("bbox_max_lat")
        existing.sample_count = int(stats.get("sample_count", 0))
        existing.update_date = utcnow()
    else:
        meta = ElevationDatasetFileMeta(
            dataset_id=dataset_id,
            file_path=file_path,
            file_name=file_name,
            bbox_min_lon=stats.get("bbox_min_lon"),
            bbox_max_lon=stats.get("bbox_max_lon"),
            bbox_min_lat=stats.get("bbox_min_lat"),
            bbox_max_lat=stats.get("bbox_max_lat"),
            sample_count=int(stats.get("sample_count", 0)),
        )
        db.add(meta)

    db.commit()


# ============================================================================
# File Record Execution Functions (for new file-centric API)
# ============================================================================


def execute_file_record_analysis_job(*, record_id: str, actor_user_id: str | None) -> None:
    """Execute analysis job for a single elevation file record."""
    db = SessionLocal()
    try:
        from .elevation_file_record_service import get_file_record_by_id

        item = get_file_record_by_id(db, record_id)
        if not item:
            return

        item.analysis_status = "running"
        item.analysis_error_message = None
        item.analysis_started_at = utcnow()
        item.analysis_finished_at = None
        item.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.file_record.analysis.running",
            {"action": "file_record_analysis_running", "file_record_id": item.id},
        )

        actor = db.execute(select(User).where(User.id == actor_user_id)).scalar_one_or_none() if actor_user_id else None
        if actor is None:
            actor = db.execute(select(User).where(User.status == "active").order_by(User.id.asc())).scalars().first()
        if actor is None:
            item.analysis_status = "failed"
            item.analysis_error_message = "未找到可用用户执行分析"
            item.analysis_finished_at = utcnow()
            item.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.file_record.analysis.failed",
                {"action": "file_record_analysis_failed", "file_record_id": item.id},
            )
            return

        # Detect GDEM data source type from filename
        gdem_info = _detect_gdem_dataset(Path(item.file_path).name)
        if gdem_info:
            item.data_source_type = gdem_info["source_type"]
            if item.resolution_m is None:
                item.resolution_m = gdem_info["resolution_m"]
            # Update source if not set
            if item.source is None:
                item.source = "ASTER GDEM" if gdem_info["source_type"] in ["gdemv2", "gdemv3"] else item.source

        # Perform analysis using the same logic as dataset analysis
        mount = _require_mount(db, item.mount_code)
        driver = _build_driver_or_400(mount)

        try:
            read_result = driver.read_file(item.file_path)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"文件不存在: {item.file_path}"
            ) from exc

        # Analyze based on file format
        if item.file_format == "csv":
            text = _decode_csv_bytes(read_result.content)
            import csv
            import io
            rows = list(csv.DictReader(io.StringIO(text)))
            if not rows:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空")

            points: list[ElevationSamplePoint] = []
            for index, row in enumerate(rows, start=2):
                lon = _pick_float(row, ["longitude", "lon", "lng", "经度"])
                lat = _pick_float(row, ["latitude", "lat", "纬度"])
                altitude = _pick_float(row, ["altitude_m", "altitude", "elevation", "dem", "海拔m", "高程"])
                if lon is None or lat is None or altitude is None:
                    continue
                if lon < -180 or lon > 180 or lat < -90 or lat > 90:
                    continue
                points.append(ElevationSamplePoint(lon=lon, lat=lat, altitude_m=altitude))

            if not points:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件没有有效样本点")

            item.sample_count = len(points)
            item.bbox_min_lon = min(p.lon for p in points)
            item.bbox_max_lon = max(p.lon for p in points)
            item.bbox_min_lat = min(p.lat for p in points)
            item.bbox_max_lat = max(p.lat for p in points)

        elif item.file_format in RASTER_FILE_FORMATS:
            _require_rasterio_available()
            import tempfile
            import os

            # Write to temp file for rasterio processing
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(item.file_path).suffix) as tmp:
                tmp.write(read_result.content)
                tmp_path = tmp.name

            try:
                import rasterio
                from rasterio.warp import calculate_default_transform, transform_bounds

                with rasterio.open(tmp_path) as src:
                    # Get bounds in WGS84
                    if src.crs and src.crs.to_epsg() != 4326:
                        bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
                    else:
                        bounds = src.bounds

                    # Calculate sample count (approximate)
                    sample_count = src.width * src.height
                    if sample_count > 2147483647:
                        sample_count = 2147483647

                    item.sample_count = sample_count
                    item.bbox_min_lon = float(bounds[0])
                    item.bbox_max_lon = float(bounds[2])
                    item.bbox_min_lat = float(bounds[1])
                    item.bbox_max_lat = float(bounds[3])
            finally:
                os.unlink(tmp_path)

        saved = get_file_record_by_id(db, record_id)
        if saved is None:
            return
        saved.analysis_status = "success"
        saved.analysis_error_message = None
        saved.analysis_finished_at = utcnow()
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()
        _publish_elevation_change(
            "elevation.file_record.analysis.success",
            {"action": "file_record_analysis_success", "file_record_id": saved.id},
        )
        _queue_file_record_terrain_build_after_analysis(db, record=saved, actor_user_id=actor.id)
    except Exception as exc:
        from .elevation_file_record_service import get_file_record_by_id
        failed = get_file_record_by_id(db, record_id)
        if failed is not None:
            failed.analysis_status = "failed"
            failed.analysis_error_message = str(exc)
            failed.analysis_finished_at = utcnow()
            failed.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.file_record.analysis.failed",
                {"action": "file_record_analysis_failed", "file_record_id": failed.id},
            )
        raise
    finally:
        db.close()


def execute_file_record_terrain_build_job(*, record_id: str, actor_user_id: str | None) -> None:
    """Execute terrain build job for a single elevation file record."""
    db = SessionLocal()
    try:
        from .elevation_file_record_service import get_file_record_by_id

        item = get_file_record_by_id(db, record_id)
        if not item:
            return

        if item.file_format not in TERRAIN_SUPPORTED_DATASET_FORMATS:
            item.terrain_status = "not_supported"
            item.terrain_error_message = "文件格式不支持地形瓦片生成"
            item.update_date = utcnow()
            db.commit()
            return

        item.terrain_status = "processing"
        item.terrain_error_message = None
        item.update_date = utcnow()
        db.commit()
        _publish_elevation_change(
            "elevation.file_record.terrain.processing",
            {"action": "file_record_terrain_processing", "file_record_id": item.id},
        )

        actor = db.execute(select(User).where(User.id == actor_user_id)).scalar_one_or_none() if actor_user_id else None
        if actor is None:
            actor = db.execute(select(User).where(User.status == "active").order_by(User.id.asc())).scalars().first()
        if actor is None:
            item.terrain_status = "failed"
            item.terrain_error_message = "未找到可用用户执行地形构建"
            item.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.file_record.terrain.failed",
                {"action": "file_record_terrain_failed", "file_record_id": item.id},
            )
            return

        artifacts = _build_file_record_terrain_tiles(db, item)

        saved = get_file_record_by_id(db, record_id)
        if saved is None:
            return
        saved.terrain_status = "ready"
        saved.terrain_error_message = None
        saved.terrain_root_path = _resolve_file_record_terrain_dir(saved.id)
        saved.terrain_url_template = _build_file_record_terrain_url_template(saved.id)
        saved.terrain_min_zoom = artifacts.min_zoom
        saved.terrain_max_zoom = artifacts.max_zoom
        saved.terrain_bounds = artifacts.bounds
        saved.terrain_metadata = artifacts.metadata
        saved.update_date = utcnow()
        saved.update_user = actor.id
        db.commit()
        _publish_elevation_change(
            "elevation.file_record.terrain.ready",
            {"action": "file_record_terrain_ready", "file_record_id": saved.id},
        )
    except Exception as exc:
        from .elevation_file_record_service import get_file_record_by_id
        failed = get_file_record_by_id(db, record_id)
        if failed is not None:
            failed.terrain_status = "failed"
            failed.terrain_error_message = str(exc)
            failed.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.file_record.terrain.failed",
                {"action": "file_record_terrain_failed", "file_record_id": failed.id},
            )
        raise
    finally:
        db.close()
