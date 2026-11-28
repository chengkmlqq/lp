from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...core.file_upload import validate_upload
from ...schemas.atp_asset import (
    AtpAssetCreateRequest,
    AtpAssetDetail,
    AtpAssetFileContentResponse,
    AtpAssetFileListResponse,
    AtpAssetListResponse,
    AtpAssetTreeChild,
    AtpAssetTreeChildrenResponse,
    AtpAssetUpdateRequest,
    AtpAssetPublishRequest,
    AtpAssetVersionCompareResponse,
    AtpAssetVersionListResponse,
    AtpModelListResponse,
    AtpTagOptionsResponse,
    AtpEngineStatusResponse,
)
from ...services.atp_asset_service import (
    activate_asset,
    create_asset,
    deactivate_asset,
    delete_asset,
    get_asset_by_id,
    get_asset_overview_tree,
    get_asset_scene,
    get_asset_slots_view,
    check_asset_slot_coverage,
    get_engine_status,
    get_slot_options,
    list_asset_files,
    list_asset_versions,
    compare_asset_versions,
    list_assets,
    list_asset_tree_children,
    list_models,
    list_tag_options,
    publish_asset,
    read_asset_file_content,
    unpublish_asset,
    # 2026-11-03：形态识别与槽位扫描合并为异步分析任务，接口只做入队
    schedule_asset_analysis,
    serialize_asset,
    upload_asset_files,
    update_asset,
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
    arrester_config: str | None = Query(default=None),
    test_status: str | None = Query(default=None),
    is_published: bool | None = Query(default=None, description="按发布状态过滤：true=已发布，false=未发布；不传=全部"),
    publish_state: str | None = Query(
        default=None,
        description="按发布生命周期过滤：new=新建 / changed=变更 / published=已发布 / offline=下线；不传=全部",
    ),
    tags: list[str] | None = Query(
        default=None,
        description="按标签过滤（可重复传 tags=a&tags=b），多选 OR，命中任一即入选；不传=不过滤",
    ),
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
        arrester_config=arrester_config,
        test_status=test_status,
        is_published=is_published,
        publish_state=publish_state,
        tags=tags,
        limit=limit,
        offset=offset,
    )


