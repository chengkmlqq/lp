"""风电场地闪密度统计 —— 业务编排层（数据库 + 对象存储 + 任务派发）。

算法本身在 ``app.services.wind_lightning_density``（纯函数），本模块负责：

- 上传校验与对象存储落地（风机文件 + 雷电 CSV）；
- 批次记录的创建/重算/逻辑删除与列表查询；
- Celery 任务执行体 ``run_batch``（解析 → 统计 → 落库 → 出图）；
- 网格表 / 风机表 / 图片 / Excel 导出（核心程序文件 file_3、file_4 由「风电场数据准备」模块产出）。

与 ``lightning_distribution``（GB/T 40621 地闪密度）完全隔离：不读写其表，
不调用其算法与色标。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence
from uuid import uuid4

import numpy as np
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.file_upload import validate_upload
from ..models.base import utcnow
from ..models.wind_data_prep import WindDataPrepBatch
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
    WindLightningDensityPrepBatchOption,
    WindLightningDensityPrepBatchOptions,
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

# LP-83：统计完成时预生成 4 种图（插值 × 单位），键同时用于 image_variants_json
# 与前端 /image 的 unit/interpolation 组合（"bilinear-km2" 等）。
IMAGE_VARIANT_COMBOS: tuple[tuple[str, str, str], ...] = (
    ("bilinear-km2", "bilinear", "km2"),
    ("bilinear-cell", "bilinear", "cell"),
    ("nearest-km2", "nearest", "km2"),
    ("nearest-cell", "nearest", "cell"),
)
IMAGE_VARIANT_KEYS = tuple(key for key, _, _ in IMAGE_VARIANT_COMBOS)
# ZIP 内文件名：固定顺序 + ASCII，避免不同系统的编码差异。
IMAGE_VARIANT_FILENAMES = {
    "bilinear-km2": "1_bilinear_km2.png",
    "bilinear-cell": "2_bilinear_cell.png",
    "nearest-km2": "3_nearest_km2.png",
    "nearest-cell": "4_nearest_cell.png",
}

# Excel 导出与整包 CSV 共用列头，避免两处列定义漂移。
CELL_EXPORT_HEADERS: tuple[str, ...] = (
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
)
TURBINE_EXPORT_HEADERS: tuple[str, ...] = (
    "序号",
    "风机编号",
    "经度",
    "纬度",
    "网格列号 i",
    "网格行号 j",
    "网格密度(次/(km²·年))",
)


# ---------------------------------------------------------------------------
# 批次名：后端统一生成（前端传来的值只作草稿提示，不信任）
# ---------------------------------------------------------------------------
# 格式：<风电场>_Y<年限><A|F>_G<网格步长>_M<外扩边距>_<MMDD-HHmm>[-序号]
# Y/G/M 为中性字符，中英文界面均无需改词条。
_BATCH_NAME_BASE_MAX = 250  # 预留 -2/-3/... 后缀空间，保证总长 <= 255


def _sanitize_farm_name(raw: str | None, fallback_filename: str) -> str:
    """风电场名：去首尾空白、空格/非法字符替换为 `_`，最多 20 字。

    为空时退化为风机点位文件名主名（去扩展名），再兜底 `未命名风电场`。
    """
    name = (raw or "").strip()
    if not name:
        name = fallback_filename.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        name = name.rsplit(".", 1)[0] if "." in name else name
        name = name.strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned or "未命名风电场")[:20]


def _format_deg(value: float | None, default: float) -> str:
    """把度数格式化为去掉末尾无意义 0 的字符串（0.010 -> 0.01）。"""
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        number = default
    text = f"{number:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def build_batch_name(
    *,
    wind_farm_name: str | None,
    turbine_filename: str,
    years: float | None,
    years_source: str,
    grid_step_deg: float | None,
    margin_deg: float | None,
    now: datetime | None = None,
) -> str:
    """依据校验后的字段生成批次名基名（不含同名序号）。"""
    farm = _sanitize_farm_name(wind_farm_name, turbine_filename)
    if years_source == "fixed" or years is None:
        year_count = 6
    else:
        try:
            year_count = max(1, int(round(float(years))))
        except (TypeError, ValueError):
            year_count = 6
    flag = "F" if years_source == "fixed" else "A"
    stamp = (now or datetime.now()).strftime("%m%d-%H%M")
    return (
        f"{farm}_Y{year_count}{flag}"
        f"_G{_format_deg(grid_step_deg, 0.01)}"
        f"_M{_format_deg(margin_deg, 0.01)}"
        f"_{stamp}"
    )[:_BATCH_NAME_BASE_MAX]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ensure_unique_batch_name(db: Session, base: str) -> str:
    """查表追加 `-2/-3/...` 直到唯一（含逻辑删除行，避免唯一索引冲突）。"""
    base = base[:_BATCH_NAME_BASE_MAX]
    taken = set(
        db.execute(
            select(WindLightningDensityBatch.batch_name).where(
                WindLightningDensityBatch.batch_name.like(_escape_like(base) + "%", escape="\\")
            )
        )
        .scalars()
        .all()
    )
    if base not in taken:
        return base
    serial = 2
    while f"{base}-{serial}" in taken:
        serial += 1
    return f"{base}-{serial}"


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


def _image_object_key(batch_id: str, variant: str | None = None) -> str:
    """图片对象键；variant 为 bilinear-km2 等组合名，默认图不带后缀。"""
    suffix = f"-{variant}" if variant else ""
    return f"wind-lightning-density/{batch_id}/{uuid4().hex}{suffix}.png"


# ---------------------------------------------------------------------------
# 输入来源：上传文件 / 复用「风电场数据准备」批次
# ---------------------------------------------------------------------------
def _prep_files_ready(batch: WindDataPrepBatch) -> bool:
    """数据准备批次是否已具备地闪密度所需的两份源文件（风机点位 + 雷电 CSV）。"""
    return bool(batch.turbine_file_key) and bool(batch.lightning_file_key)


def list_prep_batch_options(db: Session) -> WindLightningDensityPrepBatchOptions:
    """新建时可选的准备批次：已完成、未删除、两份源文件齐全（与风电场计算同口径）。"""
    rows = (
        db.execute(
            select(WindDataPrepBatch)
            .where(
                WindDataPrepBatch.is_deleted.is_(False),
                WindDataPrepBatch.status == "completed",
            )
            .order_by(WindDataPrepBatch.create_date.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    return WindLightningDensityPrepBatchOptions(
        items=[
            WindLightningDensityPrepBatchOption(
                id=row.id,
                name=row.name or "",
                wind_farm_name=row.wind_farm_name,
                turbine_count=row.turbine_count,
                grid_nx=row.grid_nx,
                grid_ny=row.grid_ny,
                create_date=row.create_date,
            )
            for row in rows
            if _prep_files_ready(row)
        ]
    )


def _load_prep_batch_sources(
    db: Session, prep_batch_id: str
) -> tuple[bytes, str, bytes, str]:
    """取回数据准备批次的风机/雷电源文件字节与原始文件名。"""
    batch = db.execute(
        select(WindDataPrepBatch).where(
            WindDataPrepBatch.id == prep_batch_id,
            WindDataPrepBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据准备批次不存在")
    if batch.status != "completed" or not _prep_files_ready(batch):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="仅可选择已完成且风机/雷电文件齐全的数据准备批次",
        )
    try:
        turbine_content = minio_storage.get_object(batch.turbine_file_key)
        lightning_content = minio_storage.get_object(batch.lightning_file_key)
    except minio_storage.MinioStorageError as exc:
        raise algo.WindLightningDensityError(
            f"读取数据准备批次源文件失败：{exc}"
        ) from exc
    if not turbine_content or not lightning_content:
        raise algo.WindLightningDensityError("数据准备批次源文件为空，无法复用")
    return (
        turbine_content,
        batch.turbine_file_name or "file_2.txt",
        lightning_content,
        batch.lightning_file_name or "lightning.csv",
    )


def _resolve_sources(
    db: Session,
    *,
    turbine_file: UploadFile | None,
    lightning_file: UploadFile | None,
    prep_batch_id: str | None,
) -> tuple[bytes, str, bytes, str, str | None]:
    """二选一解析输入来源：引用数据准备批次 / 直接上传两份文件。

    返回 ``(风机字节, 风机文件名, 雷电字节, 雷电文件名, prep_batch_id)``；
    手工上传时 prep_batch_id 为 None（历史路径，保持向后兼容）。
    """
    prep_id = (prep_batch_id or "").strip()
    if prep_id:
        if turbine_file is not None or lightning_file is not None:
            raise algo.WindLightningDensityError(
                "引用数据准备批次时不能再上传风机/雷电文件，请二选一"
            )
        turbine_content, turbine_name, lightning_content, lightning_name = (
            _load_prep_batch_sources(db, prep_id)
        )
        return turbine_content, turbine_name, lightning_content, lightning_name, prep_id
    if turbine_file is None or lightning_file is None:
        raise algo.WindLightningDensityError("请上传风机文件与雷电 CSV，或选择数据准备批次")
    turbine_content, turbine_name = _read_upload(
        turbine_file, purpose="text", allowed_exts={"txt", "csv", "xlsx", "xlsm"}
    )
    lightning_content, lightning_name = _read_upload(
        lightning_file, purpose="text", allowed_exts={"csv", "txt"}
    )
    return turbine_content, turbine_name, lightning_content, lightning_name, None


def _prep_batch_wind_farm_name(db: Session, prep_batch_id: str | None) -> str | None:
    """引用批次且未显式填风电场名时，沿用数据准备批次的风电场名（用于批次名）。"""
    if not prep_batch_id:
        return None
    return db.execute(
        select(WindDataPrepBatch.wind_farm_name).where(
            WindDataPrepBatch.id == prep_batch_id
        )
    ).scalar_one_or_none()


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
        prep_batch_id=batch.prep_batch_id,
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
        image_variants_json=batch.image_variants_json,
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
    db: Session,
    *,
    turbine_file: UploadFile | None = None,
    lightning_file: UploadFile | None = None,
    prep_batch_id: str | None = None,
    grid_step_deg: float,
    margin_deg: float,
    years_source: str,
) -> WindLightningDensityPreviewResponse:
    turbine_content, turbine_name, lightning_content, lightning_name, _ = _resolve_sources(
        db,
        turbine_file=turbine_file,
        lightning_file=lightning_file,
        prep_batch_id=prep_batch_id,
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
    turbine_file: UploadFile | None = None,
    lightning_file: UploadFile | None = None,
    prep_batch_id: str | None = None,
    batch_name: str | None,
    wind_farm_name: str | None,
    notes: str | None,
    grid_step_deg: float,
    margin_deg: float,
    years_source: str,
    actor_user_id: str,
) -> WindLightningDensityImportResponse:
    """校验通过后写入对象存储 + 建批次记录 + 派发 Celery 任务。

    输入可来自上传的两份文件，或引用一个已完成的数据准备批次（二选一）。
    校验失败抛 400，不产生任何批次记录（不落半成品）。
    """
    (
        turbine_content,
        turbine_name,
        lightning_content,
        lightning_name,
        source_prep_batch_id,
    ) = _resolve_sources(
        db,
        turbine_file=turbine_file,
        lightning_file=lightning_file,
        prep_batch_id=prep_batch_id,
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

    # 批次名一律后端生成：前端传来的 batch_name 只作草稿提示，绝不信任。
    final_wind_farm_name = (wind_farm_name or "").strip()
    if not final_wind_farm_name:
        # 引用数据准备批次时沿用其风电场名，避免批次名退化成 file_2 之类的文件名
        final_wind_farm_name = (
            _prep_batch_wind_farm_name(db, source_prep_batch_id) or ""
        ).strip()
    final_wind_farm_name = final_wind_farm_name or None
    base_name = build_batch_name(
        wind_farm_name=final_wind_farm_name,
        turbine_filename=turbine_name,
        years=analysis.years,
        years_source=analysis.years_source,
        grid_step_deg=grid_step_deg,
        margin_deg=margin_deg,
    )
    final_batch_name = ensure_unique_batch_name(db, base_name)

    batch_id = uuid4().hex
    turbine_key = _turbine_object_key(batch_id, turbine_name)
    lightning_key = _lightning_object_key(batch_id, lightning_name)
    minio_storage.put_object(turbine_key, turbine_content, content_type="text/plain")
    minio_storage.put_object(lightning_key, lightning_content, content_type="text/csv")

    now = utcnow()

    def _new_batch(name: str) -> WindLightningDensityBatch:
        return WindLightningDensityBatch(
            id=batch_id,
            batch_name=name,
            wind_farm_name=final_wind_farm_name,
            notes=(notes or "").strip() or None,
            prep_batch_id=source_prep_batch_id,
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

    batch = _new_batch(final_batch_name)
    db.add(batch)
    try:
        db.commit()  # 批次名生成与批次写入同一事务，失败不留半成品
    except IntegrityError:
        # 并发撞名：回滚后重新避让一次（仍失败则向上抛出，不产生半成品）
        db.rollback()
        final_batch_name = ensure_unique_batch_name(db, base_name)
        batch = _new_batch(final_batch_name)
        db.add(batch)
        db.commit()

    write_audit_log(
        db,
        action="wind_lightning_density.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"batch_id={batch.id}",
            f"batch_name={final_batch_name}",
            f"turbine_file={turbine_name}",
            f"lightning_file={lightning_name}",
            f"grid_step_deg={grid_step_deg}",
            f"margin_deg={margin_deg}",
            f"years_source={analysis.years_source}",
            *(
                [f"prep_batch_id={source_prep_batch_id}"]
                if source_prep_batch_id
                else []
            ),
        ),
    )
    db.commit()

    task_id = _dispatch_batch_task(batch.id, actor_user_id)
    batch.task_id = task_id
    batch.status = "processing"
    db.commit()
    return WindLightningDensityImportResponse(
        batch_id=batch.id,
        task_id=task_id,
        status="processing",
        batch_name=final_batch_name,
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
    batch.image_variants_json = None
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
        batch_id=batch.id, task_id=task_id, status="processing", batch_name=batch.batch_name
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

    # LP-83：一次性生成 4 种组合的 PNG 并全部落对象存储；页面切换/刷新直接取图，
    # 不再由 /image 端点实时 render（旧批次缺 variant 时走 lazy 兼容路径）。
    variants: dict[str, str] = {}
    for variant_key, interpolation, unit in IMAGE_VARIANT_COMBOS:
        png = algo.render_batch_png(
            counts=analysis.counts,
            lon_bins=analysis.lon_bins,
            lat_bins=analysis.lat_bins,
            data_years=analysis.years,
            step_deg=batch.grid_step_deg,
            title=batch.batch_name or batch.wind_farm_name or "Wind Farm",
            unit=unit,
            interpolation=interpolation,
        )
        image_key = _image_object_key(batch.id, variant_key)
        minio_storage.put_object(image_key, png, content_type="image/png")
        variants[variant_key] = image_key

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
    batch.image_variants_json = variants
    # 兼容旧批次 / 旧前端：默认图仍指向 bilinear-km2。
    batch.image_object_key = variants["bilinear-km2"]
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
    """密度图字节：优先直接读取统计时预存的图片；旧批次缺 variant 时一次性 lazy 生成。"""
    batch = _get_batch_or_404(db, batch_id)
    if batch.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚未完成，暂无密度图")
    if unit not in {"km2", "cell"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="单位只支持 km2 或 cell")
    if interpolation not in {"bilinear", "nearest"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="插值方式只支持 bilinear 或 nearest"
        )

    variant_key = f"{interpolation}-{unit}"
    variants = dict(batch.image_variants_json or {})
    stored_key = variants.get(variant_key)
    if not stored_key and variant_key == "bilinear-km2" and batch.image_object_key:
        # 旧批次只有默认图，且没有 variants_json：把它当作 bilinear-km2 存量图。
        stored_key = batch.image_object_key
    if stored_key:
        return minio_storage.get_object(stored_key), "image/png"

    # 旧批次缺 variant：一次性生成并存对象存储，后续请求直接命中，绝不重复 render。
    if (
        not batch.grid_x_count
        or not batch.grid_y_count
        or batch.bbox_min_lon is None
        or batch.bbox_max_lon is None
        or batch.bbox_min_lat is None
        or batch.bbox_max_lat is None
    ):
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
    lazy_key = _image_object_key(batch.id, variant_key)
    minio_storage.put_object(lazy_key, png, content_type="image/png")
    variants[variant_key] = lazy_key
    batch.image_variants_json = variants
    db.commit()
    return png, "image/png"


def build_images_zip(db: Session, batch_id: str) -> tuple[bytes, str]:
    """把 4 种密度图打包为 ZIP；每张图走 get_batch_image 的取图/兼容路径。"""
    batch = _get_batch_or_404(db, batch_id)
    if batch.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚未完成，暂无密度图")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for variant_key, interpolation, unit in IMAGE_VARIANT_COMBOS:
            content, _ = get_batch_image(db, batch_id, unit=unit, interpolation=interpolation)
            archive.writestr(IMAGE_VARIANT_FILENAMES[variant_key], content)
    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", batch.batch_name or "wind-lightning-density")
    return buffer.getvalue(), f"{safe_name}-density-images.zip"


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


def _cell_export_rows(cells: Sequence[WindLightningDensityCell]) -> list[list[Any]]:
    return [
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
    ]


def _turbine_export_rows(turbines: Sequence[WindLightningDensityTurbine]) -> list[list[Any]]:
    return [
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
    ]


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
        add_sheet("网格", CELL_EXPORT_HEADERS, _cell_export_rows(cells))

    if export_type in {"turbines", "all"}:
        add_sheet("风机", TURBINE_EXPORT_HEADERS, _turbine_export_rows(turbines))

    buffer = io.BytesIO()
    workbook.save(buffer)
    suffix = {"cells": "网格", "turbines": "风机", "all": "全部"}[export_type]
    filename = f"{batch.batch_name or '风电场地闪密度'}-{suffix}.xlsx"
    return buffer.getvalue(), filename


def _csv_bytes(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    """utf-8-sig：Excel 直接双击打开中文列头不乱码。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(list(headers))
    writer.writerows([list(row) for row in rows])
    return buffer.getvalue().encode("utf-8-sig")


