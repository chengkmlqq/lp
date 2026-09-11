"""ATP 参数模板（配置化）接口：模板树 / 增删改 / 试算预览 / 派生 / 维度选项。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_permission
from ...schemas.atp_param_template import (
    DeriveRequest,
    DeriveResponse,
    MetaResponse,
    ResolvePreviewRequest,
    ResolvePreviewResponse,
    TemplateDetail,
    TemplateListResponse,
    TemplateUpsertRequest,
    TreeResponse,
)
from ...services.atp_param_config import cache_info, invalidate
from ...services.atp_param_template_service import (
    TemplateError,
    build_tree,
    create_template,
    delete_template,
    derive_template,
    get_template,
    list_templates,
    meta_options,
    resolve_preview,
    serialize_template,
    update_template,
)

router = APIRouter(prefix="/atp/param-templates", tags=["atp-param-templates"])


def _guard(action: str):
    if action == "manage":
        return require_permission("atp.manage")
    return require_any_permission("atp.read", "atp.run", "atp.manage")


@router.get("/tree", response_model=TreeResponse)
def get_param_template_tree(
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> TreeResponse:
    return TreeResponse(**build_tree(db, keyword=keyword))


@router.get("/meta", response_model=MetaResponse)
def get_param_template_meta(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> MetaResponse:
    return MetaResponse(**meta_options(db))


@router.get("/cache", response_model=dict)
def get_param_template_cache(
    _: CurrentUser = Depends(_guard("read")),
) -> dict:
    return cache_info()


@router.post("/cache/refresh", response_model=dict)
def refresh_param_template_cache(
    _: CurrentUser = Depends(_guard("manage")),
) -> dict:
    invalidate()
    return cache_info()


@router.get("", response_model=TemplateListResponse)
def get_param_templates(
    keyword: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    voltage_level: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> TemplateListResponse:
    items = list_templates(db, keyword=keyword, tower_type=tower_type, voltage_level=voltage_level)
    return TemplateListResponse(items=items, total=len(items))  # type: ignore[arg-type]


@router.post("", response_model=TemplateDetail, status_code=status.HTTP_201_CREATED)
def post_param_template(
    payload: TemplateUpsertRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_guard("manage")),
) -> TemplateDetail:
    try:
        created = create_template(db, payload.model_dump(), operator=getattr(current_user, "username", None))
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemplateDetail(**created)


@router.post("/resolve-preview", response_model=ResolvePreviewResponse)
def post_param_template_preview(
    payload: ResolvePreviewRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> ResolvePreviewResponse:
    try:
        return ResolvePreviewResponse(**resolve_preview(db, payload.model_dump()))
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/derive", response_model=DeriveResponse)
def post_param_template_derive(
    payload: DeriveRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> DeriveResponse:
    try:
        return DeriveResponse(**derive_template(db, payload.model_dump()))
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{template_id}", response_model=TemplateDetail)
def get_param_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> TemplateDetail:
    try:
        row = get_template(db, template_id)
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TemplateDetail(**serialize_template(row, with_slots=True))


@router.put("/{template_id}", response_model=TemplateDetail)
def put_param_template(
    template_id: str,
    payload: TemplateUpsertRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_guard("manage")),
) -> TemplateDetail:
    try:
        updated = update_template(
            db, template_id, payload.model_dump(), operator=getattr(current_user, "username", None)
        )
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TemplateDetail(**updated)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_param_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("manage")),
) -> None:
    try:
        delete_template(db, template_id)
    except TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
