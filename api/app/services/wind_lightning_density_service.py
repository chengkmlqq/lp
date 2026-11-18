"""风电场地闪密度统计 —— 业务编排层（数据库 + 对象存储 + 任务派发）。

算法本身在 ``app.services.wind_lightning_density``（纯函数），本模块负责：

- 上传校验与对象存储落地（风机文件 + 雷电 CSV）；
- 批次记录的创建/重算/逻辑删除与列表查询；
- Celery 任务执行体 ``run_batch``（解析 → 统计 → 落库 → 出图）；
- 网格表 / 风机表 / 图片 / Excel 导出 / 核心程序文件（file_3、file_4）导出。

与 ``lightning_distribution``（GB/T 40621 地闪密度）完全隔离：不读写其表，
不调用其算法与色标。
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

import numpy as np
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.file_upload import validate_upload
from ..models.base import utcnow
from ..models.wind_lightning_density import (
    WindLightningDensityBatch,
    WindLightningDensityCell,
    WindLightningDensityTurbine,
)
from ..schemas.wind_lightning_density import (
    WindLightningDensityBatchDetail,
    WindLightningDensityBatchListResponse,
    WindLightningDensityBatchSummary,
    WindLightningDensityCellListResponse,
    WindLightningDensityCellRow,
    WindLightningDensityCoreGrid,
    WindLightningDensityImportResponse,
    WindLightningDensityPreviewResponse,
    WindLightningDensityTurbineListResponse,
    WindLightningDensityTurbineRow,
)
from ..services.audit_service import compose_audit_detail, write_audit_log
from ..services import minio_storage
from ..services import wind_lightning_density as algo

WIND_LIGHTNING_DENSITY_TOPIC = "admin.wind-lightning-density"
TASK_NAME = "app.tasks.wind_lightning_density_tasks.run_wind_lightning_density_job"

# 与 lightning_distribution 的 /lightning-currents/distributions 完全独立的 API 前缀
API_PREFIX = "/api/v1/wind-lightning-density"


# ---------------------------------------------------------------------------
# 解析/统计（纯计算 + 校验）
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Analysis:
    turbine_count: int
    turbine_skipped: int
    total_records: int
    valid_records: int
    skipped_records: int
    in_range_records: int
    bbox: algo.BoundingBox
    lon_bins: np.ndarray
    lat_bins: np.ndarray
    x_count: int
    y_count: int
    years: float
    years_source: str
    years_inferred: bool
    detected_years: list[int]
    counts: np.ndarray
    per_cell: np.ndarray
    per_km2: np.ndarray
    cells: list[dict[str, Any]]
    turbines: list[dict[str, Any]]
    turbine_counts: dict[tuple[int, int], int]
    core_grid: dict[str, float | int]
    core_density: np.ndarray
    stats: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _resolve_years(
    lightning: algo.LightningParseResult, years_source: str
) -> tuple[float, str, bool, list[int]]:
    """统计年限：固定 6 年 / 按时间列自动推断（推断不到回落 6 年）。"""
    if years_source == "fixed":
        return algo.DEFAULT_DATA_YEARS, "fixed", False, list(lightning.detected_years)
    inferred = lightning.inferred_years
    if inferred:
        return float(inferred), "auto", True, list(lightning.detected_years)
    return algo.DEFAULT_DATA_YEARS, "auto", False, list(lightning.detected_years)


def analyze_inputs(
    *,
    turbine_content: bytes,
    turbine_filename: str,
    lightning_content: bytes,
    lightning_filename: str,
    grid_step_deg: float = algo.DEFAULT_GRID_STEP_DEG,
    margin_deg: float = algo.DEFAULT_MARGIN_DEG,
    years_source: str = "auto",
) -> Analysis:
    """解析两份源文件并完成全部统计（供预览、新建、重算复用）。"""
    if years_source not in {"auto", "fixed"}:
        raise algo.WindLightningDensityError("统计年限来源只支持「自动」或「固定 6 年」")
    if grid_step_deg <= 0 or grid_step_deg > 1:
        raise algo.WindLightningDensityError("网格步长需在 (0, 1] 度之间")
    if margin_deg < 0 or margin_deg > 1:
        raise algo.WindLightningDensityError("外扩边距需在 [0, 1] 度之间")

    turbine_result = algo.parse_turbine_file(turbine_content, turbine_filename)
    lightning = algo.parse_lightning_csv(lightning_content)

    bbox = algo.compute_bbox(turbine_result.points, margin_deg)
    x_count, y_count = algo.validate_grid(bbox, grid_step_deg)
    lon_bins, lat_bins = algo.build_bins(bbox, grid_step_deg)

    lon_in, lat_in, in_range = algo.filter_in_range(lightning.lon, lightning.lat, bbox)
    counts = algo.histogram2d(lon_in, lat_in, lon_bins, lat_bins)

    years, resolved_source, inferred, detected_years = _resolve_years(lightning, years_source)
    per_cell, per_km2 = algo.density_from_counts(
        counts, data_years=years, step_deg=grid_step_deg
    )

    turbines, turbine_counts = algo.assign_turbines(
        turbine_result.points, lon_bins, lat_bins, per_km2
    )
    cells = algo.build_cells(
        counts,
        lon_bins,
        lat_bins,
        data_years=years,
        step_deg=grid_step_deg,
        turbine_counts=turbine_counts,
    )
    stats = algo.compute_stats(
        counts,
        data_years=years,
        step_deg=grid_step_deg,
        total_records=lightning.total_rows,
        valid_records=in_range,
        skipped_records=lightning.skipped_rows,
        turbine_count=len(turbine_result.points),
        years_source=resolved_source,
    )
    core_grid = algo.core_grid(bbox, grid_step_deg)
    core_density = algo.core_density_matrix(lightning.lon, lightning.lat, core_grid, years)

    warnings: list[str] = list(turbine_result.warnings)
    if not inferred and resolved_source == "auto":
        warnings.append("雷电 CSV 未识别到可推断的时间列，统计年限按固定 6 年计算")
    if inferred and detected_years:
        warnings.append(
            f"统计年限按雷电数据实际覆盖年份自动推断为 {years:.0f} 年"
            f"（{min(detected_years)}–{max(detected_years)}）"
        )
    if in_range == 0:
        warnings.append(
            "统计范围内没有落雷记录（0 条），密度矩阵全为 0；请核对风机点位与雷电数据是否属于同一地区"
        )
    if lightning.skipped_rows:
        warnings.append(f"雷电 CSV 有 {lightning.skipped_rows} 行坐标无效，已跳过")

    return Analysis(
        turbine_count=len(turbine_result.points),
        turbine_skipped=turbine_result.skipped,
        total_records=lightning.total_rows,
        valid_records=in_range,
        skipped_records=lightning.skipped_rows,
        in_range_records=in_range,
        bbox=bbox,
        lon_bins=lon_bins,
        lat_bins=lat_bins,
        x_count=x_count,
        y_count=y_count,
        years=years,
        years_source=resolved_source,
        years_inferred=inferred,
        detected_years=detected_years,
        counts=counts,
        per_cell=per_cell,
        per_km2=per_km2,
        cells=cells,
        turbines=turbines,
        turbine_counts=turbine_counts,
        core_grid=core_grid,
        core_density=core_density,
        stats=stats,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 上传/对象存储
# ---------------------------------------------------------------------------
def _read_upload(file: UploadFile, *, purpose: str, allowed_exts: set[str]) -> tuple[bytes, str]:
    validate_upload(file, purpose=purpose, allowed_exts=allowed_exts)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    filename = str(file.filename or "upload").strip() or "upload"
    return content, filename


def _turbine_object_key(batch_id: str, filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    return f"wind-lightning-density/{batch_id}/turbines.{suffix}"


def _lightning_object_key(batch_id: str, filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
    return f"wind-lightning-density/{batch_id}/lightning.{suffix}"


def _image_object_key(batch_id: str) -> str:
    return f"wind-lightning-density/{batch_id}/{uuid4().hex}.png"


# ---------------------------------------------------------------------------
# 查询/序列化
# ---------------------------------------------------------------------------
def _get_batch_or_404(db: Session, batch_id: str) -> WindLightningDensityBatch:
    batch = db.execute(
        select(WindLightningDensityBatch).where(
            WindLightningDensityBatch.id == batch_id,
            WindLightningDensityBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="风电场地闪密度批次不存在")
    return batch


def _summary(batch: WindLightningDensityBatch) -> WindLightningDensityBatchSummary:
    return WindLightningDensityBatchSummary(
        id=batch.id,
        batch_name=batch.batch_name or "",
        wind_farm_name=batch.wind_farm_name,
        notes=batch.notes,
        status=batch.status,
        stage=batch.stage,
        progress=batch.progress,
        task_id=batch.task_id,
        error_message=batch.error_message,
        turbine_count=batch.turbine_count,
        total_records=batch.total_records,
        valid_records=batch.valid_records,
        skipped_records=batch.skipped_records,
        data_years=batch.data_years,
        years_source=batch.years_source,
        overall_density=batch.overall_density,
        peak_density=batch.peak_density,
        area_km2=batch.area_km2,
        grid_x_count=batch.grid_x_count,
        grid_y_count=batch.grid_y_count,
        has_image=bool(batch.image_object_key),
        create_date=batch.create_date,
        update_date=batch.update_date,
        create_user=batch.create_user,
    )


def _core_grid_from_stats(batch: WindLightningDensityBatch) -> WindLightningDensityCoreGrid | None:
    raw = (batch.stats_json or {}).get("core_grid")
    if not isinstance(raw, dict):
        return None
    try:
        return WindLightningDensityCoreGrid(
            start_lon=float(raw["start_lon"]),
            start_lat=float(raw["start_lat"]),
            x_count=int(raw["x_count"]),
            y_count=int(raw["y_count"]),
            step_deg=float(raw.get("step_deg", batch.grid_step_deg)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def get_batch_detail(db: Session, batch_id: str) -> WindLightningDensityBatchDetail:
    batch = _get_batch_or_404(db, batch_id)
    cell_rows = db.execute(
        select(func.count())
        .select_from(WindLightningDensityCell)
        .where(WindLightningDensityCell.batch_id == batch.id)
    ).scalar() or 0
    summary = _summary(batch)
    return WindLightningDensityBatchDetail(
        **summary.model_dump(),
        turbine_source_file_name=batch.turbine_source_file_name,
        lightning_source_file_name=batch.lightning_source_file_name,
        grid_step_deg=batch.grid_step_deg,
        margin_deg=batch.margin_deg,
        bbox_min_lon=batch.bbox_min_lon,
        bbox_max_lon=batch.bbox_max_lon,
        bbox_min_lat=batch.bbox_min_lat,
        bbox_max_lat=batch.bbox_max_lat,
        peak_lon=batch.peak_lon,
        peak_lat=batch.peak_lat,
        stats_json=batch.stats_json,
        core_grid=_core_grid_from_stats(batch),
        cell_rows_stored=int(cell_rows),
    )


def list_batches(
    db: Session,
    *,
    keyword: str | None = None,
    status_filter: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> WindLightningDensityBatchListResponse:
    filters: list[Any] = [WindLightningDensityBatch.is_deleted.is_(False)]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                WindLightningDensityBatch.batch_name.ilike(pattern),
                WindLightningDensityBatch.wind_farm_name.ilike(pattern),
            )
        )
    if status_filter:
        filters.append(WindLightningDensityBatch.status == status_filter)
    if date_from:
        filters.append(WindLightningDensityBatch.create_date >= date_from)
    if date_to:
        filters.append(WindLightningDensityBatch.create_date <= date_to)

    total = db.execute(
        select(func.count()).select_from(WindLightningDensityBatch).where(*filters)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindLightningDensityBatch)
            .where(*filters)
            .order_by(
                WindLightningDensityBatch.create_date.desc(),
                WindLightningDensityBatch.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindLightningDensityBatchListResponse(
        total=int(total), items=[_summary(row) for row in rows]
    )


_CELL_SORT_FIELDS = {
    "cell_i": WindLightningDensityCell.cell_i,
    "cell_j": WindLightningDensityCell.cell_j,
    "strike_count": WindLightningDensityCell.strike_count,
    "density_per_cell_year": WindLightningDensityCell.density_per_cell_year,
    "density_per_km2_year": WindLightningDensityCell.density_per_km2_year,
    "turbine_count": WindLightningDensityCell.turbine_count,
}


def list_cells(
    db: Session,
    batch_id: str,
    *,
    sort_by: str = "density_per_km2_year",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> WindLightningDensityCellListResponse:
    batch = _get_batch_or_404(db, batch_id)
    column = _CELL_SORT_FIELDS.get(sort_by, WindLightningDensityCell.density_per_km2_year)
    order = column.desc() if sort_order != "asc" else column.asc()
    total = db.execute(
        select(func.count())
        .select_from(WindLightningDensityCell)
        .where(WindLightningDensityCell.batch_id == batch.id)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindLightningDensityCell)
            .where(WindLightningDensityCell.batch_id == batch.id)
            .order_by(order, WindLightningDensityCell.cell_j.asc(), WindLightningDensityCell.cell_i.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindLightningDensityCellListResponse(
        total=int(total),
        items=[
            WindLightningDensityCellRow(
                cell_i=row.cell_i,
                cell_j=row.cell_j,
                center_lon=row.center_lon,
                center_lat=row.center_lat,
                min_lon=row.min_lon,
                max_lon=row.max_lon,
                min_lat=row.min_lat,
                max_lat=row.max_lat,
                strike_count=row.strike_count,
                density_per_cell_year=row.density_per_cell_year,
                density_per_km2_year=row.density_per_km2_year,
                turbine_count=row.turbine_count,
            )
            for row in rows
        ],
    )


def list_turbines(
    db: Session,
    batch_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> WindLightningDensityTurbineListResponse:
    batch = _get_batch_or_404(db, batch_id)
    total = db.execute(
        select(func.count())
        .select_from(WindLightningDensityTurbine)
        .where(WindLightningDensityTurbine.batch_id == batch.id)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindLightningDensityTurbine)
            .where(WindLightningDensityTurbine.batch_id == batch.id)
            .order_by(WindLightningDensityTurbine.seq.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindLightningDensityTurbineListResponse(
        total=int(total),
        items=[
            WindLightningDensityTurbineRow(
                seq=row.seq,
                turbine_no=row.turbine_no,
                lon=row.lon,
                lat=row.lat,
                cell_i=row.cell_i,
                cell_j=row.cell_j,
                cell_density=row.cell_density,
            )
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# 新建 / 重算 / 删除
# ---------------------------------------------------------------------------
def preview_batch(
    *,
    turbine_file: UploadFile,
    lightning_file: UploadFile,
    grid_step_deg: float,
    margin_deg: float,
    years_source: str,
) -> WindLightningDensityPreviewResponse:
    turbine_content, turbine_name = _read_upload(
        turbine_file, purpose="text", allowed_exts={"txt", "csv", "xlsx", "xlsm"}
    )
    lightning_content, lightning_name = _read_upload(
        lightning_file, purpose="text", allowed_exts={"csv", "txt"}
    )
    analysis = analyze_inputs(
        turbine_content=turbine_content,
        turbine_filename=turbine_name,
        lightning_content=lightning_content,
        lightning_filename=lightning_name,
        grid_step_deg=grid_step_deg,
        margin_deg=margin_deg,
        years_source=years_source,
    )
    return WindLightningDensityPreviewResponse(
        turbine_count=analysis.turbine_count,
        turbine_skipped=analysis.turbine_skipped,
        total_records=analysis.total_records,
        valid_records=analysis.valid_records,
        skipped_records=analysis.skipped_records,
        in_range_records=analysis.in_range_records,
        bbox_min_lon=analysis.bbox.min_lon,
        bbox_max_lon=analysis.bbox.max_lon,
        bbox_min_lat=analysis.bbox.min_lat,
        bbox_max_lat=analysis.bbox.max_lat,
        grid_x_count=analysis.x_count,
        grid_y_count=analysis.y_count,
        area_km2=analysis.stats.get("area_km2"),
        data_years=analysis.years,
        years_source=analysis.years_source,
        detected_years=analysis.detected_years,
        warnings=analysis.warnings,
    )


def create_batch(
    db: Session,
    *,
    turbine_file: UploadFile,
    lightning_file: UploadFile,
    batch_name: str | None,
    wind_farm_name: str | None,
    notes: str | None,
    grid_step_deg: float,
    margin_deg: float,
    years_source: str,
    actor_user_id: str,
) -> WindLightningDensityImportResponse:
    """校验通过后写入对象存储 + 建批次记录 + 派发 Celery 任务。

    校验失败抛 400，不产生任何批次记录（不落半成品）。
    """
    turbine_content, turbine_name = _read_upload(
        turbine_file, purpose="text", allowed_exts={"txt", "csv", "xlsx", "xlsm"}
    )
    lightning_content, lightning_name = _read_upload(
        lightning_file, purpose="text", allowed_exts={"csv", "txt"}
    )
    analysis = analyze_inputs(
        turbine_content=turbine_content,
        turbine_filename=turbine_name,
        lightning_content=lightning_content,
        lightning_filename=lightning_name,
        grid_step_deg=grid_step_deg,
        margin_deg=margin_deg,
        years_source=years_source,
    )

    batch_id = uuid4().hex
    turbine_key = _turbine_object_key(batch_id, turbine_name)
    lightning_key = _lightning_object_key(batch_id, lightning_name)
    minio_storage.put_object(turbine_key, turbine_content, content_type="text/plain")
    minio_storage.put_object(lightning_key, lightning_content, content_type="text/csv")

    now = utcnow()
    batch = WindLightningDensityBatch(
        id=batch_id,
        batch_name=(batch_name or "").strip() or (wind_farm_name or "").strip() or turbine_name,
        wind_farm_name=(wind_farm_name or "").strip() or None,
        notes=(notes or "").strip() or None,
        grid_step_deg=float(grid_step_deg),
        margin_deg=float(margin_deg),
        data_years=analysis.years,
        years_source=analysis.years_source,
        turbine_source_file_name=turbine_name,
        turbine_object_key=turbine_key,
        lightning_source_file_name=lightning_name,
        lightning_object_key=lightning_key,
        turbine_count=analysis.turbine_count,
        total_records=analysis.total_records,
        valid_records=analysis.valid_records,
        skipped_records=analysis.skipped_records,
        bbox_min_lon=analysis.bbox.min_lon,
        bbox_max_lon=analysis.bbox.max_lon,
        bbox_min_lat=analysis.bbox.min_lat,
        bbox_max_lat=analysis.bbox.max_lat,
        grid_x_count=analysis.x_count,
        grid_y_count=analysis.y_count,
        status="pending",
        stage="parsing",
        progress=0,
        create_user=actor_user_id,
        create_date=now,
        update_date=now,
    )
    db.add(batch)
    db.commit()

    write_audit_log(
        db,
        action="wind_lightning_density.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"batch_id={batch.id}",
            f"batch_name={batch.batch_name}",
            f"turbine_file={turbine_name}",
            f"lightning_file={lightning_name}",
            f"grid_step_deg={grid_step_deg}",
            f"margin_deg={margin_deg}",
            f"years_source={analysis.years_source}",
        ),
    )
    db.commit()

    task_id = _dispatch_batch_task(batch.id, actor_user_id)
    batch.task_id = task_id
    batch.status = "processing"
    db.commit()
    return WindLightningDensityImportResponse(
        batch_id=batch.id, task_id=task_id, status="processing"
    )


def _dispatch_batch_task(batch_id: str, actor_user_id: str | None) -> str | None:
    from ..core.celery_app import celery_app as _celery_app

    try:
        task = _celery_app.send_task(
            TASK_NAME,
            kwargs=dict(batch_id=batch_id, actor_user_id=actor_user_id),
            queue="celery",
        )
        return str(task.id)
    except Exception:  # noqa: BLE001 - broker 不可用时不阻塞接口（任务可重试）
        return None


def recompute_batch(
    db: Session, batch_id: str, *, actor_user_id: str
) -> WindLightningDensityImportResponse:
    batch = _get_batch_or_404(db, batch_id)
    db.execute(
        WindLightningDensityCell.__table__.delete().where(
            WindLightningDensityCell.batch_id == batch.id
        )
    )
    db.execute(
        WindLightningDensityTurbine.__table__.delete().where(
            WindLightningDensityTurbine.batch_id == batch.id
        )
    )
    batch.status = "pending"
    batch.stage = "parsing"
    batch.progress = 0
    batch.error_message = None
    batch.image_object_key = None
    batch.update_user = actor_user_id
    batch.update_date = utcnow()
    db.commit()

    write_audit_log(
        db,
        action="wind_lightning_density.recompute",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"batch_id={batch.id}", f"batch_name={batch.batch_name}"),
    )
    db.commit()

    task_id = _dispatch_batch_task(batch.id, actor_user_id)
    batch.task_id = task_id
    batch.status = "processing"
    db.commit()
    return WindLightningDensityImportResponse(
        batch_id=batch.id, task_id=task_id, status="processing"
    )


def delete_batch(db: Session, batch_id: str, *, actor_user_id: str) -> None:
    batch = _get_batch_or_404(db, batch_id)
    batch.is_deleted = True
    batch.update_user = actor_user_id
    batch.update_date = utcnow()
    write_audit_log(
        db,
        action="wind_lightning_density.delete",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"batch_id={batch.id}", f"batch_name={batch.batch_name}"),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 任务执行体
# ---------------------------------------------------------------------------
def run_batch(db: Session, batch_id: str, *, actor_user_id: str | None = None) -> dict[str, Any]:
    """Celery 任务执行体：重新解析源文件 → 统计 → 落库 → 出图。

    重算会先清空旧网格/风机明细，失败时批次标记 failed 并保留源文件以便重试。
    """
    batch = db.execute(
        select(WindLightningDensityBatch).where(WindLightningDensityBatch.id == batch_id)
    ).scalar_one_or_none()
    if not batch:
        raise algo.WindLightningDensityError(f"批次不存在（batch_id={batch_id}）")

    batch.status = "processing"
    batch.stage = "parsing"
    batch.progress = 5
    batch.error_message = None
    db.commit()

    turbine_content = minio_storage.get_object(batch.turbine_object_key)
    lightning_content = minio_storage.get_object(batch.lightning_object_key)

    analysis = analyze_inputs(
        turbine_content=turbine_content,
        turbine_filename=batch.turbine_source_file_name or "turbines.txt",
        lightning_content=lightning_content,
        lightning_filename=batch.lightning_source_file_name or "lightning.csv",
        grid_step_deg=batch.grid_step_deg,
        margin_deg=batch.margin_deg,
        years_source=batch.years_source,
    )

    batch.stage = "computing"
    batch.progress = 45
    batch.data_years = analysis.years
    batch.turbine_count = analysis.turbine_count
    batch.total_records = analysis.total_records
    batch.valid_records = analysis.valid_records
    batch.skipped_records = analysis.skipped_records
    batch.bbox_min_lon = analysis.bbox.min_lon
    batch.bbox_max_lon = analysis.bbox.max_lon
    batch.bbox_min_lat = analysis.bbox.min_lat
    batch.bbox_max_lat = analysis.bbox.max_lat
    batch.grid_x_count = analysis.x_count
    batch.grid_y_count = analysis.y_count
    batch.area_km2 = float(analysis.stats.get("area_km2") or 0.0)
    batch.overall_density = float(analysis.stats.get("overall_density") or 0.0)
    batch.peak_density = float(analysis.stats.get("peak_density") or 0.0)
    peak_i = analysis.stats.get("peak_cell_i")
    peak_j = analysis.stats.get("peak_cell_j")
    peak_i = int(peak_i) if peak_i is not None else -1
    peak_j = int(peak_j) if peak_j is not None else -1
    if 0 <= peak_i < analysis.x_count and 0 <= peak_j < analysis.y_count:
        batch.peak_lon = float(
            (analysis.lon_bins[peak_i] + analysis.lon_bins[peak_i + 1]) / 2.0
        )
        batch.peak_lat = float(
            (analysis.lat_bins[peak_j] + analysis.lat_bins[peak_j + 1]) / 2.0
        )
    else:
        batch.peak_lon = None
        batch.peak_lat = None
    db.commit()

    # 重算场景：清空旧明细后整批重建（同一事务内完成，避免半成品）
    db.execute(
        WindLightningDensityCell.__table__.delete().where(
            WindLightningDensityCell.batch_id == batch.id
        )
    )
    db.execute(
        WindLightningDensityTurbine.__table__.delete().where(
            WindLightningDensityTurbine.batch_id == batch.id
        )
    )
    if analysis.cells:
        db.execute(
            WindLightningDensityCell.__table__.insert(),
            [
                {
                    "id": uuid4().hex,
                    "batch_id": batch.id,
                    **cell,
                }
                for cell in analysis.cells
            ],
        )
    if analysis.turbines:
        db.execute(
            WindLightningDensityTurbine.__table__.insert(),
            [
                {
                    "id": uuid4().hex,
                    "batch_id": batch.id,
                    **turbine,
                }
                for turbine in analysis.turbines
            ],
        )

    batch.stage = "rendering"
    batch.progress = 80
    db.commit()

    preview_png = algo.render_batch_png(
        counts=analysis.counts,
        lon_bins=analysis.lon_bins,
        lat_bins=analysis.lat_bins,
        data_years=analysis.years,
        step_deg=batch.grid_step_deg,
        title=batch.batch_name or batch.wind_farm_name or "Wind Farm",
        unit="km2",
        interpolation="bilinear",
    )
    image_key = _image_object_key(batch.id)
    minio_storage.put_object(image_key, preview_png, content_type="image/png")

    stats_json: dict[str, Any] = dict(analysis.stats)
    stats_json.update(
        {
            "years_inferred": analysis.years_inferred,
            "detected_years": analysis.detected_years,
            "core_grid": analysis.core_grid,
            "warnings": analysis.warnings,
            "stored_cells": len(analysis.cells),
            "grid_step_deg": batch.grid_step_deg,
            "margin_deg": batch.margin_deg,
        }
    )
    batch.image_object_key = image_key
    batch.stats_json = stats_json
    batch.status = "completed"
    batch.stage = "done"
    batch.progress = 100
    batch.error_message = None
    batch.update_user = actor_user_id
    batch.update_date = utcnow()
    db.commit()

    return {
        "status": "completed",
        "batch_id": batch.id,
        "turbine_count": batch.turbine_count,
        "valid_records": batch.valid_records,
        "grid": [batch.grid_x_count, batch.grid_y_count],
        "warnings": analysis.warnings,
    }


def mark_batch_failed(db: Session, batch_id: str, error_message: str) -> None:
    batch = db.execute(
        select(WindLightningDensityBatch).where(WindLightningDensityBatch.id == batch_id)
    ).scalar_one_or_none()
    if not batch:
        return
    batch.status = "failed"
    batch.stage = "failed"
    batch.error_message = error_message[:2000]
    batch.update_date = utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# 出图 / 导出
# ---------------------------------------------------------------------------
def get_batch_image(
    db: Session,
    batch_id: str,
    *,
    unit: str = "km2",
    interpolation: str = "bilinear",
) -> tuple[bytes, str]:
    """密度图字节：默认（bilinear + per km²）直接复用任务产物，其余按参数重绘。"""
    batch = _get_batch_or_404(db, batch_id)
    if batch.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚未完成，暂无密度图")
    if unit not in {"km2", "cell"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="单位只支持 km2 或 cell")
    if interpolation not in {"bilinear", "nearest"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="插值方式只支持 bilinear 或 nearest"
        )

    if unit == "km2" and interpolation == "bilinear" and batch.image_object_key:
        return minio_storage.get_object(batch.image_object_key), "image/png"

    if not batch.grid_x_count or not batch.grid_y_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="密度图不存在")
    cells = (
        db.execute(
            select(WindLightningDensityCell).where(WindLightningDensityCell.batch_id == batch.id)
        )
        .scalars()
        .all()
    )
    counts = algo.matrix_from_cells(
        [{"cell_i": c.cell_i, "cell_j": c.cell_j, "strike_count": c.strike_count} for c in cells],
        batch.grid_x_count,
        batch.grid_y_count,
    )
    bbox = algo.BoundingBox(
        min_lon=float(batch.bbox_min_lon),
        max_lon=float(batch.bbox_max_lon),
        min_lat=float(batch.bbox_min_lat),
        max_lat=float(batch.bbox_max_lat),
    )
    lon_bins, lat_bins = algo.build_bins(bbox, batch.grid_step_deg)
    png = algo.render_batch_png(
        counts=counts,
        lon_bins=lon_bins,
        lat_bins=lat_bins,
        data_years=batch.data_years or algo.DEFAULT_DATA_YEARS,
        step_deg=batch.grid_step_deg,
        title=batch.batch_name or "Wind Farm",
        unit=unit,
        interpolation=interpolation,
    )
    return png, "image/png"


def _load_export_rows(
    db: Session, batch: WindLightningDensityBatch
) -> tuple[list[WindLightningDensityCell], list[WindLightningDensityTurbine]]:
    cells = (
        db.execute(
            select(WindLightningDensityCell)
            .where(WindLightningDensityCell.batch_id == batch.id)
            .order_by(WindLightningDensityCell.cell_j.asc(), WindLightningDensityCell.cell_i.asc())
        )
        .scalars()
        .all()
    )
    turbines = (
        db.execute(
            select(WindLightningDensityTurbine)
            .where(WindLightningDensityTurbine.batch_id == batch.id)
            .order_by(WindLightningDensityTurbine.seq.asc())
        )
        .scalars()
        .all()
    )
    return list(cells), list(turbines)


def export_excel(db: Session, batch_id: str, *, export_type: str) -> tuple[bytes, str]:
    """Excel 导出：cells / turbines / all（all 含概览 + 网格 + 风机）。"""
    if export_type not in {"cells", "turbines", "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="导出类型只支持 cells/turbines/all"
        )
    batch = _get_batch_or_404(db, batch_id)
    cells, turbines = _load_export_rows(db, batch)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise HTTPException(status_code=500, detail="服务端缺少 openpyxl，无法导出 Excel") from exc

    workbook = Workbook()
    workbook.remove(workbook.active)

    def add_sheet(title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        sheet = workbook.create_sheet(title=title)
        sheet.append(list(headers))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        for row in rows:
            sheet.append(list(row))
        for column in sheet.columns:
            width = max(len(str(item.value or "")) for item in column) + 4
            sheet.column_dimensions[column[0].column_letter].width = min(max(width, 10), 40)
        sheet.freeze_panes = "A2"

    if export_type in {"all"}:
        add_sheet(
            "概览",
            ["项目", "值"],
            [
                ["批次名称", batch.batch_name],
                ["风电场", batch.wind_farm_name or "-"],
                ["批次 ID", batch.id],
                ["风机数", batch.turbine_count],
                ["雷电记录总数", batch.total_records],
                ["范围内落雷数", batch.valid_records],
                ["跳过记录数", batch.skipped_records],
                ["统计年限", batch.data_years],
                ["年限来源", "固定 6 年" if batch.years_source == "fixed" else "自动推断/默认6年"],
                ["网格步长(°)", batch.grid_step_deg],
                ["外扩边距(°)", batch.margin_deg],
                ["网格数", f"{batch.grid_x_count} × {batch.grid_y_count}"],
                ["统计面积(km²)", batch.area_km2],
                ["整体密度(次/(km²·年))", batch.overall_density],
                ["峰值密度(次/(km²·年))", batch.peak_density],
                ["峰值坐标", f"{batch.peak_lon}, {batch.peak_lat}"],
                ["创建时间", batch.create_date.isoformat() if batch.create_date else "-"],
            ],
        )

    if export_type in {"cells", "all"}:
        add_sheet(
            "网格",
            [
                "列号 i",
                "行号 j",
                "中心经度",
                "中心纬度",
                "西边界",
                "东边界",
                "南边界",
                "北边界",
                "落雷次数",
                "密度(次/(格·年))",
                "密度(次/(km²·年))",
                "风机数",
            ],
            [
                [
                    cell.cell_i,
                    cell.cell_j,
                    cell.center_lon,
                    cell.center_lat,
                    cell.min_lon,
                    cell.max_lon,
                    cell.min_lat,
                    cell.max_lat,
                    cell.strike_count,
                    cell.density_per_cell_year,
                    cell.density_per_km2_year,
                    cell.turbine_count,
                ]
                for cell in cells
            ],
        )

    if export_type in {"turbines", "all"}:
        add_sheet(
            "风机",
            ["序号", "风机编号", "经度", "纬度", "网格列号 i", "网格行号 j", "网格密度(次/(km²·年))"],
            [
                [
                    turbine.seq,
                    turbine.turbine_no or "",
                    turbine.lon,
                    turbine.lat,
                    turbine.cell_i,
                    turbine.cell_j,
                    turbine.cell_density,
                ]
                for turbine in turbines
            ],
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    suffix = {"cells": "网格", "turbines": "风机", "all": "全部"}[export_type]
    filename = f"{batch.batch_name or '风电场地闪密度'}-{suffix}.xlsx"
    return buffer.getvalue(), filename


def export_core_files(db: Session, batch_id: str) -> tuple[bytes, str]:
    """导出核心程序所需的 ``file_3.txt`` + ``file_4.txt``（zip，UTF-8 无 BOM，\\n 行尾）。"""
    batch = _get_batch_or_404(db, batch_id)
    if batch.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚未完成，无法导出核心程序文件")
    turbines = (
        db.execute(
            select(WindLightningDensityTurbine)
            .where(WindLightningDensityTurbine.batch_id == batch.id)
            .order_by(WindLightningDensityTurbine.seq.asc())
        )
        .scalars()
        .all()
    )
    if not turbines:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批次没有风机明细，无法导出")

    core_grid_raw = (batch.stats_json or {}).get("core_grid") or {}
    try:
        grid: dict[str, float | int] = {
            "start_lon": float(core_grid_raw["start_lon"]),
            "start_lat": float(core_grid_raw["start_lat"]),
            "x_count": int(core_grid_raw["x_count"]),
            "y_count": int(core_grid_raw["y_count"]),
            "step_deg": float(core_grid_raw.get("step_deg", batch.grid_step_deg)),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="批次缺少研究区域网格参数，请重算后再导出") from exc

    # 用源文件按研究区域网格重算密度，保证 file_4 与 file_3 的 grid_id 一一对应
    lightning_content = minio_storage.get_object(batch.lightning_object_key)
    lightning = algo.parse_lightning_csv(lightning_content)
    core_density = algo.core_density_matrix(
        lightning.lon,
        lightning.lat,
        grid,
        batch.data_years or algo.DEFAULT_DATA_YEARS,
    )
    file3, file4 = algo.build_core_files(
        [{"lon": t.lon, "lat": t.lat} for t in turbines], grid, core_density
    )
    if len(file3) != len(turbines) or len(file4) != len(turbines):
        raise HTTPException(status_code=409, detail="file_3/file_4 行数与风机数不一致，已中止导出")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file_3.txt", "".join(file3).encode("utf-8"))
        archive.writestr("file_4.txt", "".join(file4).encode("utf-8"))
    filename = f"{batch.batch_name or '风电场地闪密度'}-file_3-file_4.zip"
    return buffer.getvalue(), filename
