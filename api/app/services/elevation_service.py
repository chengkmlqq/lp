from __future__ import annotations

import asyncio
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
from ..models.elevation import ElevationApplyJob, ElevationFileRecord
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.user import User
from ..schemas.elevation import (
    ElevationApplyJobCreateRequest,
    ElevationApplyJobCreateResponse,
    ElevationApplyJobListResponse,
    ElevationApplyJobSummary,
    ElevationFileRecordTaskStatusResponse,
    ElevationFileRecordTerrainTaskStatusResponse,
    ElevationFileRecordPreviewResponse,
    ElevationPreviewCell,
    ElevationPreviewDiagnostics,
    ElevationPreviewPoint,
    ElevationTerrainLayerResponse,
)
from .file_service import _build_driver_or_400, _require_mount, list_enabled_mounts
from .line_preparation_service import record_line_preparation_source
from .push_service import publish_topic
from .storage_driver import StorageDriverError, StorageInvalidPathError, StoragePathNotFoundError, join_virtual_path, normalize_virtual_path

ELEVATION_TOPIC = "admin.elevation"
POWER_LINES_TOPIC = "admin.power-lines"
NEAREST_MATCH_MAX_DISTANCE_M = 2000.0
ELEVATION_FILE_EXT_FORMAT_MAP = {
    ".tif": "tif",
    ".tiff": "tif",
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
    r"ASTGTMV003_[NS]\d{2}[EW]\d{3}_dem\.tiff?",  # GDEM V3
    r"ASTGTM2_[NS]\d{2}[EW]\d{3}_dem\.tiff?",      # GDEM V2
]
GDEM_DEFAULT_RESOLUTION_M = 30.0


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


def serialize_job(item: ElevationApplyJob) -> ElevationApplyJobSummary:
    line = item.line
    file_record = item.file_record
    return ElevationApplyJobSummary(
        id=item.id,
        line_id=item.line_id,
        line_code=line.code if line else None,
        line_name=line.name if line else None,
        file_record_id=item.file_record_id,
        file_record_name=file_record.file_name if file_record else None,
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


def get_file_record_by_id(db: Session, record_id: str) -> ElevationFileRecord | None:
    return db.execute(
        select(ElevationFileRecord).where(ElevationFileRecord.id == record_id)
    ).scalar_one_or_none()


def _supports_file_record_terrain_build(record: ElevationFileRecord) -> bool:
    return _resolve_file_record_format(record) in TERRAIN_SUPPORTED_DATASET_FORMATS


def _default_terrain_status_for_format(file_format: str) -> str:
    return "pending" if file_format in TERRAIN_SUPPORTED_DATASET_FORMATS else "not_supported"


def _resolve_file_record_terrain_dir(record_id: str) -> str:
    return f"/elevation/terrain/records/{record_id[:2]}/{record_id[2:4]}/{record_id}"


def _resolve_file_record_terrain_layer_path(record_id: str) -> str:
    return join_virtual_path(_resolve_file_record_terrain_dir(record_id), "layer.json")


def _resolve_file_record_terrain_tile_path(*, record_id: str, z: int, x: int, y: int) -> str:
    return join_virtual_path(join_virtual_path(join_virtual_path(_resolve_file_record_terrain_dir(record_id), str(z)), str(x)), f"{y}.terrain")


def _build_file_record_terrain_url_template(record_id: str) -> str:
    return f"/terrain/{record_id}/{{z}}/{{x}}/{{y}}.terrain"


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


def list_jobs(
    db: Session,
    *,
    line_id: str | None,
    status_filter: str | None,
    limit: int,
    file_record_id: str | None = None,
) -> ElevationApplyJobListResponse:
    stmt = select(ElevationApplyJob)
    total_stmt = select(func.count()).select_from(ElevationApplyJob)

    if line_id:
        stmt = stmt.where(ElevationApplyJob.line_id == line_id)
        total_stmt = total_stmt.where(ElevationApplyJob.line_id == line_id)
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

    file_record: ElevationFileRecord | None = None
    if payload.file_record_id:
        file_record = get_file_record_by_id(db, payload.file_record_id)
        if not file_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程文件记录不存在")
        if file_record.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="高程文件记录未启用")
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="必须提供 file_record_id")

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
        file_record_id=file_record.id,
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

    _publish_elevation_change(
        "elevation.job.created",
        {
            "action": "job_created",
            "job_id": latest.id,
            "line_id": latest.line_id,
            "file_record_id": latest.file_record_id,
        },
    )
    return ElevationApplyJobCreateResponse(job=serialize_job(latest), queued=True)


