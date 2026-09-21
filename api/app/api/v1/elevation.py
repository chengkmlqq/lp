from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...core.file_upload import (
    resolve_temp_upload,
    save_temp_upload,
    validate_upload,
)
from ...schemas.elevation import (
    ElevationApplyJobCreateRequest,
    ElevationApplyJobCreateResponse,
    ElevationApplyJobListResponse,
    ElevationApplyJobSummary,
    ElevationApplyJobTowerListResponse,
    ElevationBackfillCoverageResponse,
    ElevationDatasetListResponse,
    ElevationLinkedLineListResponse,
    ElevationTerrainLayerResponse,
    ElevationFileRecordAnalyzeResponse,
    ElevationFileRecordCreateRequest,
    ElevationFileRecordListResponse,
    ElevationFileRecordPreviewResponse,
    ElevationFileRecordSummary,
    ElevationFileRecordTaskStatusResponse,
    ElevationFileRecordTerrainBuildResponse,
    ElevationFileRecordTerrainTaskStatusResponse,
    ElevationFileRecordUpdateRequest,
    ElevationFileRecordUploadResponse,
    ElevationTempUploadResponse,
)
from ...services.elevation_service import (
    create_apply_job,
    get_job_by_id,
    get_linked_lines_for_file_record,
    list_job_towers,
    list_jobs,
    serialize_job,
    get_file_record_analysis_task_status,
    get_file_record_terrain_layer,
    get_file_record_terrain_task_status,
    get_file_record_terrain_tile,
    preview_backfill_coverage,
)
from ...services.elevation_file_record_service import (
    create_file_record_from_upload,
    delete_file_record,
    get_file_record_by_id,
    list_elevation_datasets,
    list_file_records,
    preview_file_record,
    queue_file_record_analysis,
    queue_file_record_terrain_build,
    serialize_file_record,
    update_file_record,
)

router = APIRouter(prefix="/elevation", tags=["elevation"], dependencies=[Depends(require_enabled_menu_route)])


# ============================================================================
# New File Record API (扁平化高程文件管理)
# ============================================================================

@router.get("/records", response_model=ElevationFileRecordListResponse)
def get_elevation_file_records(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordListResponse:
    return list_file_records(
        db,
        keyword=keyword,
        status_filter=status_filter,
    )


@router.post("/upload-temp", response_model=ElevationTempUploadResponse)
def upload_elevation_temp_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
) -> ElevationTempUploadResponse:
    """选择文件后立即上传到临时目录，返回 temp_file_id 供确认提交时引用。

    与地闪密度导入统一的两段式交互：选择文件后先上传到 MinIO 临时区并展示
    上传进度，表单确认提交时携带 temp_file_id，服务端从临时目录取文件再入库；
    临时文件消费后删除，或由定时清理任务兜底清理。
    """
    validate_upload(file, max_mb=999999, allowed_exts={"tif", "tiff", "zip"}, allowed_exts_label="tif/tiff/zip")
    temp_file_id, file_name = save_temp_upload(file, current_user.user.id)
    return ElevationTempUploadResponse(temp_file_id=temp_file_id, file_name=file_name)


@router.post("/records", response_model=ElevationFileRecordUploadResponse)
def create_elevation_file_record(
    file: UploadFile | None = File(default=None),
    temp_file_id: str | None = Form(default=None),
    source: str | None = Form(default=None),
    mount_code: str | None = Form(default=None),
    resolution_m: float | None = Form(default=None),
    notes: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordUploadResponse:
    validate_upload(file, max_mb=999999, allowed_exts={"tif", "tiff", "zip"}, allowed_exts_label="tif/tiff/zip")
    payload = ElevationFileRecordCreateRequest(
        source=source,
        mount_code=mount_code,
        resolution_m=resolution_m,
        notes=notes,
    )
    if temp_file_id:
        content, filename = resolve_temp_upload(temp_file_id, current_user.user.id)
        return create_file_record_from_upload(
            db,
            None,
            payload,
            actor=current_user.user,
            content=content,
            filename=filename,
        )
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少文件，请提供 file 或 temp_file_id",
        )
    return create_file_record_from_upload(db, file, payload, actor=current_user.user)


