"""风电场数据准备 —— 业务编排层（数据库 + 对象存储 + 任务派发）。

纯算法在 ``app.services.wind_grid`` / ``app.services.wind_data_prep``，本模块负责
上传校验、批次 CRUD、Celery 任务体、五文件下载/预览、打包与校验报告导出。

与 LP-32（风电场地闪密度统计）完全隔离：不读写其表，接口与页面互不复用。
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.file_upload import validate_upload
from ..models.base import utcnow
from ..models.wind_data_prep import WindDataPrepBatch, WindDataPrepTurbine
from ..schemas.wind_data_prep import (
    WindDataPrepBatchDetail,
    WindDataPrepBatchListResponse,
    WindDataPrepBatchSummary,
    WindDataPrepImportResponse,
    WindDataPrepPreviewResponse,
    WindDataPrepTurbineListResponse,
    WindDataPrepTurbineRow,
)
from ..services import minio_storage
from ..services import wind_data_prep as prep
from ..services import wind_grid as wg
from ..services.audit_service import compose_audit_detail, write_audit_log

WIND_DATA_PREP_TOPIC = "admin.wind-data-prep"
TASK_NAME = "app.tasks.wind_data_prep_tasks.run_wind_data_prep_job"
API_PREFIX = "/api/v1/wind-data-prep"

FILE_ALIASES = {
    "file1": "file_1.txt",
    "file2": "file_2.txt",
    "file3": "file_3.txt",
    "file4": "file_4.txt",
    "p0abc": "P0.abc",
}
FILE_LABELS = {
    "file_1.txt": "file_1.txt（区域参数）",
    "file_2.txt": "file_2.txt（风机清单）",
    "file_3.txt": "file_3.txt（网格编号）",
    "file_4.txt": "file_4.txt（落雷次数 Nl）",
    "P0.abc": "P0.abc（地形高程）",
}
FILE_KEY_FIELDS = {
    "file_1.txt": "file1_key",
    "file_2.txt": "file2_key",
    "file_3.txt": "file3_key",
    "file_4.txt": "file4_key",
    "P0.abc": "p0abc_key",
}


# ---------------------------------------------------------------------------
# 输入校验与分析
# ---------------------------------------------------------------------------
def build_params(
    *,
    start_lon: float,
    start_lat: float,
    grid_nx: int,
    grid_ny: int,
    risk_base_s: float,
    grid_step_deg: float = wg.DEFAULT_DDEG,
    terrain_mode: str = "zero",
    wind_farm_name: str = "",
    remark: str = "",
) -> prep.PrepParams:
    if terrain_mode not in {"zero", "tif"}:
        raise wg.WindGridError("地形模式只支持 zero（零高程）或 tif")
    return prep.PrepParams(
        start_lon=float(start_lon),
        start_lat=float(start_lat),
        nx=int(grid_nx),
        ny=int(grid_ny),
        risk_base_s=float(risk_base_s),
        ddeg=float(grid_step_deg),
        terrain_mode=terrain_mode,
        wind_farm_name=(wind_farm_name or "").strip(),
        remark=(remark or "").strip(),
    )


def analyze_inputs(
    *,
    turbine_content: bytes,
    turbine_filename: str,
    lightning_content: bytes,
    lightning_filename: str,
    tif_content: bytes | None,
    tif_filename: str | None,
    params: prep.PrepParams,
) -> prep.PrepResult:
    return prep.prepare_data(
        params,
        turbine_content=turbine_content,
        turbine_filename=turbine_filename,
        lightning_content=lightning_content,
        lightning_filename=lightning_filename,
        tif_content=tif_content,
    )


def _read_upload(file: UploadFile, *, purpose: str, allowed_exts: set[str]) -> tuple[bytes, str]:
    validate_upload(file, purpose=purpose, allowed_exts=allowed_exts)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    filename = str(file.filename or "upload").strip() or "upload"
    return content, filename


def _turbine_key(batch_id: str, filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    return f"wind-data-prep/{batch_id}/turbines.{suffix}"


def _lightning_key(batch_id: str, filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
    return f"wind-data-prep/{batch_id}/lightning.{suffix}"


def _terrain_key(batch_id: str) -> str:
    return f"wind-data-prep/{batch_id}/terrain.tif"


def _output_key(batch_id: str, name: str) -> str:
    return f"wind-data-prep/{batch_id}/out/{name}"


def _package_key(batch_id: str) -> str:
    return f"wind-data-prep/{batch_id}/package.zip"


# ---------------------------------------------------------------------------
# 查询 / 序列化
# ---------------------------------------------------------------------------
def _get_batch_or_404(db: Session, batch_id: str) -> WindDataPrepBatch:
    batch = db.execute(
        select(WindDataPrepBatch).where(
            WindDataPrepBatch.id == batch_id,
            WindDataPrepBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="风电场数据准备批次不存在")
    return batch


def _files_ready(batch: WindDataPrepBatch) -> int:
    return sum(
        1
        for name in prep.FILE_NAMES
        if getattr(batch, FILE_KEY_FIELDS[name], None)
    )


def _summary(batch: WindDataPrepBatch) -> WindDataPrepBatchSummary:
    return WindDataPrepBatchSummary(
        id=batch.id,
        name=batch.name or "",
        wind_farm_name=batch.wind_farm_name,
        remark=batch.remark,
        start_lon=batch.start_lon,
        start_lat=batch.start_lat,
        grid_nx=batch.grid_nx,
        grid_ny=batch.grid_ny,
        grid_step_deg=batch.grid_step_deg,
        risk_base_s=batch.risk_base_s,
        data_years=batch.data_years,
        terrain_mode=batch.terrain_mode,
        turbine_count=batch.turbine_count,
        lightning_total=batch.lightning_total,
        lightning_valid=batch.lightning_valid,
        lightning_in_scope=batch.lightning_in_scope,
        status=batch.status,
        stage=batch.stage,
        progress=batch.progress,
        task_id=batch.task_id,
        error_message=batch.error_message,
        files_ready=_files_ready(batch),
        has_report=bool(batch.report_json),
        create_date=batch.create_date,
        update_date=batch.update_date,
        create_user=batch.create_user,
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
) -> WindDataPrepBatchListResponse:
    filters: list[Any] = [WindDataPrepBatch.is_deleted.is_(False)]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(
                WindDataPrepBatch.name.ilike(pattern),
                WindDataPrepBatch.wind_farm_name.ilike(pattern),
            )
        )
    if status_filter:
        filters.append(WindDataPrepBatch.status == status_filter)
    if date_from:
        filters.append(WindDataPrepBatch.create_date >= date_from)
    if date_to:
        filters.append(WindDataPrepBatch.create_date <= date_to)
    total = db.execute(
        select(func.count()).select_from(WindDataPrepBatch).where(*filters)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindDataPrepBatch)
            .where(*filters)
            .order_by(WindDataPrepBatch.create_date.desc(), WindDataPrepBatch.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindDataPrepBatchListResponse(total=int(total), items=[_summary(row) for row in rows])


def get_batch_detail(db: Session, batch_id: str) -> WindDataPrepBatchDetail:
    batch = _get_batch_or_404(db, batch_id)
    p0abc_header: dict[str, Any] = {}
    if batch.p0abc_key:
        try:
            p0abc_header = prep.validate_p0abc(
                minio_storage.get_object(batch.p0abc_key),
                nx=batch.grid_nx,
                ny=batch.grid_ny,
            )
        except wg.WindGridError:
            p0abc_header = {}
    return WindDataPrepBatchDetail(
        **_summary(batch).model_dump(),
        turbine_file_name=batch.turbine_file_name,
        lightning_file_name=batch.lightning_file_name,
        terrain_file_name=batch.terrain_file_name,
        nonzero_cell_count=batch.nonzero_cell_count,
        zero_nl_turbine_count=batch.zero_nl_turbine_count,
        nl_max=batch.nl_max,
        nl_min=batch.nl_min,
        nl_avg=batch.nl_avg,
        report_json=batch.report_json,
        stats_json=batch.stats_json,
        p0abc_header=p0abc_header,
    )


def list_turbines(
    db: Session,
    batch_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> WindDataPrepTurbineListResponse:
    batch = _get_batch_or_404(db, batch_id)
    total = db.execute(
        select(func.count())
        .select_from(WindDataPrepTurbine)
        .where(WindDataPrepTurbine.batch_id == batch.id)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindDataPrepTurbine)
            .where(WindDataPrepTurbine.batch_id == batch.id)
            .order_by(WindDataPrepTurbine.seq.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindDataPrepTurbineListResponse(
        total=int(total),
        items=[
            WindDataPrepTurbineRow(
                seq=row.seq,
                turbine_no=row.turbine_no,
                lon=row.lon,
                lat=row.lat,
                cell_i=row.cell_i,
                cell_j=row.cell_j,
                grid_id=row.grid_id,
                flash_count=row.flash_count,
                flash_count_east=row.flash_count_east,
                nl=row.nl,
                density_per_km2_year=row.density_per_km2_year,
                height=row.height,
                blade=row.blade,
                motion=row.motion,
                circuit=row.circuit,
            )
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# 预览 / 新建 / 重算 / 删除
# ---------------------------------------------------------------------------
def preview_batch(
    *,
    turbine_file: UploadFile,
    lightning_file: UploadFile,
    terrain_file: UploadFile | None,
    params: prep.PrepParams,
) -> WindDataPrepPreviewResponse:
    turbine_content, turbine_name = _read_upload(
        turbine_file, purpose="text", allowed_exts={"txt", "csv", "xlsx", "xlsm"}
    )
    lightning_content, lightning_name = _read_upload(
        lightning_file, purpose="text", allowed_exts={"csv", "txt"}
    )
    tif_content: bytes | None = None
    if params.terrain_mode == "tif":
        if terrain_file is None:
            raise wg.WindGridError("已选择 tif 地形，请上传 EPSG:4326、0.01° 分辨率的 tif 文件")
        tif_content, _ = _read_upload(terrain_file, purpose="raster", allowed_exts={"tif", "tiff"})
    result = analyze_inputs(
        turbine_content=turbine_content,
        turbine_filename=turbine_name,
        lightning_content=lightning_content,
        lightning_filename=lightning_name,
        tif_content=tif_content,
        tif_filename=(terrain_file.filename if terrain_file else None),
        params=params,
    )
    stats = result.stats
    return WindDataPrepPreviewResponse(
        turbine_count=stats["turbine_count"],
        lightning_total=stats["lightning_total"],
        lightning_valid=stats["lightning_valid"],
        lightning_in_scope=stats["lightning_in_scope"],
        nonzero_cell_count=stats["nonzero_cell_count"],
        nl_max=stats["nl_max"],
        nl_min=stats["nl_min"],
        nl_avg=stats["nl_avg"],
        time_span=stats["time_span"],
        type_distribution=stats["type_distribution"],
        report=result.report,
        warnings=result.warnings,
        p0abc_header=prep.validate_p0abc(
            result.files["P0.abc"], nx=params.nx, ny=params.ny
        ),
        file_lines={
            "file_1.txt": len(result.files["file_1.txt"].decode("utf-8").splitlines()),
            "file_2.txt": stats["turbine_count"],
            "file_3.txt": stats["turbine_count"],
            "file_4.txt": stats["turbine_count"],
        },
        file_sizes={name: len(content) for name, content in result.files.items()},
    )


def create_batch(
    db: Session,
    *,
    turbine_file: UploadFile,
    lightning_file: UploadFile,
    terrain_file: UploadFile | None,
    params: prep.PrepParams,
    name: str | None,
    actor_user_id: str,
) -> WindDataPrepImportResponse:
    """先完成全部校验（失败不落任何记录），再存源文件、建批次、派发任务。"""
    turbine_content, turbine_name = _read_upload(
        turbine_file, purpose="text", allowed_exts={"txt", "csv", "xlsx", "xlsm"}
    )
    lightning_content, lightning_name = _read_upload(
        lightning_file, purpose="text", allowed_exts={"csv", "txt"}
    )
    tif_content: bytes | None = None
    terrain_name: str | None = None
    if params.terrain_mode == "tif":
        if terrain_file is None:
            raise wg.WindGridError("已选择 tif 地形，请上传 EPSG:4326、0.01° 分辨率的 tif 文件")
        tif_content, terrain_name = _read_upload(
            terrain_file, purpose="raster", allowed_exts={"tif", "tiff"}
        )

    result = analyze_inputs(
        turbine_content=turbine_content,
        turbine_filename=turbine_name,
        lightning_content=lightning_content,
        lightning_filename=lightning_name,
        tif_content=tif_content,
        tif_filename=terrain_name,
        params=params,
    )

    batch_id = uuid4().hex
    turbine_key = _turbine_key(batch_id, turbine_name)
    lightning_key = _lightning_key(batch_id, lightning_name)
    minio_storage.put_object(turbine_key, turbine_content, content_type="text/plain")
    minio_storage.put_object(lightning_key, lightning_content, content_type="text/csv")
    terrain_key: str | None = None
    if tif_content is not None:
        terrain_key = _terrain_key(batch_id)
        minio_storage.put_object(terrain_key, tif_content, content_type="image/tiff")

    stats = result.stats
    now = utcnow()
    batch = WindDataPrepBatch(
        id=batch_id,
        name=(name or "").strip() or params.wind_farm_name or turbine_name,
        wind_farm_name=params.wind_farm_name or None,
        remark=params.remark or None,
        start_lon=params.start_lon,
        start_lat=params.start_lat,
        grid_nx=params.nx,
        grid_ny=params.ny,
        grid_step_deg=params.ddeg,
        risk_base_s=params.risk_base_s,
        data_years=wg.DATA_YEARS,
        terrain_mode=params.terrain_mode,
        turbine_file_key=turbine_key,
        lightning_file_key=lightning_key,
        terrain_file_key=terrain_key,
        turbine_file_name=turbine_name,
        lightning_file_name=lightning_name,
        terrain_file_name=terrain_name,
        turbine_count=stats["turbine_count"],
        lightning_total=stats["lightning_total"],
        lightning_valid=stats["lightning_valid"],
        lightning_in_scope=stats["lightning_in_scope"],
        nonzero_cell_count=stats["nonzero_cell_count"],
        zero_nl_turbine_count=stats["zero_nl_turbine_count"],
        nl_max=stats["nl_max"],
        nl_min=stats["nl_min"],
        nl_avg=stats["nl_avg"],
        status="pending",
        stage="parsing",
        progress=0,
        report_json=result.report,
        stats_json=stats,
        create_user=actor_user_id,
        create_date=now,
        update_date=now,
    )
    db.add(batch)
    db.commit()
    write_audit_log(
        db,
        action="wind_data_prep.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"batch_id={batch.id}",
            f"name={batch.name}",
            f"turbine_file={turbine_name}",
            f"lightning_file={lightning_name}",
            f"grid={params.nx}x{params.ny}",
            f"terrain_mode={params.terrain_mode}",
        ),
    )
    db.commit()

    task_id = _dispatch_batch_task(batch.id, actor_user_id)
    batch.task_id = task_id
    batch.status = "processing"
    db.commit()
    return WindDataPrepImportResponse(batch_id=batch.id, task_id=task_id, status="processing")


def _dispatch_batch_task(batch_id: str, actor_user_id: str | None) -> str | None:
    from ..core.celery_app import celery_app as _celery_app

    try:
        task = _celery_app.send_task(
            TASK_NAME,
            kwargs=dict(batch_id=batch_id, actor_user_id=actor_user_id),
            queue="celery",
        )
        return str(task.id)
    except Exception:  # noqa: BLE001 - broker 不可用时不阻塞接口
        return None


def recompute_batch(
    db: Session,
    batch_id: str,
    *,
    actor_user_id: str,
    param_overrides: dict[str, Any] | None = None,
) -> WindDataPrepImportResponse:
    """用原文件 + 可选新参数重跑（清空旧明细与产物后整批重建）。"""
    batch = _get_batch_or_404(db, batch_id)
    if param_overrides:
        for key in ("start_lon", "start_lat", "grid_nx", "grid_ny", "risk_base_s", "grid_step_deg", "terrain_mode"):
            value = param_overrides.get(key)
            if value is None or value == "":
                continue
            column = {
                "grid_nx": "grid_nx",
                "grid_ny": "grid_ny",
            }.get(key, key)
            setattr(batch, column, value)
        if batch.terrain_mode not in {"zero", "tif"}:
            raise wg.WindGridError("地形模式只支持 zero 或 tif")
    db.execute(
        WindDataPrepTurbine.__table__.delete().where(WindDataPrepTurbine.batch_id == batch.id)
    )
    for name in prep.FILE_NAMES:
        setattr(batch, FILE_KEY_FIELDS[name], None)
    batch.package_key = None
    batch.status = "pending"
    batch.stage = "parsing"
    batch.progress = 0
    batch.error_message = None
    batch.update_user = actor_user_id
    batch.update_date = utcnow()
    db.commit()
    write_audit_log(
        db,
        action="wind_data_prep.recompute",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"batch_id={batch.id}", f"name={batch.name}"),
    )
    db.commit()

    task_id = _dispatch_batch_task(batch.id, actor_user_id)
    batch.task_id = task_id
    batch.status = "processing"
    db.commit()
    return WindDataPrepImportResponse(batch_id=batch.id, task_id=task_id, status="processing")


def delete_batch(db: Session, batch_id: str, *, actor_user_id: str) -> None:
    batch = _get_batch_or_404(db, batch_id)
    batch.is_deleted = True
    batch.update_user = actor_user_id
    batch.update_date = utcnow()
    write_audit_log(
        db,
        action="wind_data_prep.delete",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"batch_id={batch.id}", f"name={batch.name}"),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 任务执行体
# ---------------------------------------------------------------------------
def _log_checks(
    checks: list[dict[str, Any]] | None, on_log: Callable[[str], None] | None
) -> None:
    """把校验报告逐项写入任务日志（仅记录，不影响校验/阻断逻辑）。"""
    if not on_log or not checks:
        return
    for item in checks:
        if not item.get("passed"):
            tag = "错误"
        elif item.get("level") in {"warning", "info"} or item.get("code") in {
            "notice",
            "lightning_type",
        }:
            # 数据准备的 passed 项 level 统一为 ok，提示类靠 code 识别
            tag = "警告"
        else:
            tag = "通过"
        on_log(
            f"[校验] [{tag}] {item.get('label', '')} — {item.get('message', '')}"
        )


def run_batch(
    db: Session,
    batch_id: str,
    *,
    actor_user_id: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Celery 任务体：重新解析源文件 → 校验 → 生成五文件 → 落库。"""
    batch = db.execute(
        select(WindDataPrepBatch).where(WindDataPrepBatch.id == batch_id)
    ).scalar_one_or_none()
    if not batch:
        raise wg.WindGridError(f"批次不存在（batch_id={batch_id}）")

    batch.status = "processing"
    batch.stage = "parsing"
    batch.progress = 5
    batch.error_message = None
    db.commit()

    turbine_content = minio_storage.get_object(batch.turbine_file_key)
    lightning_content = minio_storage.get_object(batch.lightning_file_key)
    tif_content = (
        minio_storage.get_object(batch.terrain_file_key) if batch.terrain_file_key else None
    )
    params = build_params(
        start_lon=batch.start_lon,
        start_lat=batch.start_lat,
        grid_nx=batch.grid_nx,
        grid_ny=batch.grid_ny,
        risk_base_s=batch.risk_base_s,
        grid_step_deg=batch.grid_step_deg,
        terrain_mode=batch.terrain_mode,
        wind_farm_name=batch.wind_farm_name or "",
        remark=batch.remark or "",
    )
    try:
        result = analyze_inputs(
            turbine_content=turbine_content,
            turbine_filename=batch.turbine_file_name or "turbines.txt",
            lightning_content=lightning_content,
            lightning_filename=batch.lightning_file_name or "lightning.csv",
            tif_content=tif_content,
            tif_filename=batch.terrain_file_name,
            params=params,
        )
    except wg.WindGridError as exc:
        # 阻断前把已生成的校验项（含导致阻断的错误项）逐项写入任务日志
        _log_checks(getattr(exc, "checks", None), on_log)
        raise
    _log_checks(result.report.get("checks"), on_log)

    batch.stage = "serializing"
    batch.progress = 55
    db.commit()

    # 产物统一落对象存储，并打包 zip
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in result.files.items():
            key = _output_key(batch.id, name)
            minio_storage.put_object(key, content, content_type="application/octet-stream")
            setattr(batch, FILE_KEY_FIELDS[name], key)
            archive.writestr(name, content)
    package_content = buffer.getvalue()
    package_key = _package_key(batch.id)
    minio_storage.put_object(package_key, package_content, content_type="application/zip")
    batch.package_key = package_key

    stats = result.stats
    batch.stage = "saving"
    batch.progress = 80
    batch.turbine_count = stats["turbine_count"]
    batch.lightning_total = stats["lightning_total"]
    batch.lightning_valid = stats["lightning_valid"]
    batch.lightning_in_scope = stats["lightning_in_scope"]
    batch.nonzero_cell_count = stats["nonzero_cell_count"]
    batch.zero_nl_turbine_count = stats["zero_nl_turbine_count"]
    batch.nl_max = stats["nl_max"]
    batch.nl_min = stats["nl_min"]
    batch.nl_avg = stats["nl_avg"]
    batch.report_json = result.report
    batch.stats_json = stats

    # 重算场景：整批替换风机明细（同一事务内完成，避免半成品）
    db.execute(
        WindDataPrepTurbine.__table__.delete().where(WindDataPrepTurbine.batch_id == batch.id)
    )
    turbine_rows = [
        {
            "id": uuid4().hex,
            "batch_id": batch.id,
            "seq": turbine["seq"],
            "turbine_no": turbine["turbine_no"],
            "lon": turbine["lon"],
            "lat": turbine["lat"],
            "cell_i": turbine["cell_i"],
            "cell_j": turbine["cell_j"],
            "grid_id": turbine["grid_id"],
            "flash_count": turbine["flash_count"],
            "flash_count_east": turbine["flash_count_east"],
            "nl": turbine["nl"],
            "density_per_km2_year": turbine["density_per_km2_year"],
            "height": turbine["height"],
            "blade": turbine["blade"],
            "motion": turbine["motion"],
            "circuit": turbine["circuit"],
            "input_elev": turbine["input_elev"],
        }
        for turbine in result.turbines
    ]
    if turbine_rows:
        db.execute(WindDataPrepTurbine.__table__.insert(), turbine_rows)

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
        "lightning_in_scope": batch.lightning_in_scope,
        "files_ready": _files_ready(batch),
    }


