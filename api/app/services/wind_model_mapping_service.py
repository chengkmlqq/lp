"""机组型号 / 叶片型号映射的 CRUD 服务（LP-133）。

供风电数据准备页面在线维护，供单风机计算按型号自动带出参数。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.wind_model_mapping import WindBladeModel, WindTurbineModel
from ..schemas.wind_model_mapping import (
    WindBladeModelCreateRequest,
    WindBladeModelListResponse,
    WindBladeModelSummary,
    WindBladeModelUpdateRequest,
    WindTurbineModelCreateRequest,
    WindTurbineModelListResponse,
    WindTurbineModelSummary,
    WindTurbineModelUpdateRequest,
)

DUPLICATE_CODE_DETAIL = "型号编码已存在"


def serialize_wind_turbine_model(item: WindTurbineModel) -> WindTurbineModelSummary:
    return WindTurbineModelSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        hub_height_m=item.hub_height_m,
        description=item.description,
        is_enabled=item.is_enabled,
        sort_order=item.sort_order,
        create_user=item.create_user,
        create_date=item.create_date,
        update_user=item.update_user,
        update_date=item.update_date,
    )


def serialize_wind_blade_model(item: WindBladeModel) -> WindBladeModelSummary:
    return WindBladeModelSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        blade_length_m=item.blade_length_m,
        description=item.description,
        is_enabled=item.is_enabled,
        sort_order=item.sort_order,
        create_user=item.create_user,
        create_date=item.create_date,
        update_user=item.update_user,
        update_date=item.update_date,
    )


def _apply_filters(
    stmt: Select,
    model: type[WindTurbineModel] | type[WindBladeModel],
    *,
    keyword: str | None,
    enabled: bool | None,
) -> Select:
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        stmt = stmt.where(or_(model.code.ilike(like), model.name.ilike(like)))
    if enabled is not None:
        stmt = stmt.where(model.is_enabled.is_(enabled))
    return stmt


def _list_models(
    db: Session,
    model: type[WindTurbineModel] | type[WindBladeModel],
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    enabled: bool | None,
) -> tuple[list, int]:
    total_stmt = _apply_filters(select(func.count()).select_from(model), model, keyword=keyword, enabled=enabled)
    total = db.scalar(total_stmt) or 0

    rows_stmt = _apply_filters(select(model), model, keyword=keyword, enabled=enabled)
    rows_stmt = (
        rows_stmt.order_by(model.sort_order.asc(), model.code.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(rows_stmt).all()), int(total)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:  # code 唯一索引兜底并发写入
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_CODE_DETAIL
        ) from exc


def _code_taken(
    db: Session,
    model: type[WindTurbineModel] | type[WindBladeModel],
    code: str,
    *,
    exclude_id: str | None = None,
) -> bool:
    stmt = select(model.id).where(model.code == code)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.scalar(stmt) is not None


# ---------------------------------------------------------------------------
# 机组型号
# ---------------------------------------------------------------------------
def list_wind_turbine_models(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    enabled: bool | None,
) -> WindTurbineModelListResponse:
    rows, total = _list_models(
        db,
        WindTurbineModel,
        limit=limit,
        offset=offset,
        keyword=keyword,
        enabled=enabled,
    )
    return WindTurbineModelListResponse(
        items=[serialize_wind_turbine_model(row) for row in rows], total=total
    )


def create_wind_turbine_model(
    db: Session,
    payload: WindTurbineModelCreateRequest,
    *,
    actor_user_id: str | None,
) -> WindTurbineModelSummary:
    if _code_taken(db, WindTurbineModel, payload.code):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_CODE_DETAIL)

    item = WindTurbineModel(
        code=payload.code,
        name=payload.name,
        hub_height_m=payload.hub_height_m,
        description=payload.description,
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(item)
    _commit(db)
    db.refresh(item)
    return serialize_wind_turbine_model(item)


def update_wind_turbine_model(
    db: Session,
    model_id: str,
    payload: WindTurbineModelUpdateRequest,
    *,
    actor_user_id: str | None,
) -> WindTurbineModelSummary | None:
    item = db.get(WindTurbineModel, model_id)
    if item is None:
        return None

    changes = payload.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    if new_code is not None and _code_taken(
        db, WindTurbineModel, new_code, exclude_id=item.id
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_CODE_DETAIL)

    for field_name, value in changes.items():
        if value is not None or field_name == "description":
            setattr(item, field_name, value)
    item.update_user = actor_user_id
    item.update_date = utcnow()
    _commit(db)
    db.refresh(item)
    return serialize_wind_turbine_model(item)


def delete_wind_turbine_model(db: Session, model_id: str) -> bool:
    item = db.get(WindTurbineModel, model_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# 叶片型号
# ---------------------------------------------------------------------------
def list_wind_blade_models(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    enabled: bool | None,
) -> WindBladeModelListResponse:
    rows, total = _list_models(
        db,
        WindBladeModel,
        limit=limit,
        offset=offset,
        keyword=keyword,
        enabled=enabled,
    )
    return WindBladeModelListResponse(
        items=[serialize_wind_blade_model(row) for row in rows], total=total
    )


def create_wind_blade_model(
    db: Session,
    payload: WindBladeModelCreateRequest,
    *,
    actor_user_id: str | None,
) -> WindBladeModelSummary:
    if _code_taken(db, WindBladeModel, payload.code):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_CODE_DETAIL)

    item = WindBladeModel(
        code=payload.code,
        name=payload.name,
        blade_length_m=payload.blade_length_m,
        description=payload.description,
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(item)
    _commit(db)
    db.refresh(item)
    return serialize_wind_blade_model(item)


def update_wind_blade_model(
    db: Session,
    model_id: str,
    payload: WindBladeModelUpdateRequest,
    *,
    actor_user_id: str | None,
) -> WindBladeModelSummary | None:
    item = db.get(WindBladeModel, model_id)
    if item is None:
        return None

    changes = payload.model_dump(exclude_unset=True)
    new_code = changes.get("code")
    if new_code is not None and _code_taken(
        db, WindBladeModel, new_code, exclude_id=item.id
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DUPLICATE_CODE_DETAIL)

    for field_name, value in changes.items():
        if value is not None or field_name == "description":
            setattr(item, field_name, value)
    item.update_user = actor_user_id
    item.update_date = utcnow()
    _commit(db)
    db.refresh(item)
    return serialize_wind_blade_model(item)


def delete_wind_blade_model(db: Session, model_id: str) -> bool:
    item = db.get(WindBladeModel, model_id)
    if item is None:
        return False
    db.delete(item)
    db.commit()
    return True
