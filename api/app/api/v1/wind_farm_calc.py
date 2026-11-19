"""风电场计算 API（前缀 ``/api/v1/wind-farm-calc``）。

输入只来自 LP-33 已完成的「风电场数据准备」批次，不开放用户直接上传 file_1~4 / P0.abc。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.wind_farm_calc import (
    WindFarmCalcCancelResponse,
    WindFarmCalcCreateRequest,
    WindFarmCalcCreateResponse,
    WindFarmCalcEngineInfo,
    WindFarmCalcJobDetail,
    WindFarmCalcJobListResponse,
    WindFarmCalcLogResponse,
    WindFarmCalcPrepBatchOptions,
    WindFarmCalcResultListResponse,
)
from ...services import wind_farm_calc_service as service
from ...services.wind_farm_calc import WindFarmCalcError

router = APIRouter(
    prefix="/wind-farm-calc",
    tags=["wind-farm-calc"],
    dependencies=[Depends(require_enabled_menu_route)],
)

_READ_PERMISSIONS = ("wind_farm_calc.read", "wind_farm_calc.manage")
_MANAGE_PERMISSION = "wind_farm_calc.manage"


def _attachment_headers(filename: str) -> dict[str, str]:
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
        )
    }


# ---------------------------------------------------------------------------
# 静态路径（必须在 /{job_id} 之前注册）
# ---------------------------------------------------------------------------
@router.get("/prep-batches", response_model=WindFarmCalcPrepBatchOptions)
def list_available_prep_batches(
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindFarmCalcPrepBatchOptions:
    return service.list_prep_batch_options(db)


@router.get("/engine", response_model=WindFarmCalcEngineInfo)
def get_engine_info(
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
) -> WindFarmCalcEngineInfo:
    return service.get_engine_info()


@router.post("", response_model=WindFarmCalcCreateResponse)
def create_wind_farm_calc_job(
    payload: WindFarmCalcCreateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindFarmCalcCreateResponse:
    try:
        return service.create_job(
            db,
            prep_batch_id=payload.prep_batch_id,
            name=payload.name,
            actor_user_id=current_user.user.id,
        )
    except WindFarmCalcError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=WindFarmCalcJobListResponse)
def list_wind_farm_calc_jobs(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    prep_batch_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindFarmCalcJobListResponse:
    return service.list_jobs(
        db,
        keyword=keyword,
        status_filter=status_filter,
        prep_batch_id=prep_batch_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# 单个任务
# ---------------------------------------------------------------------------
@router.get("/{job_id}", response_model=WindFarmCalcJobDetail)
def get_wind_farm_calc_job(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindFarmCalcJobDetail:
    return service.get_job_detail(db, job_id)


@router.get("/{job_id}/results", response_model=WindFarmCalcResultListResponse)
def list_wind_farm_calc_results(
    job_id: str,
    risk_level: int | None = Query(default=None, ge=1, le=4),
    suggestion_code: int | None = Query(default=None, ge=1, le=4),
    sort_by: str = Query(default="seq"),
    order: str = Query(default="asc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindFarmCalcResultListResponse:
    return service.list_results(
        db,
        job_id,
        risk_level=risk_level,
        suggestion_code=suggestion_code,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}/log", response_model=WindFarmCalcLogResponse)
def get_wind_farm_calc_log(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindFarmCalcLogResponse:
    return service.get_log_info(db, job_id)


@router.post("/{job_id}/cancel", response_model=WindFarmCalcCancelResponse)
def cancel_wind_farm_calc_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindFarmCalcCancelResponse:
    return service.cancel_job(db, job_id, actor_user_id=current_user.user.id)


@router.get("/{job_id}/export")
def export_wind_farm_calc_results(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, media_type, filename = service.export_results(db, job_id)
    return Response(content=content, media_type=media_type, headers=_attachment_headers(filename))


@router.get("/{job_id}/output")
def get_wind_farm_calc_output(
    job_id: str,
    preview: bool = Query(default=False, description="在线预览 GBK 原文（转为 UTF-8 文本）"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    job = service.get_job_detail(db, job_id)
    if not job.output_object_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="原始 file_out.txt 尚未生成")
    from ...services import minio_storage
    from ...services.wind_farm_calc import decode_file_out

    raw = minio_storage.get_object(job.output_object_key)
    if preview:
        return Response(content=decode_file_out(raw).encode("utf-8"), media_type="text/plain; charset=utf-8")
    return Response(
        content=raw,
        media_type="text/plain; charset=gbk",
        headers=_attachment_headers("file_out.txt"),
    )


@router.delete("/{job_id}")
def delete_wind_farm_calc_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service.delete_job(db, job_id, actor_user_id=current_user.user.id)
    return {"status": "deleted", "job_id": job_id}