def _archive_input_name(name: str | None, fallback: str) -> str:
    """上传文件名只取文件名本身，避免其中的路径分隔符写进 ZIP。"""
    cleaned = re.sub(r"[\\/]", "_", (name or "").strip())
    return cleaned or fallback


def _load_package_file(key: str | None, label: str) -> bytes:
    """读取对象存储中的原始输入；缺失/失败/空内容都给出明确错误，不打空文件进包。"""
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{label}未归档，无法打包下载",
        )
    try:
        content = minio_storage.get_object(key)
    except minio_storage.MinioStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取{label}失败：{exc}",
        ) from exc
    if not content:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{label}内容为空，无法打包下载",
        )
    return content


def build_package(db: Session, batch_id: str) -> tuple[bytes, str]:
    """整包下载：网格 CSV + 风机 CSV + 两份原始输入文件 + 4 张密度图。"""
    batch = _get_batch_or_404(db, batch_id)
    if batch.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="批次尚未完成，暂无可下载产物")
    cells, turbines = _load_export_rows(db, batch)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("网格密度表.csv", _csv_bytes(CELL_EXPORT_HEADERS, _cell_export_rows(cells)))
        archive.writestr("风机明细.csv", _csv_bytes(TURBINE_EXPORT_HEADERS, _turbine_export_rows(turbines)))
        archive.writestr(
            _archive_input_name(batch.turbine_source_file_name, "turbines.txt"),
            _load_package_file(batch.turbine_object_key, "原始风机文件"),
        )
        archive.writestr(
            _archive_input_name(batch.lightning_source_file_name, "lightning.csv"),
            _load_package_file(batch.lightning_object_key, "原始雷电文件"),
        )
        for variant_key, interpolation, unit in IMAGE_VARIANT_COMBOS:
            content, _ = get_batch_image(db, batch_id, unit=unit, interpolation=interpolation)
            archive.writestr(IMAGE_VARIANT_FILENAMES[variant_key], content)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", batch.batch_name or "wind-lightning-density")
    return buffer.getvalue(), f"{safe_name}-package.zip"
