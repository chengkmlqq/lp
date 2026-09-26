"""ATP 参数注册表（计算参数管理）接口：CRUD / 字段目录 / 脚本试算 / 预览解析。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_permission
from ...schemas.atp_param_definition import (
    DefinitionListResponse,
    DefinitionSummary,
    DefinitionUpsertRequest,
    FieldsResponse,
    ResolvePreviewRequest,
    ResolvePreviewResponse,
    TestScriptRequest,
    TestScriptResponse,
)
from ...services.atp_param_definition_service import (
    DefinitionServiceError,
    create_definition,
    delete_definition,
    field_catalog,
    get_definition,
    list_definitions,
    preview_resolve,
    serialize_definition,
    test_script,
    update_definition,
)
from ...services.atp_param_registry import DefinitionError

router = APIRouter(prefix="/atp/param-definitions", tags=["atp-param-definitions"])


def _guard(action: str):
    if action == "manage":
        return require_permission("atp.manage")
    return require_any_permission("atp.read", "atp.run", "atp.manage")


@router.get("/fields", response_model=FieldsResponse)
def get_bindable_fields(
    db: Session = Depends(get_db),  # noqa: ARG001
    _: CurrentUser = Depends(_guard("read")),
) -> FieldsResponse:
    return FieldsResponse(**field_catalog())


@router.post("/test-script", response_model=TestScriptResponse)
def post_test_script(
    payload: TestScriptRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> TestScriptResponse:
    try:
        result = test_script(payload.model_dump(), db)
    except (DefinitionError, DefinitionServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TestScriptResponse(**result)


@router.post("/resolve-preview", response_model=ResolvePreviewResponse)
def post_resolve_preview(
    payload: ResolvePreviewRequest,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> ResolvePreviewResponse:
    try:
        result = preview_resolve(db, payload.model_dump())
    except (DefinitionError, DefinitionServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ResolvePreviewResponse(**result)


@router.get("", response_model=DefinitionListResponse)
def get_param_definitions(
    keyword: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> DefinitionListResponse:
    items = list_definitions(db, keyword=keyword, source_type=source_type)
    return DefinitionListResponse(items=items, total=len(items))  # type: ignore[arg-type]


@router.get("/{definition_id}", response_model=DefinitionSummary)
def get_param_definition(
    definition_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("read")),
) -> DefinitionSummary:
    try:
        row = get_definition(db, definition_id)
    except DefinitionServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DefinitionSummary(**serialize_definition(row))


@router.post("", response_model=DefinitionSummary, status_code=status.HTTP_201_CREATED)
def post_param_definition(
    payload: DefinitionUpsertRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_guard("manage")),
) -> DefinitionSummary:
    try:
        created = create_definition(db, payload.model_dump(), operator=getattr(current_user, "username", None))
    except (DefinitionError, DefinitionServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DefinitionSummary(**created)


@router.put("/{definition_id}", response_model=DefinitionSummary)
def put_param_definition(
    definition_id: str,
    payload: DefinitionUpsertRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_guard("manage")),
) -> DefinitionSummary:
    try:
        updated = update_definition(
            db, definition_id, payload.model_dump(), operator=getattr(current_user, "username", None)
        )
    except (DefinitionError, DefinitionServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DefinitionSummary(**updated)


@router.delete("/{definition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_param_definition(
    definition_id: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_guard("manage")),
) -> None:
    try:
        delete_definition(db, definition_id)
    except DefinitionServiceError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