def _dispatch_elevation_apply_task(*, job_id: str, actor_user_id: str | None):
    from ..tasks.elevation_tasks import apply_elevation_for_line_job

    return apply_elevation_for_line_job.delay(job_id, actor_user_id)


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
        _publish_elevation_change(
            "elevation.job.running",
            {
                "action": "job_running",
                "job_id": job.id,
                "line_id": job.line_id,
                "file_record_id": job.file_record_id,
            },
        )

        line = db.execute(select(Line).where(Line.id == job.line_id)).scalar_one_or_none()
        file_record = get_file_record_by_id(db, job.file_record_id) if job.file_record_id else None
        elevation_source = file_record
        if not line or file_record is None:
            job.status = "failed"
            job.error_message = "线路或高程文件记录不存在"
            job.finished_at = utcnow()
            job.update_date = utcnow()
            db.commit()
            _publish_elevation_change(
                "elevation.job.failed",
                {
                    "action": "job_failed",
                    "job_id": job.id,
                    "line_id": job.line_id,
                    "file_record_id": job.file_record_id,
                },
            )
            return

        file_format = _resolve_elevation_file_format(elevation_source)
        stats, warnings = _apply_raster_to_line_towers(
            db,
            line_id=line.id,
            elevation_source=elevation_source,
            mode=job.mode,
        )

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

        _publish_elevation_change(
            "elevation.job.success",
            {
                "action": "job_success",
                "job_id": job.id,
                "line_id": line.id,
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
            _publish_elevation_change(
                "elevation.job.failed",
                {
                    "action": "job_failed",
                    "job_id": failed.id,
                    "line_id": failed.line_id,
                    "file_record_id": failed.file_record_id,
                },
            )
        raise
    finally:
        db.close()


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


def _resolve_dataset_mount_code(db: Session, *, requested_mount_code: str | None) -> str:
    code = _normalize_str(requested_mount_code)
    if code is not None:
        _require_mount(db, code)
        return code

    mounts = list_enabled_mounts(db)
    if not mounts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无可用文件挂载点")
    return mounts[0].code


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


def _detect_file_format(file_path: str) -> str:
    extension = Path(file_path).suffix.lower()
    file_format = ELEVATION_FILE_EXT_FORMAT_MAP.get(extension)
    if not file_format:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的高程文件类型: {extension or 'unknown'}，仅支持 .tif/.tiff",
        )
    return file_format


def _resolve_file_record_format(record: ElevationFileRecord) -> str:
    declared = (record.file_format or "").strip().lower()
    detected = _detect_file_format(record.file_path)
    if declared and declared in ELEVATION_FILE_EXT_FORMAT_MAP.values():
        if declared == detected:
            return declared
        if declared in RASTER_FILE_FORMATS and detected in RASTER_FILE_FORMATS:
            return detected
    return detected


def _resolve_elevation_file_format(elevation_source: ElevationFileRecord) -> str:
    return _resolve_file_record_format(elevation_source)


def _elevation_source_metadata(elevation_source: ElevationFileRecord) -> dict[str, str | None]:
    return {
        "file_record_id": getattr(elevation_source, "id", None),
        "file_record_name": getattr(elevation_source, "file_name", None),
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
    record: ElevationFileRecord,
) -> _OpenedRasterDataset:
    file_format = _resolve_elevation_file_format(record)
    if file_format not in RASTER_FILE_FORMATS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前文件不是栅格高程文件: {record.file_path}",
        )

    rasterio = _require_rasterio_available()

    mount = _require_mount(db, record.mount_code)
    driver = _build_driver_or_400(mount)
    try:
        read_result = driver.read_file(record.file_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"高程数据文件不存在: {record.file_path}") from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    suffix = Path(record.file_path).suffix.lower() or ".img"
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
            detail=f"高程栅格文件解析失败: {record.file_path}",
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
    record: ElevationFileRecord,
    limit: int,
) -> ElevationFileRecordPreviewResponse:
    from ..services.elevation_file_record_service import serialize_file_record
    warnings: list[str] = []
    with _open_raster_dataset(db, record) as opened:
        rasterio = opened.rasterio
        src = opened.dataset
        warning_text = _append_non_wgs84_bounds_warning(rasterio=rasterio, src=src)
        if warning_text:
            warnings.append(warning_text)

        width = int(src.width or 0)
        height = int(src.height or 0)
        source_bounds = src.bounds
        source_crs_text = str(src.crs) if src.crs is not None else None
        diagnostics = ElevationPreviewDiagnostics(
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
            return ElevationFileRecordPreviewResponse(
                record=serialize_file_record(record),
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
        sampled_points: list[ElevationPreviewPoint] = []
        sampled_cells: list[ElevationPreviewCell] = []

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
                    ElevationPreviewCell(
                        min_longitude=round(min_lon, 6),
                        max_longitude=round(max_lon, 6),
                        min_latitude=round(min_lat, 6),
                        max_latitude=round(max_lat, 6),
                        altitude_m=round(altitude, 3),
                    )
                )
                sampled_points.append(
                    ElevationPreviewPoint(
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

        return ElevationFileRecordPreviewResponse(
            record=serialize_file_record(record),
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
    elevation_source: ElevationFileRecord,
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
        if item.file_format in RASTER_FILE_FORMATS:
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

        # 使用 CTB Worker (ctb-tile) 生成地形瓦片
        import os as _os
        from ..core.celery_app import celery_app as _celery_app
        from celery.result import AsyncResult as _AsyncResult

        # 1. 从 MinIO 下载 DEM 到共享卷临时路径
        mount = _require_mount(db, item.mount_code)
        driver = _build_driver_or_400(mount)
        _read_result = driver.read_file(item.file_path)
        _temp_dir = "/app/data/temp"
        _os.makedirs(_temp_dir, exist_ok=True)
        _temp_dem = f"{_temp_dir}/{record_id}.tif"
        with open(_temp_dem, "wb") as _f:
            _f.write(_read_result.content)

        # 2. 发送任务到 CTB Worker (ctb queue)
        _ctb_input = f"/data/app/temp/{record_id}.tif"
        _task = _celery_app.send_task(
            "app.tasks.ctb.build_file_record_terrain",
            kwargs={
                "record_id": record_id,
                "input_path": _ctb_input,
                "name": item.file_name or record_id,
            },
            queue="ctb",
        )

        # 3. 等待 CTB Worker 完成（最多 1 小时）
        _ctb_result = _task.get(timeout=3600)

        # 4. 清理临时 DEM 文件
        try:
            _os.unlink(_temp_dem)
        except Exception:
            pass

        # 5. 映射 CTB Worker 结果到 _TerrainBuildArtifacts
        _tile_count = _ctb_result.get("tile_count", 0)
        _min_zoom = _ctb_result.get("min_zoom", 0)
        _max_zoom = _ctb_result.get("max_zoom", 6)
        _bounds_list = _ctb_result.get("bounds", [0, 0, 0, 0])
        _layer_url = _ctb_result.get("layer_url", f"/terrain/{record_id}/layer.json")

        artifacts = _TerrainBuildArtifacts(
            min_zoom=_min_zoom,
            max_zoom=_max_zoom,
            bounds={"west": _bounds_list[0], "south": _bounds_list[1], "east": _bounds_list[2], "north": _bounds_list[3]},
            metadata={
                "tool": "ctb-tile",
                "format": "heightmap-1.0",
                "projection": "EPSG:4326",
                "tile_size": 65,
                "generated_at": utcnow().isoformat(),
                "tile_count": _tile_count,
                "layer_url": _layer_url,
                "terrain_url_template": f"/terrain/{record_id}/{{z}}/{{x}}/{{y}}.terrain",
            },
        )

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
