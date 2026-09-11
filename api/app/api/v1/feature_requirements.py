"""功能需求单接口：列表 / 详情 / 新建 / 修改 / 状态 / 删除 / 元数据。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_any_permission,
    require_enabled_menu_route,
    require_permission,
)
from app.schemas.feature_requirement import (
    RequirementCreate,
    RequirementListOut,
    RequirementMetaOut,
    RequirementOut,
    RequirementStatusUpdate,
    RequirementUpdate,
)
from app.services import feature_requirement_service as svc

router = APIRouter(prefix="/feature-requirements", tags=["feature-requirements"], dependencies=[Depends(require_enabled_menu_route)])

_READ = require_any_permission("atp.read", "atp.run", "atp.manage")
_WRITE = require_permission("atp.manage")


@router.get("", response_model=RequirementListOut, dependencies=[Depends(_READ)])
def list_requirements(
    keyword: str | None = Query(default=None),
    module: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> RequirementListOut:
    items, total = svc.list_requirements(
        db, keyword=keyword, module=module, status=status, priority=priority, page=page, page_size=page_size
    )
    return RequirementListOut(items=[RequirementOut.model_validate(i) for i in items], total=total)


@router.get("/meta", response_model=RequirementMetaOut, dependencies=[Depends(_READ)])
def requirement_meta(db: Session = Depends(get_db)) -> RequirementMetaOut:
    data = svc.meta()
    return RequirementMetaOut(modules=svc.list_modules(db), priorities=data["priorities"], statuses=data["statuses"])


@router.get("/{requirement_id}", response_model=RequirementOut, dependencies=[Depends(_READ)])
def get_requirement(requirement_id: str, db: Session = Depends(get_db)) -> RequirementOut:
    row = svc.get_requirement(db, requirement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="需求单不存在")
    return RequirementOut.model_validate(row)


@router.post("", response_model=RequirementOut, dependencies=[Depends(_WRITE)])
def create_requirement(payload: RequirementCreate, db: Session = Depends(get_db), user=Depends(get_current_user)) -> RequirementOut:
    return RequirementOut.model_validate(svc.create_requirement(db, payload, operator=_operator_id(user)))


@router.put("/{requirement_id}", response_model=RequirementOut, dependencies=[Depends(_WRITE)])
def update_requirement(requirement_id: str, payload: RequirementUpdate, db: Session = Depends(get_db)) -> RequirementOut:
    row = svc.get_requirement(db, requirement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="需求单不存在")
    return RequirementOut.model_validate(svc.update_requirement(db, row, payload))


@router.patch("/{requirement_id}/status", response_model=RequirementOut, dependencies=[Depends(_WRITE)])
def update_status(requirement_id: str, payload: RequirementStatusUpdate, db: Session = Depends(get_db)) -> RequirementOut:
    row = svc.get_requirement(db, requirement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="需求单不存在")
    return RequirementOut.model_validate(svc.update_requirement(db, row, RequirementUpdate(status=payload.status)))


@router.delete("/{requirement_id}", dependencies=[Depends(_WRITE)])
def delete_requirement(requirement_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    row = svc.get_requirement(db, requirement_id)
    if row is None:
        raise HTTPException(status_code=404, detail="需求单不存在")
    svc.delete_requirement(db, row)
    return {"ok": True}

def _operator_id(user: object) -> str | None:
    """兼容 ORM 对象 / dict / None 的当前用户标识。"""
    if user is None:
        return None
    for attr in ("user_id", "username", "id"):
        value = getattr(user, attr, None)
        if value:
            return str(value)
    if isinstance(user, dict):
        for key in ("user_id", "username", "id"):
            if user.get(key):
                return str(user[key])
    return None
