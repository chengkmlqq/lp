from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.tower_profile import TowerProfileDetail, TowerProfileUpsertRequest
from ...services.tower_profile_service import get_tower_profile_detail, upsert_tower_profile
from ...services.tower_topology import TowerGeometryValidationError

router = APIRouter(prefix="/tower-profiles", tags=["tower-profiles"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("/{tower_id}", response_model=TowerProfileDetail)
def get_tower_profile_endpoint(
    tower_id: str,
    _: CurrentUser = Depends(require_any_permission("tower.read", "tower.manage", "line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> TowerProfileDetail:
    item = get_tower_profile_detail(db, tower_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tower not found")
    return item


@router.put("/{tower_id}", response_model=TowerProfileDetail)
def put_tower_profile_endpoint(
    tower_id: str,
    payload: TowerProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_permission("tower.manage")),
    db: Session = Depends(get_db),
) -> TowerProfileDetail:
    try:
        item = upsert_tower_profile(db, tower_id, payload, actor=current_user.user)
    except TowerGeometryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tower not found")
    return item
