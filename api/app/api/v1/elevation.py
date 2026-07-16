from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.elevation import (
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
    ElevationDatasetCreateRequest,
    ElevationDatasetFileListResponse,
    ElevationDatasetListResponse,
    ElevationDatasetPreviewResponse,
    ElevationDatasetSummary,
    ElevationDatasetTerrainBuildResponse,
    ElevationDatasetTerrainTaskStatusResponse,
    ElevationTerrainLayerResponse,
    ElevationDatasetUpdateRequest,
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
)
from ...services.elevation_service import (
    create_apply_job,
    create_dataset,
    delete_dataset,
    get_data_import_job_by_id,
    get_dataset_analysis_task_status,
    get_file_record_analysis_task_status,
    get_file_record_terrain_layer,
    get_file_record_terrain_task_status,
    get_file_record_terrain_tile,
    get_dataset_terrain_layer,
    get_dataset_terrain_task_status,
    get_dataset_terrain_tile,
    get_job_by_id,
    import_dataset_data_files,
    import_datasets_from_csv,
    list_data_import_jobs,
    list_dataset_files,
    list_datasets,
    list_jobs,
    preview_dataset,
    queue_dataset_analysis,
    queue_dataset_terrain_build,
    serialize_data_import_job,
    serialize_job,
    update_dataset,
)
from ...services.elevation_file_record_service import (
    create_file_record_from_upload,
    delete_file_record,
    get_file_record_by_id,
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


@router.post("/records", response_model=ElevationFileRecordUploadResponse)
def create_elevation_file_record(
    file: UploadFile = File(...),
    source: str | None = Form(default=None),
    mount_code: str | None = Form(default=None),
    resolution_m: float | None = Form(default=None),
    notes: str | None = Form(default=None),
    trigger_analysis: bool = Form(default=True),
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationFileRecordUploadResponse:
    payload = ElevationFileRecordCreateRequest(
        source=source,
        mount_code=mount_code,
        resolution_m=resolution_m,
        notes=notes,
        trigger_analysis=trigger_analysis,
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


# ============================================================================
# Legacy Dataset API (向后兼容，逐步废弃)
# ============================================================================

@router.get("/datasets", response_model=ElevationDatasetListResponse)
def get_elevation_datasets(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetListResponse:
    return list_datasets(
        db,
        keyword=keyword,
        status_filter=status_filter,
    )


@router.post("/datasets", response_model=ElevationDatasetSummary)
def create_elevation_dataset(
    payload: ElevationDatasetCreateRequest,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetSummary:
    created = create_dataset(db, payload, actor=current_user.user)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="高程数据集编码已存在")
    return created


@router.post("/datasets/import", response_model=ElevationDatasetBatchImportResponse)
def import_elevation_datasets(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetBatchImportResponse:
    return import_datasets_from_csv(
        db,
        file=file,
        actor=current_user.user,
    )


@router.post("/datasets/{dataset_id}/data/import", response_model=ElevationDatasetDataImportResponse)
def import_elevation_dataset_data(
    dataset_id: str,
    files: list[UploadFile] = File(...),
    trigger_analysis: bool = Form(True),
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetDataImportResponse:
    return import_dataset_data_files(
        db,
        dataset_id=dataset_id,
        files=files,
        actor=current_user.user,
        trigger_analysis=trigger_analysis,
    )


@router.patch("/datasets/{dataset_id}", response_model=ElevationDatasetSummary)
def update_elevation_dataset(
    dataset_id: str,
    payload: ElevationDatasetUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetSummary:
    updated = update_dataset(db, dataset_id, payload, actor=current_user.user)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    return updated


@router.delete("/datasets/{dataset_id}")
def delete_elevation_dataset(
    dataset_id: str,
    _: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_dataset(db, dataset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程数据集不存在")
    return {"success": True}


@router.post("/datasets/{dataset_id}/analyze", response_model=ElevationDatasetAnalyzeResponse)
def analyze_elevation_dataset(
    dataset_id: str,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetAnalyzeResponse:
    return queue_dataset_analysis(db, dataset_id=dataset_id, actor=current_user.user)


@router.post("/datasets/{dataset_id}/terrain/build", response_model=ElevationDatasetTerrainBuildResponse)
def build_elevation_dataset_terrain(
    dataset_id: str,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetTerrainBuildResponse:
    return queue_dataset_terrain_build(db, dataset_id=dataset_id, actor=current_user.user)


@router.get("/datasets/{dataset_id}/preview", response_model=ElevationDatasetPreviewResponse)
def preview_elevation_dataset(
    dataset_id: str,
    max_points: int = Query(default=1500, ge=1, le=5000),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetPreviewResponse:
    return preview_dataset(
        db,
        dataset_id=dataset_id,
        max_points=max_points,
    )


@router.get("/datasets/{dataset_id}/files", response_model=ElevationDatasetFileListResponse)
def get_elevation_dataset_files(
    dataset_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetFileListResponse:
    return list_dataset_files(db, dataset_id=dataset_id)


@router.get("/datasets/{dataset_id}/analysis-task", response_model=ElevationDatasetAnalysisTaskStatusResponse)
def get_elevation_dataset_analysis_task_status(
    dataset_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetAnalysisTaskStatusResponse:
    return get_dataset_analysis_task_status(db, dataset_id=dataset_id)


@router.get("/datasets/{dataset_id}/terrain/status", response_model=ElevationDatasetTerrainTaskStatusResponse)
def get_elevation_dataset_terrain_status(
    dataset_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDatasetTerrainTaskStatusResponse:
    return get_dataset_terrain_task_status(db, dataset_id=dataset_id)


@router.get("/import-jobs", response_model=ElevationDataImportJobListResponse)
def get_elevation_data_import_jobs(
    dataset_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDataImportJobListResponse:
    return list_data_import_jobs(
        db,
        dataset_id=dataset_id,
        status_filter=status_filter,
        limit=limit,
    )


@router.get("/import-jobs/{job_id}", response_model=ElevationDataImportJobSummary)
def get_elevation_data_import_job_detail(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationDataImportJobSummary:
    item = get_data_import_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程导入任务不存在")
    return serialize_data_import_job(item)


@router.get("/datasets/{dataset_id}/terrain/layer.json", response_model=ElevationTerrainLayerResponse)
def get_elevation_dataset_terrain_layer(
    dataset_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationTerrainLayerResponse:
    return get_dataset_terrain_layer(db, dataset_id=dataset_id)


@router.get("/datasets/{dataset_id}/terrain/{z}/{x}/{y}.terrain")
def get_elevation_dataset_terrain_tile_endpoint(
    dataset_id: str,
    z: int,
    x: int,
    y: int,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> Response:
    content = get_dataset_terrain_tile(db, dataset_id=dataset_id, z=z, x=x, y=y)
    return Response(content=content, media_type="application/octet-stream")


@router.get("/jobs", response_model=ElevationApplyJobListResponse)
def get_elevation_jobs(
    line_id: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    file_record_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobListResponse:
    return list_jobs(
        db,
        line_id=line_id,
        dataset_id=dataset_id,
        file_record_id=file_record_id,
        status_filter=status_filter,
        limit=limit,
    )


@router.get("/jobs/{job_id}", response_model=ElevationApplyJobSummary)
def get_elevation_job_detail(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("elevation.read", "elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobSummary:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="高程回填任务不存在")
    return serialize_job(item)


@router.post("/jobs/apply-line", response_model=ElevationApplyJobCreateResponse)
def create_elevation_apply_line_job(
    payload: ElevationApplyJobCreateRequest,
    current_user: CurrentUser = Depends(require_permission("elevation.manage")),
    db: Session = Depends(get_db),
) -> ElevationApplyJobCreateResponse:
    # Support both file_record_id (new) and dataset_id (legacy)
    if not payload.file_record_id and not payload.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须提供 file_record_id 或 dataset_id"
        )

    return create_apply_job(
        db,
        payload,
        actor=current_user.user,
    )