@router.get("/models", response_model=AtpModelListResponse)
def get_atp_model_list(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    voltage_level: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    scene_type: str | None = Query(default=None),
    arrester_config: str | None = Query(default=None),
    test_status: str | None = Query(default=None),
    is_published: bool | None = Query(default=None, description="按展示版本的发布状态过滤"),
    publish_state: str | None = Query(
        default=None,
        description="按展示版本的发布生命周期过滤：new/changed/published/offline",
    ),
    tags: list[str] | None = Query(
        default=None,
        description="按标签过滤（可重复传 tags=a&tags=b），多选 OR，命中任一展示版本的标签即入选；不传=不过滤",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpModelListResponse:
    """决策 1：按「模型」聚合的列表（一模型一行）。卡片/列表视图走这里（781 模型），
    详情页版本历史/对比/发布/下线/激活仍走 /assets 与版本接口（1429 版本，口径不变）。
    """
    return list_models(
        db,
        keyword=keyword,
        status_filter=status_filter,
        voltage_level=voltage_level,
        tower_type=tower_type,
        scene_type=scene_type,
        arrester_config=arrester_config,
        test_status=test_status,
        is_published=is_published,
        publish_state=publish_state,
        tags=tags,
        limit=limit,
        offset=offset,
    )


@router.get("/models/tags", response_model=AtpTagOptionsResponse)
def get_atp_model_tag_options(
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTagOptionsResponse:
    """标签候选（2026-11-16）：返回现有版本 tags_json 去重后的全部已用标签，
    供主列表「标签」多选下拉使用；无独立标签字典，未使用过的标签不出现。
    """
    return list_tag_options(db)


@router.get("/assets/tree/children", response_model=AtpAssetTreeChildrenResponse)
def get_atp_asset_tree_children(
    path: str | None = Query(default=None, description="父路径，如 vl:110|tw:guxing；空 = 第一层电压等级"),
    keyword: str | None = Query(default=None, description="树内搜索：返回过滤后的嵌套树（保留命中节点及其全部后代）"),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetTreeChildrenResponse:
    children = [
        AtpAssetTreeChild(**item)
        for item in list_asset_tree_children(db, path=path, keyword=keyword)
    ]
    return AtpAssetTreeChildrenResponse(items=children)


@router.get("/assets/slot-options", response_model=dict)
def get_atp_asset_slot_options_endpoint(
    tower_type: str | None = Query(default=None),
    voltage_level: str | None = Query(default=None),
    scene_type: str | None = Query(default=None),
    arrester_config: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """按维度过滤已扫描模型，返回 work.atp $PARAMETER 槽位并集（参数模板编辑下拉候选）。"""
    return get_slot_options(
        db,
        tower_type=tower_type,
        voltage_level=voltage_level,
        scene_type=scene_type,
        arrester_config=arrester_config,
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
    replace: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """上传模型文件到资产目录。

    支持两种入参：
    1. 传统方式：直接上传文件（files 字段，zip 或散文件）
    2. 两段式：先调用通用 upload-temp 端点获取 temp_file_id，再提交 temp_file_id
    临时文件在消费后自动删除，或由 24h 定时清理任务兜底。

    replace=true（2026-11-10）：重新上传覆盖——先清空该版本的存储目录再写入新文件，
    并重置测试结论（文件已变，旧结论作废）。
    """
    if temp_file_id:
        from ...core.file_upload import _check_upload, describe_temp_upload, get_upload_limit_mb

        name_hint, size_bytes = describe_temp_upload(temp_file_id, current_user.user.id)
        _check_upload(
            size_bytes=size_bytes,
            filename=name_hint,
            max_mb=get_upload_limit_mb("model"),
            allowed_exts=None,
            allowed_exts_label="",
        )
    for upload in files or []:
        validate_upload(upload, purpose="model")
    updated = upload_asset_files(
        db,
        asset_id=asset_id,
        files=files or [],
        temp_file_id=temp_file_id,
        actor_user_id=current_user.user.id,
        replace=replace,
    )
    return AtpAssetDetail(**updated.model_dump())


@router.post("/assets/{asset_id}/format-check", response_model=AtpAssetDetail)
def recheck_atp_asset_format_endpoint(
    asset_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """重新检测模型形态（形态识别 + 槽位扫描，异步执行）。

    2026-11-03 起改为后台任务：判定本身只有毫秒级，但读模型包要走 OSS，同步执行会
    把请求按住 2~3 秒。接口立即返回当前状态（analysis_status=pending），前端轮询
    列表/详情刷新；失败原因落在 analysis_error。
    """
    updated = schedule_asset_analysis(
        db,
        asset_id=asset_id,
        actor_user_id=current_user.user.id,
    )
    return AtpAssetDetail(**updated.model_dump())


@router.get("/assets/{asset_id}/scene")
def get_atp_asset_scene_endpoint(
    asset_id: str,
    entry_file: str = Query(default="work.atp", description="入口 .atp 相对路径，默认 work.atp"),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """解析资产入口 .atp 为 3D 场景 JSON（schema ``lp.atp.scene/1``）。

    前端 Three.js 拓扑图数据源：节点/支路/开关/电源/参数/INCLUDE 块。
    """
    return get_asset_scene(db, asset_id=asset_id, entry_file=entry_file)


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
    offset: int = Query(default=0, ge=0, description="行级懒加载：起始行(0-based)，配合 limit 分段读取全文"),
    limit: int | None = Query(default=None, ge=1, le=100000, description="本次返回的行数上限；不传则返回全文"),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileContentResponse:
    """读取资产目录下文本文件内容（在线查看：行级懒加载全文，不截断）。

    - 不传 offset/limit 时返回全文，兼容 dat 详情等一次性读取场景。
    - 传 offset/limit 时只返回该行区间，配合 total_lines/has_more 前端滚动续读。
    """
    return read_asset_file_content(db, asset_id=asset_id, relative_path=path, offset=offset, limit=limit)


@router.get("/assets/overview-tree")
def get_atp_asset_overview_tree_endpoint(
    _: CurrentUser = Depends(require_permission("atp.view")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """总览思维导图：电压→塔型→场景→避雷器→避雷线→版本（叶子标生效状态）。"""
    return get_asset_overview_tree(db)


@router.get("/assets/export")
def export_atp_assets_endpoint(
    voltage_level: str | None = Query(default=None, description="按电压等级过滤（如 110）；不传 = 全部启用模型"),
    tower_type: str | None = Query(default=None, description="按塔形过滤，可选"),
    scene_type: str | None = Query(default=None, description="按场景过滤（fanji/raoji1/...），可选"),
    arrester_config: str | None = Query(default=None, description="按避雷器措施过滤（noM/M123/...），可选"),
    shield_wire: str | None = Query(default=None, description="按避雷线配置过滤（with/single），可选"),
    layout: str = Query(
        default="legacy",
        pattern="^(legacy|atp_tree)$",
        description="legacy=LP 互导包；atp_tree=D 盘 ATP 目录树（激活版本，直接供 C# 使用）",
    ),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
):
    """批量打包下载 ATP 模型，支持 LP 互导包与 D 盘 ATP 目录树两种布局。"""
    import io

    from fastapi.responses import StreamingResponse

    from ...services.atp_asset_service import export_assets_zip

    data, filename = export_assets_zip(
        db,
        voltage_level=voltage_level,
        tower_type=tower_type,
        scene_type=scene_type,
        arrester_config=arrester_config,
        shield_wire=shield_wire,
        layout=layout,
    )
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@router.get("/assets/{asset_id}/versions", response_model=AtpAssetVersionListResponse)
def list_atp_asset_versions_endpoint(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetVersionListResponse:
    """同维度组合内的版本历史（2026-11-10）：含自身，按创建时间倒序。

    每个版本带发布状态、发布时间、版本描述、测试结论与文件数/总大小。
    """
    return list_asset_versions(db, asset_id=asset_id)


@router.get("/assets/{asset_id}/versions/compare", response_model=AtpAssetVersionCompareResponse)
def compare_atp_asset_versions_endpoint(
    asset_id: str,
    other_id: str = Query(min_length=1),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetVersionCompareResponse:
    """两个版本对比（2026-11-10）：元数据并排 + 文件级差异（按相对路径+大小判定）。"""
    return compare_asset_versions(db, asset_id=asset_id, other_id=other_id)


# --- 目标 1：槽位扫描 / 查看 / 覆盖检测 ---


@router.post("/assets/{asset_id}/scan-slots")
def scan_atp_asset_slots_endpoint(
    asset_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """触发槽位扫描（异步）：与形态识别合并成一个后台分析任务。

    立即返回当前缓存视图（含 analysis_status），前端轮询 slots 接口等新结果；
    这样「扫槽位」也不会因为要读 OSS 而卡住 2~3 秒。
    """
    schedule_asset_analysis(db, asset_id=asset_id, actor_user_id=current_user.user.id)
    return get_asset_slots_view(db, asset_id=asset_id)


@router.get("/assets/{asset_id}/slots")
def get_atp_asset_slots_endpoint(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """返回模型槽位缓存视图（未扫描时 slot_names 为空）。"""
    return get_asset_slots_view(db, asset_id=asset_id)


@router.get("/assets/{asset_id}/coverage")
def get_atp_asset_coverage_endpoint(
    asset_id: str,
    template_id: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> dict:
    """按参数模板检测模型槽位覆盖（目标 3）。template_id 缺省时按资产维度匹配取并集。"""
    return check_asset_slot_coverage(db, asset_id=asset_id, template_id=template_id)


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


@router.post("/assets/{asset_id}/activate", response_model=AtpAssetDetail)
def activate_atp_asset_endpoint(
    asset_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """把该模型设为「生效」（同维度组其他版本自动失效）。"""
    updated = activate_asset(db, asset_id=asset_id, actor_user_id=current_user.user.id)
    return AtpAssetDetail(**updated.model_dump())


@router.post("/assets/{asset_id}/deactivate", response_model=AtpAssetDetail)
def deactivate_atp_asset_endpoint(
    asset_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """取消该模型的生效状态。"""
    updated = deactivate_asset(db, asset_id=asset_id, actor_user_id=current_user.user.id)
    return AtpAssetDetail(**updated.model_dump())


@router.post("/assets/{asset_id}/publish", response_model=AtpAssetDetail)
def publish_atp_asset_endpoint(
    asset_id: str,
    payload: AtpAssetPublishRequest | None = Body(default=None),
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """发布该版本（2026-11-05）：发布后参与仿真定位。

    2026-11-10：支持随发布填写版本描述（release_notes）与标签（tags），均选填，
    兼容旧客户端不传 body。
    2026-11-10（版本切换）：set_active=true 时把该版本一并切成同维度组内唯一生效版本，
    用于「变更版本重新发布后立即上线」。
    """
    updated = publish_asset(
        db,
        asset_id=asset_id,
        release_notes=payload.release_notes if payload else None,
        tags=payload.tags if payload else None,
        set_active=payload.set_active if payload else None,
        actor_user_id=current_user.user.id,
    )
    return AtpAssetDetail(**updated.model_dump())


@router.post("/assets/{asset_id}/unpublish", response_model=AtpAssetDetail)
def unpublish_atp_asset_endpoint(
    asset_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    """下线该版本（2026-11-05）：下线后不参与仿真定位，文件与运行记录保留。"""
    updated = unpublish_asset(db, asset_id=asset_id, actor_user_id=current_user.user.id)
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
