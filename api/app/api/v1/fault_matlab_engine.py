from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...services.fault_matlab_engine_service import (
    MatlabEngineError,
    create_module,
    delete_module,
    delete_version,
    get_module,
    get_version_files,
    list_modules,
    list_versions,
    publish_draft,
    rollback_to_version,
    trigger_sync_for_module,
    update_module,
    upload_draft,
)
from ...services.minio_storage import (
    MinioObjectNotFoundError,
    MinioStorageError,
    build_matlab_engine_draft_prefix,
    build_matlab_engine_release_prefix,
    get_object,
)

router = APIRouter(
    prefix="/fault-matlab",
    tags=["fault-matlab-engine"],
    dependencies=[Depends(require_enabled_menu_route)],
)


class ModuleCreateRequest(BaseModel):
    slug: str = Field(default="", description="模块标识，可选，自动生成或手动输入")
    name: str = Field(..., description="模块显示名称")
    description: str = Field(default="", description="模块描述")
    required_files: list[str] | None = Field(default=None, description="必需文件列表")
    worker_deploy_path: str = Field(default="", description="Worker 部署路径")


class ModuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, description="模块显示名称")
    description: str | None = Field(default=None, description="模块描述")
    required_files: list[str] | None = Field(default=None, description="必需文件列表")
    worker_deploy_path: str | None = Field(default=None, description="Worker 部署路径")


class PublishRequest(BaseModel):
    version_tag: str = Field(..., description="版本号，如 v1.0.0")
    changelog: str = Field(default="", description="变更日志")


def _current_user_id(current_user: CurrentUser) -> str:
    return current_user.user.id


def _current_user_name(current_user: CurrentUser) -> str:
    return getattr(current_user.user, "username", "") or getattr(current_user.user, "user_name", "") or ""


def _handle_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, MatlabEngineError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="内部错误")


@router.get("/modules")
def get_modules(
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": list_modules(db)}


@router.post("/modules")
def create_matlab_module(
    payload: ModuleCreateRequest,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        module = create_module(db, payload.model_dump(), actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return module


@router.put("/modules/{slug}")
def update_matlab_module(
    slug: str,
    payload: ModuleUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        module = update_module(db, slug, payload.model_dump(exclude_unset=True), actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not module:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"模块不存在: {slug}")
    return module


@router.delete("/modules/{slug}")
def delete_matlab_module(
    slug: str,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        ok = delete_module(db, slug, actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"模块不存在: {slug}")
    return {"deleted": True, "slug": slug}


@router.get("/modules/{slug}/versions")
def get_module_versions(
    slug: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    if not get_module(db, slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"模块不存在: {slug}")
    return list_versions(db, slug, limit=limit, offset=offset)


@router.post("/modules/{slug}/upload")
def upload_module_draft(
    slug: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    try:
        draft = upload_draft(
            db,
            slug,
            content,
            uploaded_by=_current_user_id(current_user),
            uploaded_by_name=_current_user_name(current_user),
        )
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return draft


@router.post("/modules/{slug}/publish")
def publish_module_draft(
    slug: str,
    payload: PublishRequest,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        release = publish_draft(
            db,
            slug,
            version_hash=_get_draft_hash(db, slug),
            version_tag=payload.version_tag,
            changelog=payload.changelog,
            actor_user_id=_current_user_id(current_user),
        )
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return release


def _get_draft_hash(db: Session, slug: str) -> str:
    versions = list_versions(db, slug)
    draft = versions.get("draft")
    if not draft:
        raise MatlabEngineError("当前没有草稿版本")
    return draft.get("version_hash", "")


@router.post("/modules/{slug}/rollback")
def rollback_module_version(
    slug: str,
    payload: dict[str, Any],
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    version_hash = str(payload.get("version_hash") or "")
    if not version_hash:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 version_hash")
    try:
        draft = rollback_to_version(db, slug, version_hash, actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return draft


@router.delete("/modules/{slug}/versions/{version_hash}")
def delete_module_version(
    slug: str,
    version_hash: str,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return delete_version(db, slug, version_hash, actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/modules/{slug}/versions/{version_hash}/files")
def get_module_version_files(
    slug: str,
    version_hash: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return get_version_files(db, slug, version_hash)
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _resolve_engine_package_prefix(slug: str, version_hash: str, scope: str) -> str:
    """返回指定 scope（draft/release）下 engine.zip 所在前缀。"""
    if scope == "draft":
        return build_matlab_engine_draft_prefix(slug, version_hash)
    return build_matlab_engine_release_prefix(slug, version_hash)


def _download_name(slug: str, version_tag: str, version_hash: str) -> str:
    """生成下载文件名：{module_slug}_{version_tag}.zip，版本号缺省时退化为 hash。"""
    tag = (version_tag or "").strip().replace("/", "_").replace("\\", "_") or version_hash
    return f"{slug}_{tag}.zip"


@router.get("/modules/{slug}/versions/{version_hash}/download")
def download_module_version_package(
    slug: str,
    version_hash: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """下载指定版本（草稿或已发布）上传的 engine.zip 原始包。"""
    if not get_module(db, slug):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"模块不存在: {slug}")
    versions = list_versions(db, slug)
    draft = versions.get("draft")
    releases = versions.get("releases", [])

    scope: str | None = None
    version_tag = ""
    if draft and draft.get("version_hash") == version_hash:
        scope = "draft"
        version_tag = draft.get("version_tag") or ""
    else:
        for item in releases:
            if item.get("version_hash") == version_hash:
                scope = "release"
                version_tag = item.get("version_tag") or ""
                break
    if not scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"版本不存在: {version_hash}")

    prefix = _resolve_engine_package_prefix(slug, version_hash, scope)
    zip_key = f"{prefix}engine.zip"
    try:
        content = get_object(zip_key)
    except MinioObjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"该版本的上传包不存在（{scope}）",
        ) from exc
    except MinioStorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    filename = _download_name(slug, version_tag, version_hash)
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in filename) or "engine.zip"
    encoded_filename = quote(filename)
    return StreamingResponse(
        iter([content]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_filename}',
        },
    )


@router.post("/modules/{slug}/sync")
def sync_module_engine(
    slug: str,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        task_id = trigger_sync_for_module(db, slug, actor_user_id=_current_user_id(current_user))
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "dispatched"}
