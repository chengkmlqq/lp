"""ATP 测试线路（单塔基准）API。

权限与 ATP 模块其它端点一致：读 ``atp.read`` / 写 ``atp.manage`` / 执行 ``atp.run``。

端点一览：
- ``GET    /atp/test-lines``                 列表（电压/塔型/避雷线/状态/关键字 + 分页）
- ``POST   /atp/test-lines``                 新建（带回路几何子表）
- ``GET    /atp/test-lines/resolve``         按资产维度反查（前端切换来源时用）
- ``POST   /atp/test-lines:derive``          按维度/资产/真实杆塔派生草稿（干跑）
- ``GET    /atp/test-lines/{id}``            详情（含冻结快照与逐字段来源）
- ``PATCH  /atp/test-lines/{id}``            编辑（改后自动重算快照）
- ``DELETE /atp/test-lines/{id}``            删除（被引用时 409）
- ``POST   /atp/test-lines/{id}/preview``    装配预览（base_tower/profile + 校验）
- ``POST   /atp/test-lines/{id}/clone``      复制为同几何维新样本
- ``GET    /atp/test-lines/{id}/usage``      被哪些资产/用例引用
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.atp_test_line import (
    AtpTestLineCloneRequest,
    AtpTestLineCreateRequest,
    AtpTestLineDeriveRequest,
    AtpTestLineDeriveResponse,
    AtpTestLineDetail,
    AtpTestLineListResponse,
    AtpTestLinePreviewResponse,
    AtpTestLineResolveResponse,
    AtpTestLineUpdateRequest,
    AtpTestLineUsageResponse,
)
from ...services.atp_test_line_service import (
    clone_test_line,
    create_test_line,
    delete_test_line,
    derive_test_line,
    get_test_line_detail,
    list_test_lines,
    list_usage,
    preview_test_line,
    resolve_for_asset,
    update_test_line,
)

router = APIRouter(
    prefix="/atp", tags=["atp-test-lines"], dependencies=[Depends(require_enabled_menu_route)]
)

_READ = Depends(require_any_permission("atp.read", "atp.run", "atp.manage"))
_MANAGE = Depends(require_permission("atp.manage"))


@router.get("/test-lines", response_model=AtpTestLineListResponse)
def list_atp_test_lines_endpoint(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None, description="按代码/名称/描述模糊搜索"),
    voltage_level: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    shield_wire: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    asset_id: str | None = Query(default=None),
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLineListResponse:
    """测试线路列表。"""
    data = list_test_lines(
        db,
        limit=limit,
        offset=offset,
        keyword=keyword,
        voltage_level=voltage_level,
        tower_type=tower_type,
        shield_wire=shield_wire,
        status_value=status_value,
        asset_id=asset_id,
    )
    return AtpTestLineListResponse(**data)


# ⚠️ 必须定义在 ``/{test_line_id}`` 之前：否则 "resolve" 会被当成 id
@router.get("/test-lines/resolve", response_model=AtpTestLineResolveResponse)
def resolve_atp_test_line_endpoint(
    asset_id: str = Query(description="按该资产的维度反查可用测试线路"),
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLineResolveResponse:
    """按资产维度解析测试线路（模型级绑定 → 几何维 → 降级）。"""
    return AtpTestLineResolveResponse(**resolve_for_asset(db, asset_id=asset_id))


@router.post("/test-lines:derive", response_model=AtpTestLineDeriveResponse)
def derive_atp_test_line_endpoint(
    payload: AtpTestLineDeriveRequest,
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLineDeriveResponse:
    """按维度/资产/真实杆塔派生草稿（**干跑，不落库**；返回逐字段来源与阻断项）。"""
    return AtpTestLineDeriveResponse(**derive_test_line(db, payload))


@router.post("/test-lines", response_model=AtpTestLineDetail)
def create_atp_test_line_endpoint(
    payload: AtpTestLineCreateRequest,
    current_user: CurrentUser = _MANAGE,
    db: Session = Depends(get_db),
) -> AtpTestLineDetail:
    """新建测试线路（几何硬约束不通过时返回 400 + blockers）。"""
    data = create_test_line(db, payload=payload, actor_user_id=current_user.user.id)
    return AtpTestLineDetail(**data)


@router.get("/test-lines/{test_line_id}", response_model=AtpTestLineDetail)
def get_atp_test_line_endpoint(
    test_line_id: str,
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLineDetail:
    """测试线路详情（含冻结快照、回路几何、逐字段派生来源）。"""
    return AtpTestLineDetail(**get_test_line_detail(db, test_line_id))


@router.patch("/test-lines/{test_line_id}", response_model=AtpTestLineDetail)
def update_atp_test_line_endpoint(
    test_line_id: str,
    payload: AtpTestLineUpdateRequest,
    current_user: CurrentUser = _MANAGE,
    db: Session = Depends(get_db),
) -> AtpTestLineDetail:
    """编辑测试线路（任何改动都会重算冻结快照）。"""
    data = update_test_line(
        db, test_line_id=test_line_id, payload=payload, actor_user_id=current_user.user.id
    )
    return AtpTestLineDetail(**data)


@router.delete("/test-lines/{test_line_id}")
def delete_atp_test_line_endpoint(
    test_line_id: str,
    _: CurrentUser = _MANAGE,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除测试线路（仍被资产/用例引用时返回 409 并列出引用方）。"""
    delete_test_line(db, test_line_id)
    return {"status": "deleted", "id": test_line_id}


@router.post("/test-lines/{test_line_id}/preview", response_model=AtpTestLinePreviewResponse)
def preview_atp_test_line_endpoint(
    test_line_id: str,
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLinePreviewResponse:
    """装配预览：真实执行时会用的 base_tower/profile 与几何校验结果。"""
    return AtpTestLinePreviewResponse(**preview_test_line(db, test_line_id))


@router.post("/test-lines/{test_line_id}/clone", response_model=AtpTestLineDetail)
def clone_atp_test_line_endpoint(
    test_line_id: str,
    payload: AtpTestLineCloneRequest,
    current_user: CurrentUser = _MANAGE,
    db: Session = Depends(get_db),
) -> AtpTestLineDetail:
    """复制为同几何维新样本（工程参数沿用源线路，只改维度键）。"""
    overrides = {
        key: value
        for key, value in payload.model_dump().items()
        if key not in {"code", "name"} and value is not None
    }
    data = clone_test_line(
        db,
        test_line_id=test_line_id,
        code=payload.code,
        name=payload.name,
        overrides=overrides,
        actor_user_id=current_user.user.id,
    )
    return AtpTestLineDetail(**data)


@router.get("/test-lines/{test_line_id}/usage", response_model=AtpTestLineUsageResponse)
def usage_atp_test_line_endpoint(
    test_line_id: str,
    _: CurrentUser = _READ,
    db: Session = Depends(get_db),
) -> AtpTestLineUsageResponse:
    """引用清单（哪些资产绑定、哪些测试集用例绑定）。"""
    return AtpTestLineUsageResponse(**list_usage(db, test_line_id))
