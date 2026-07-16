from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.wine import WineRunDetail, WineRunListResponse, WineRunRequest, WineStatusResponse
from ...services.wine_service import create_run, get_run_detail, get_wine_status, list_runs


router = APIRouter(prefix="/wine", tags=["wine"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("/status", response_model=WineStatusResponse)
async def get_wine_status_endpoint(
    _: CurrentUser = Depends(require_any_permission("wine.read", "wine.manage")),
) -> WineStatusResponse:
    return await get_wine_status()


@router.get("/runs", response_model=WineRunListResponse)
def list_wine_runs_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("wine.read", "wine.manage")),
    db: Session = Depends(get_db),
) -> WineRunListResponse:
    return list_runs(db, limit=limit, offset=offset)


@router.post("/runs", response_model=WineRunDetail)
def create_wine_run_endpoint(
    payload: WineRunRequest,
    current_user: CurrentUser = Depends(require_permission("wine.manage")),
    db: Session = Depends(get_db),
) -> WineRunDetail:
    return create_run(db, payload=payload, actor_user_id=current_user.user.id)


@router.get("/runs/{run_id}", response_model=WineRunDetail)
def get_wine_run_detail_endpoint(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("wine.read", "wine.manage")),
    db: Session = Depends(get_db),
) -> WineRunDetail:
    return get_run_detail(db, run_id=run_id)


@router.post("/test/stream", response_model=WineRunDetail)
def test_wine_stream_endpoint(
    payload: WineRunRequest,
    current_user: CurrentUser = Depends(require_permission("wine.manage")),
    db: Session = Depends(get_db),
) -> WineRunDetail:
    return create_run(db, payload=payload, actor_user_id=current_user.user.id)


@router.post("/run/stream", response_model=WineRunDetail)
def run_wine_stream_endpoint(
    payload: WineRunRequest,
    current_user: CurrentUser = Depends(require_permission("wine.manage")),
    db: Session = Depends(get_db),
) -> WineRunDetail:
    return create_run(db, payload=payload, actor_user_id=current_user.user.id)