def mark_batch_failed(db: Session, batch_id: str, error_message: str) -> None:
    batch = db.execute(
        select(WindDataPrepBatch).where(WindDataPrepBatch.id == batch_id)
    ).scalar_one_or_none()
    if not batch:
        return
    batch.status = "failed"
    batch.stage = "failed"
    batch.error_message = error_message[:2000]
    batch.update_date = utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# 文件下载 / 预览 / 报告
# ---------------------------------------------------------------------------
def _resolve_name(name: str) -> str:
    normalized = name.strip().lower()
    target = FILE_ALIASES.get(normalized)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名只支持 file1/file2/file3/file4/p0abc",
        )
    return target


def get_file(
    db: Session, batch_id: str, name: str, *, preview: bool = False
) -> tuple[bytes, str, str]:
    batch = _get_batch_or_404(db, batch_id)
    target = _resolve_name(name)
    key = getattr(batch, FILE_KEY_FIELDS[target], None)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="产物尚未生成，请等待任务完成"
        )
    content = minio_storage.get_object(key)
    if preview and target == "P0.abc":
        header = prep.validate_p0abc(content, nx=batch.grid_nx, ny=batch.grid_ny)
        import json

        return (
            json.dumps(header, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            "p0abc-header.json",
        )
    media_type = "text/plain; charset=utf-8" if target != "P0.abc" else "application/octet-stream"
    return content, media_type, target


def get_package(db: Session, batch_id: str) -> tuple[bytes, str]:
    batch = _get_batch_or_404(db, batch_id)
    if not batch.package_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="打包文件尚未生成")
    return (
        minio_storage.get_object(batch.package_key),
        f"{batch.name or 'wind-data-prep'}-five-files.zip",
    )


def get_report(db: Session, batch_id: str, *, format: str = "json") -> tuple[bytes, str, str]:
    batch = _get_batch_or_404(db, batch_id)
    if format not in {"json", "excel"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告格式只支持 json 或 excel")
    report = batch.report_json or {}
    if format == "json":
        import json

        return (
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            f"{batch.name or 'wind-data-prep'}-report.json",
        )
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise HTTPException(status_code=500, detail="服务端缺少 openpyxl，无法导出 Excel") from exc

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "校验报告"
    sheet.append(["状态", "级别", "编码", "检查项", "是否通过", "说明"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for item in report.get("checks", []):
        sheet.append(
            [
                report.get("status", ""),
                item.get("level", ""),
                item.get("code", ""),
                item.get("label", ""),
                "是" if item.get("passed") else "否",
                item.get("message", ""),
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["F"].width = 90
    buffer = io.BytesIO()
    workbook.save(buffer)
    return (
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"{batch.name or 'wind-data-prep'}-report.xlsx",
    )
