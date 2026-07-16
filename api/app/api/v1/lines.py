from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.line import (
    LineCreateRequest,
    LineListResponse,
    LineSummary,
    LineTowerCreateRequest,
    LineTowerImportResponse,
    LineTowerListResponse,
    LineTowerSummary,
    LineTowerUpdateRequest,
    LineUpdateRequest,
)
from ...services.line_service import (
    create_line,
    create_line_tower,
    delete_line,
    delete_line_tower,
    export_line_towers_to_csv,
    get_line_by_id,
    get_line_tower_by_id,
    import_line_towers_from_csv,
    list_line_towers,
    list_lines,
    serialize_line,
    serialize_line_tower,
    update_line,
    update_line_tower,
)

router = APIRouter(prefix="/lines", tags=["lines"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("", response_model=LineListResponse)
def get_line_list(
    keyword: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> LineListResponse:
    return list_lines(db, keyword=keyword)


@router.post("", response_model=LineSummary)
def create_line_endpoint(
    payload: LineCreateRequest,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> LineSummary:
    return create_line(db, payload, actor_user_id=current_user.user.id)


@router.get("/{line_id}", response_model=LineSummary)
def get_line_detail(
    line_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> LineSummary:
    line = get_line_by_id(db, line_id)
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")

    tower_total = int(len(line.towers))
    return serialize_line(line, tower_count=tower_total)


@router.patch("/{line_id}", response_model=LineSummary)
def update_line_endpoint(
    line_id: str,
    payload: LineUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> LineSummary:
    updated = update_line(db, line_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    return updated


@router.delete("/{line_id}")
def delete_line_endpoint(
    line_id: str,
    _: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_line(db, line_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    return {"success": True}


@router.get("/{line_id}/towers", response_model=LineTowerListResponse)
def get_line_tower_list(
    line_id: str,
    keyword: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("tower.read", "tower.manage", "line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> LineTowerListResponse:
    line = get_line_by_id(db, line_id)
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    return list_line_towers(
        db,
        line_id=line_id,
        keyword=keyword,
        tower_type=tower_type,
        risk_level=risk_level,
        limit=limit,
        offset=offset,
    )


@router.post("/{line_id}/towers", response_model=LineTowerSummary)
def create_line_tower_endpoint(
    line_id: str,
    payload: LineTowerCreateRequest,
    current_user: CurrentUser = Depends(require_permission("tower.manage")),
    db: Session = Depends(get_db),
) -> LineTowerSummary:
    created = create_line_tower(db, line_id, payload, actor_user_id=current_user.user.id)
    if not created:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    return created


@router.patch("/towers/{tower_id}", response_model=LineTowerSummary)
def update_line_tower_endpoint(
    tower_id: str,
    payload: LineTowerUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("tower.manage")),
    db: Session = Depends(get_db),
) -> LineTowerSummary:
    updated = update_line_tower(db, tower_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tower not found")
    return updated


@router.delete("/towers/{tower_id}")
def delete_line_tower_endpoint(
    tower_id: str,
    _: CurrentUser = Depends(require_permission("tower.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_line_tower(db, tower_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tower not found")
    return {"success": True}


@router.post("/{line_id}/towers/import", response_model=LineTowerImportResponse)
def import_line_tower_csv_endpoint(
    line_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("tower.manage")),
    db: Session = Depends(get_db),
) -> LineTowerImportResponse:
    line = get_line_by_id(db, line_id)
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")
    return import_line_towers_from_csv(
        db,
        line=line,
        file=file,
        actor_user_id=current_user.user.id,
    )


@router.get("/{line_id}/towers/export")
def export_line_towers_endpoint(
    line_id: str,
    _: CurrentUser = Depends(require_any_permission("tower.read", "tower.manage", "line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    line = get_line_by_id(db, line_id)
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line not found")

    filename, content = export_line_towers_to_csv(db, line=line)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type="text/csv", headers=headers)


@router.get("/towers/{tower_id}", response_model=LineTowerSummary)
def get_line_tower_detail(
    tower_id: str,
    _: CurrentUser = Depends(require_any_permission("tower.read", "tower.manage", "line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> LineTowerSummary:
    item = get_line_tower_by_id(db, tower_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tower not found")
    return serialize_line_tower(item)