@router.get("/records/{record_id}", response_model=ElevationFileRecordSummary)
def get_elevation_file_record_detail(
    record_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordSummary:
    item = get_file_record_by_id(db, record_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    return serialize_file_record(item)


@router.patch("/records/{record_id}", response_model=ElevationFileRecordSummary)
def update_elevation_file_record(
    record_id: str,
    payload: ElevationFileRecordUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordSummary:
    updated = update_file_record(db, record_id, payload, actor=current_user.user)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    return updated


@router.delete("/records/{record_id}")
def delete_elevation_file_record(
    record_id: str,
    _: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_file_record(db, record_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    return {"success": True}


@router.post("/records/{record_id}/analyze", response_model=ElevationFileRecordAnalyzeResponse)
def analyze_elevation_file_record(
    record_id: str,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordAnalyzeResponse:
    return queue_file_record_analysis(db, record_id=record_id, actor=current_user.user)


@router.post("/records/{record_id}/terrain/build", response_model=ElevationFileRecordTerrainBuildResponse)
def build_elevation_file_record_terrain(
    record_id: str,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordTerrainBuildResponse:
    return queue_file_record_terrain_build(db, record_id=record_id, actor=current_user.user)


@router.get("/records/{record_id}/preview", response_model=ElevationFileRecordPreviewResponse)
def preview_elevation_file_record(
    record_id: str,
    max_points: int = Query(default=1500, ge=1, le=5000),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordPreviewResponse:
    return preview_file_record(
        db,
        record_id=record_id,
        max_points=max_points,
    )


@router.get("/records/{record_id}/linked-lines", response_model=ElevationLinkedLineListResponse)
def get_elevation_file_record_linked_lines(
    record_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationLinkedLineListResponse:
    """查询高程文件回填过的关联线路列表（含最近一次回填状态/杆塔统计）。"""
    return get_linked_lines_for_file_record(db, record_id=record_id)


@router.get("/records/{record_id}/lines-preview", response_model=ElevationBackfillCoverageResponse)
def get_elevation_file_record_backfill_coverage(
    record_id: str,
    line_ids: str | None = Query(default=None, description="逗号分隔的线路 ID，缺省返回全部线路"),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationBackfillCoverageResponse:
    """逐塔预检：返回每条候选线路对当前高程文件的可回填覆盖统计。

    对每条线路的每座杆塔真实采样一次，统计可命中塔数（matchable_tower_count）。
    使命中 0 座的线路（DEM 在该区域为 NoData）在回填选线路时禁用并标注。
    """
    ids = None
    if line_ids:
        ids = [s.strip() for s in line_ids.split(",") if s.strip()]
    items = preview_backfill_coverage(db, record_id=record_id, line_ids=ids)
    return ElevationBackfillCoverageResponse(
        file_record_id=record_id,
        items=items,
        total=len(items),
    )


@router.get("/records/{record_id}/jobs", response_model=ElevationApplyJobListResponse)
def get_elevation_file_record_jobs(
    record_id: str,
    status: str | None = Query(default=None),
    line_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobListResponse:
    """查询单个高程文件的所有回填任务记录（支持按线路名称/编号关键词后台过滤）。"""
    return list_jobs(
        db,
        line_id=line_id,
        status_filter=status,
        keyword=keyword,
        limit=limit,
        file_record_id=record_id,
    )


@router.get("/records/{record_id}/analysis-status", response_model=ElevationFileRecordTaskStatusResponse)
def get_elevation_file_record_analysis_status(
    record_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordTaskStatusResponse:
    return get_file_record_analysis_task_status(db, record_id=record_id)


@router.get("/records/{record_id}/terrain-status", response_model=ElevationFileRecordTerrainTaskStatusResponse)
def get_elevation_file_record_terrain_status(
    record_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordTerrainTaskStatusResponse:
    return get_file_record_terrain_task_status(db, record_id=record_id)


@router.get("/records/{record_id}/terrain/layer.json", response_model=ElevationTerrainLayerResponse)
def get_elevation_file_record_terrain_layer(
    record_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationTerrainLayerResponse:
    return get_file_record_terrain_layer(db, record_id=record_id)


@router.get("/records/{record_id}/terrain/{z}/{x}/{y}.terrain")
def get_elevation_file_record_terrain_tile_endpoint(
    record_id: str,
    z: int,
    x: int,
    y: int,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> Response:
    content = get_file_record_terrain_tile(db, record_id=record_id, z=z, x=x, y=y)
    return Response(content=content, media_type="application/octet-stream")


@router.get("/jobs/{job_id}/towers", response_model=ElevationApplyJobTowerListResponse)
def get_elevation_apply_job_towers(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobTowerListResponse:
    """查询一个高程回填任务的逐杆塔回填数据明细（分页）。"""
    return list_job_towers(db, job_id=job_id, limit=limit, offset=offset)


@router.post("/jobs/apply-line", response_model=ElevationApplyJobCreateResponse)
def apply_elevation_job_to_line(
    payload: ElevationApplyJobCreateRequest,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobCreateResponse:
    """将高程数据回填到线路杆塔，创建异步回填任务。

    前端 elevation-records 与 power-lines 页面的回填弹窗调用本接口。
    服务层 create_apply_job 完成全部校验（线路 404 / file_record_id 必填 400 /
    模式 400 / 线路无杆塔 400）并派发 Celery 任务。
    """
    return create_apply_job(db, payload, actor=current_user.user)


# ============================================================================
# Legacy Dataset API (backed by ElevationFileRecord)
# ============================================================================


@router.get("/datasets", response_model=ElevationDatasetListResponse)
def list_elevation_datasets_endpoint(
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetListResponse:
    """List elevation file records in the legacy dataset format.

    The frontend power-lines page calls GET /api/v1/elevation/datasets to
    populate terrain dataset selection.  This endpoint bridges the gap by
    returning file records mapped to the old ElevationDatasetSummary shape.
    """
    return list_elevation_datasets(db)
