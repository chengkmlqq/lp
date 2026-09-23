from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.atp_asset import (
    AtpAssetCreateRequest,
    AtpAssetDetail,
    AtpAssetFileContentResponse,
    AtpAssetFileListResponse,
    AtpAssetListResponse,
    AtpAssetRunDetail,
    AtpAssetRunListResponse,
    AtpAssetRunRequest,
    AtpAssetTestRunRequest,
    AtpAssetUpdateRequest,
    AtpEngineStatusResponse,
)
from ...services.atp_asset_service import (
    create_asset,
    delete_asset,
    get_asset_by_id,
    get_engine_status,
    get_run_detail,
    list_asset_files,
    list_assets,
    list_runs,
    read_asset_file_content,
    serialize_asset,
    upload_asset_files,
    update_asset,
)
from ...services.atp_asset_test_service import (
    create_test_run,
    read_artifact_zip,
    read_compare_json,
)

router = APIRouter(prefix="/atp", tags=["atp-assets"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("/engine/status", response_model=AtpEngineStatusResponse)
def get_atp_engine_status_endpoint(
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
) -> AtpEngineStatusResponse:
    return get_engine_status()


@router.get("/assets", response_model=AtpAssetListResponse)
def get_atp_asset_list(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    voltage_level: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    scene_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetListResponse:
    return list_assets(
        db,
        keyword=keyword,
        status_filter=status_filter,
        voltage_level=voltage_level,
        tower_type=tower_type,
        scene_type=scene_type,
        limit=limit,
        offset=offset,
    )


@router.post("/assets", response_model=AtpAssetDetail)
def create_atp_asset_endpoint(
    payload: AtpAssetCreateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    created = create_asset(db, payload, actor_user_id=current_user.user.id)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset code already exists")
    return AtpAssetDetail(**created.model_dump())


@router.post("/assets/{asset_id}/files", response_model=AtpAssetDetail)
def upload_atp_asset_files_endpoint(
    asset_id: str,
    temp_file_id: str | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """上传模型文件到资产目录。

    支持两种入参：
    1. 传统方式：直接上传文件（files 字段，zip 或散文件）
    2. 两段式：先调用通用 upload-temp 端点获取 temp_file_id，再提交 temp_file_id
    临时文件在消费后自动删除，或由 24h 定时清理任务兜底。
    """
    updated = upload_asset_files(
        db,
        asset_id=asset_id,
        files=files or [],
        temp_file_id=temp_file_id,
        actor_user_id=current_user.user.id,
    )
    return AtpAssetDetail(**updated.model_dump())


@router.get("/assets/{asset_id}/files", response_model=AtpAssetFileListResponse)
def list_atp_asset_files_endpoint(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileListResponse:
    """列出资产目录下的模型文件（前端详情页「文件」tab 数据源）。"""
    return list_asset_files(db, asset_id=asset_id)


@router.get("/assets/{asset_id}/files/content", response_model=AtpAssetFileContentResponse)
def read_atp_asset_file_content_endpoint(
    asset_id: str,
    path: str = Query(..., description="相对存储根目录的文件路径，如 templates/fanji/short.dat"),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileContentResponse:
    """读取资产目录下文本文件内容（dat 文件详情查看、lib 结果查看等）。"""
    return read_asset_file_content(db, asset_id=asset_id, relative_path=path)


@router.get("/assets/{asset_id}", response_model=AtpAssetDetail)
def get_atp_asset_detail(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    item = get_asset_by_id(db, asset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    detail = serialize_asset(
        item,
        run_count=len(item.runs),
        last_run_status=item.runs[0].status if item.runs else None,
        last_run_date=item.runs[0].create_date if item.runs else None,
        db=db,
    )
    return AtpAssetDetail(**detail.model_dump())


@router.patch("/assets/{asset_id}", response_model=AtpAssetDetail)
def update_atp_asset_endpoint(
    asset_id: str,
    payload: AtpAssetUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    updated = update_asset(db, asset_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return AtpAssetDetail(**updated.model_dump())


@router.delete("/assets/{asset_id}")
def delete_atp_asset_endpoint(
    asset_id: str,
    _: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_asset(db, asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return {"success": True}





@router.get("/runs/{run_id}", response_model=AtpAssetRunDetail)
def get_atp_run_detail(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunDetail:
    return get_run_detail(db, run_id=run_id)


# ─────────────────────── 单模型测试（分段 + 对拍产物） ───────────────────────
# 设计见 services/atp_asset_test_service.py 模块注释：
# materialize（物化+引擎文件）→ geometry（DAT→LIB）→ simulate（单次 ATP），
# 判据看产物（哈希/数值/LIS 报错）而非退出码，产出 compare.json 供与 C# 端 diff。


@router.post("/assets/{asset_id}/test-runs", response_model=AtpAssetRunDetail)
def create_atp_asset_test_run_endpoint(
    asset_id: str,
    payload: AtpAssetTestRunRequest,
    current_user: CurrentUser = Depends(require_any_permission("atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunDetail:
    """发起一次 ATP 模型单模型测试（异步，返回 run 记录供轮询）。"""
    return create_test_run(
        db,
        asset_id=asset_id,
        payload=payload,
        actor_user_id=current_user.user.id,
    )


@router.get("/assets/{asset_id}/test-runs", response_model=AtpAssetRunListResponse)
def list_atp_asset_test_runs_endpoint(
    asset_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunListResponse:
    """该资产的运行记录（测试运行与生产运行共用 atp_asset_run 表，按时间倒序）。"""
    return list_runs(db, asset_id=asset_id, limit=limit, offset=offset)


@router.get("/test-runs/{run_id}/compare")
def get_atp_asset_test_compare(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """取对拍产物 compare.json（schema ``lp.atp.compare/1``，与 C# harness 同格式）。"""
    return read_compare_json(db, run_id=run_id)


@router.get("/test-runs/{run_id}/artifacts")
def download_atp_asset_test_artifacts(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载测试产物包（改写后的 dat/pch/lib/lis/pl4 + manifest + compare.json）。"""
    path, filename = read_artifact_zip(db, run_id=run_id)
    return FileResponse(path, filename=filename, media_type="application/zip")
