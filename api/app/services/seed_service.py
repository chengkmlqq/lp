from dataclasses import dataclass, field
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security import hash_password
from ..models.file_storage import FileStorageBackend, FileStorageMount
from ..models.menu import Menu
from ..models.rbac import Permission, Role
from ..models.system_param import SystemParam
from ..models.tower_model import TowerModel
from ..models.user import User
from .scheduled_task_service import seed_default_scheduled_tasks
from .tower_model_service import seed_tower_models_from_legacy

settings = get_settings()

SEED_RESULT_CATEGORIES = (
    "permissions",
    "roles",
    "role_permissions",
    "menus",
    "role_menus",
    "file_storage_backends",
    "file_storage_mounts",
    "admin_users",
    "legacy_tower_models",
    "atp_param_definitions",
    "dimensions",
    "param_categories",
    "matlab_engine_modules",
)


@dataclass(slots=True)
class SeedCategorySummary:
    created: int = 0
    updated: int = 0
    linked: int = 0
    unchanged: int = 0
    overwritten: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "created": self.created,
            "updated": self.updated,
            "linked": self.linked,
            "unchanged": self.unchanged,
            "overwritten": self.overwritten,
        }


def _build_seed_summary() -> dict[str, SeedCategorySummary]:
    return {
        category: SeedCategorySummary()
        for category in SEED_RESULT_CATEGORIES
    }


@dataclass(slots=True)
class SeedDefaultsResult:
    force: bool
    summary: dict[str, SeedCategorySummary] = field(default_factory=_build_seed_summary)

    @property
    def success(self) -> bool:
        return True

    @property
    def mode(self) -> str:
        return "force_overwrite" if self.force else "missing_only"

    @property
    def overwrote_existing(self) -> bool:
        return any(item.overwritten > 0 for item in self.summary.values())

    def to_response(self) -> dict[str, object]:
        return {
            "success": self.success,
            "force": self.force,
            "mode": self.mode,
            "overwrote_existing": self.overwrote_existing,
            "summary": {
                category: item.to_dict()
                for category, item in self.summary.items()
            },
        }

DEFAULT_PERMISSIONS: dict[str, str] = {
    "user.read": "Read user profile",
    "user.write": "Update user profile",
    "user.manage": "Manage all users and roles",
    "role.read": "Read roles",
    "role.manage": "Manage roles",
    "menu.read": "Read menus",
    "menu.manage": "Manage menus",
    "system_param.read": "Read system parameters",
    "system_param.manage": "Manage system parameters",
    # ⚠️ 2026-09-27 修复：DEFAULT_ROLES.admin 引用了 system_param.runtime，但本字典漏定义 →
    # 全新库调 /admin/system/seed-defaults 直接 KeyError('system_param.runtime')（36 全新部署实测）
    "system_param.runtime": "Read runtime system parameters",
    "admin.system_message": "Manage system messages",
    "ai_chat.read": "Use AI chat",
    "file.read": "Read file mounts and indexed entries",
    "file.manage": "Manage file operations and storage sync",
    "line.read": "Read power lines",
    "line.manage": "Manage power lines",
    "line.create": "Create power lines",
    "line.update": "Update power lines",
    "line.delete": "Delete power lines",
    "line.import": "Import power lines",
    "line.export": "Export power lines",
    "line.map": "Map preview of power lines",
    "tower.read": "Read line towers",
    "tower.manage": "Manage line towers",
    "tower.create": "Create line towers",
    "tower.update": "Update line towers",
    "tower.delete": "Delete line towers",
    "tower.import": "Import line towers",
    "tower.export": "Export line towers",
    "tower_model.read": "Read tower model library",
    "tower_model.manage": "Manage tower model library and images",
    "lightning.read": "Read lightning current events and features",
    "lightning.manage": "Manage lightning current events and data imports",
    # LP-32：风电场地闪密度统计（独立模块，与 lightning.read/manage 完全隔离）
    "wind_lightning_density.read": "Read wind-farm ground flash density batches",
    "wind_lightning_density.manage": "Create and manage wind-farm ground flash density batches",
    # LP-33：风电场数据准备（与 LP-32 完全隔离的独立模块）
    "wind_data_prep.read": "Read wind-farm data preparation batches",
    "wind_data_prep.manage": "Create and manage wind-farm data preparation batches",
    # LP-35：风电场计算（依赖 LP-33 批次，独立菜单与权限点）
    "wind_farm_calc.read": "Read wind-farm calculation jobs",
    "wind_farm_calc.manage": "Create and manage wind-farm calculation jobs",
    # LP-36：单风机计算（独立 matlab-wind worker + 编译产物引擎管理）
    "wind_turbine_calc.read": "Read single wind-turbine calculation jobs",
    "wind_turbine_calc.manage": "Create and manage single wind-turbine calculation jobs",
    "elevation.read": "Read elevation datasets and apply jobs",
    "elevation.manage": "Manage elevation datasets and run altitude apply jobs",
    "atp.read": "Read ATP models and versions",
    # LP-28：atp_assets.py 的 require_permission("atp.view") 引用了此码但此前从未注册，
    # 导致权限覆盖测试长期飘红；补齐注册（接口层鉴权已退化为仅登录，无运行时影响）。
    "atp.view": "View ATP asset overview tree",
    "atp.manage": "Manage ATP models and version artifacts",
    "atp.run": "Run ATP simulations",
    "fl.create": "Create lightning analysis jobs",
    "fl.start": "Start lightning analysis jobs",
    "fl.cancel": "Cancel lightning analysis jobs",
    "fl.delete": "Delete lightning analysis jobs",
    "fl.export": "Export lightning analysis results",
    "fault.create": "Create fault analysis records",
    "fault.delete": "Delete fault analysis records",
    "celery.read": "Read Celery workers, queues, and task statuses",
    "celery.manage": "Manage Celery worker control operations",
    # 2026-09-27 补齐：维度管理接口（dimensions.py / dimension_types.py）要求 dimension.read/manage，
    # 但本字典与 permissions 表均未注册，导致非 admin 角色永远无法通过任何途径获得。
    "dimension.read": "Read dimension types and dimensions",
    "dimension.manage": "Manage dimension types and dimensions",
    # LP-14：平台基础数据包导出 / 导入（维度、系统参数、ATP 模型）
    "platform_data.manage": "Export and import platform base data package",
}

DEFAULT_ROLES: dict[str, dict[str, object]] = {
    "admin": {
        "name": "Administrator",
        "permissions": [
            "user.read",
            "user.write",
            "user.manage",
            "role.read",
            "role.manage",
            "menu.read",
            "menu.manage",
            "system_param.read",
            "system_param.manage",
            "system_param.runtime",
            "admin.system_message",
            "file.read",
            "file.manage",
            "line.read",
            "line.manage",
            "line.create",
            "line.update",
            "line.delete",
            "line.import",
            "line.export",
            "line.map",
            "tower.read",
            "tower.manage",
            "tower.create",
            "tower.update",
            "tower.delete",
            "tower.import",
            "tower.export",
            "tower_model.read",
            "tower_model.manage",
            "lightning.read",
            "lightning.manage",
            "wind_lightning_density.read",
            "wind_lightning_density.manage",
            "wind_data_prep.read",
            "wind_data_prep.manage",
            "wind_farm_calc.read",
            "wind_farm_calc.manage",
            "wind_turbine_calc.read",
            "wind_turbine_calc.manage",
            "elevation.read",
            "elevation.manage",
            "atp.read",
            "atp.view",
            "atp.manage",
            "atp.run",
            "celery.read",
            "celery.manage",
            "ai_chat.read",
            "fl.create",
            "fl.start",
            "fl.cancel",
            "fl.delete",
            "fl.export",
            "fault.create",
            "fault.delete",
            "platform_data.manage",
        ],
    },
    "user": {
        "name": "User",
        "permissions": ["user.read"],
    },
}

DEFAULT_MENUS: list[dict[str, object]] = [
    # ── Top-level (parent_code=None) ─────────────────────────────────
    {
        "code": "admin.overview",
        "name": "系统总览",
        "path": "/admin/overview",
        "icon": "DashboardOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": -10,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "menu.read",
    },
    {
        "code": "admin.power_lines",
        "name": "线路管理",
        "path": "/admin/power-lines",
        "icon": "Network",
        "parent_code": None,
        "type": "menu",
        "sort_order": 0,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "line.read",
    },
    {
        "code": "admin.fault_analysis",
        "name": "故障分析",
        "path": "/admin/fault-analysis",
        "icon": "AuditOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 49,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "line.read",
    },
    {
        "code": "admin.fault_recurrence",
        "name": "故障复现",
        "path": "/admin/fault-recurrence",
        "icon": "Experiment",
        "parent_code": None,
        "type": "menu",
        "sort_order": 50,
        "status": "disabled",
        "visible": False,
        "cacheable": False,
        "permission_code": "line.read",
    },
    {
        "code": "admin.fl_analysis",
        "name": "防雷计算",
        "path": "/fl-analysis",
        "icon": "BarChartOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 50,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "line.manage",
    },
    {
        "code": "admin.lightning_currents",
        "name": "雷电幅值统计",
        "path": "/admin/lightning-currents",
        "icon": "Zap",
        "parent_code": None,
        "type": "menu",
        "sort_order": 52,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "lightning.read",
    },
    {
        "code": "admin.lightning_distribution",
        "name": "地闪密度统计",
        "path": "/admin/lightning-distribution",
        "icon": "Map",
        "parent_code": None,
        "type": "menu",
        "sort_order": 53,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "lightning.read",
    },
    {
        "code": "admin.wind_lightning_density",
        "name": "地闪密度统计",
        "path": "/admin/wind-lightning-density",
        "icon": "CloudOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 54,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "wind_lightning_density.read",
    },
    {
        "code": "admin.wind_data_prep",
        "name": "风电场数据准备",
        "path": "/admin/wind-data-prep",
        "icon": "CloudUploadOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 46,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "wind_data_prep.read",
    },
    {
        "code": "admin.wind_farm_calc",
        "name": "风电场计算",
        "path": "/admin/wind-farm-calc",
        "icon": "ThunderboltOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 47,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "wind_farm_calc.read",
    },
    {
        "code": "admin.docs_view",
        "name": "操作文档",
        "path": "/admin/docs-view",
        "icon": "FileSearchOutlined",
        "parent_code": None,
        "type": "menu",
        "sort_order": 62,
        "status": "enabled",
        "visible": False,
        "cacheable": False,
        "permission_code": "file.read",
    },
    # ── Directories ──────────────────────────────────────────────────
    {
        "code": "admin.basic_data",
        "name": "基础数据",
        "path": None,
        "icon": "FolderOutlined",
        "parent_code": None,
        "type": "directory",
        "sort_order": 97,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": None,
    },
    {
        "code": "admin.system",
        "name": "系统管理",
        "path": None,
        "icon": "Settings2",
        "parent_code": None,
        "type": "directory",
        "sort_order": 99,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": None,
    },
    {
        "code": "admin.debug",
        "name": "系统调试",
        "path": None,
        "icon": "BuildOutlined",
        "parent_code": None,
        "type": "directory",
        "sort_order": 100,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": None,
    },
    # ── Children of 基础数据 (admin.basic_data) ─────────────────────
    {
        "code": "admin.tower_models",
        "name": "杆塔模型管理",
        "path": "/admin/tower-models",
        "icon": "Apartment",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 10,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "tower_model.read",
    },
    {
        "code": "admin.atp_test_sets",
        "name": "测试集管理",
        "path": "/admin/atp-test-sets",
        "icon": "ExperimentOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 21,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "atp.read",
    },
    {
        # 测试线路（单塔基准）：模型测试的默认输入源。
        # API 侧 /api/v1/atp/test-lines 的菜单守卫同时接受本菜单与 admin.atp_models，
        # 避免"只给了测试线路菜单却调不通接口"。
        "code": "admin.atp_test_lines",
        "name": "测试线路管理",
        "path": "/admin/atp-test-lines",
        "icon": "ClusterOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 22,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "atp.read",
    },
    {
        "code": "admin.atp_param_templates",
        "name": "参数模板管理",
        "path": "/admin/atp-param-templates",
        "icon": "BranchesOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 25,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "atp.read",
    },
    {
        "code": "admin.atp_params",
        "name": "ATP计算参数管理",
        "path": "/admin/atp-params",
        "icon": "FunctionOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 26,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "atp.read",
    },
    {
        # 基础数据包「导出」页（交付人员用）：导出表单 + 任务列表。
        # 与导入页共用一个权限码 platform_data.manage（方案 A）。
        "code": "admin.platform_data.export",
        "name": "基础数据包导出",
        "path": "/admin/platform-data/export",
        "icon": "DownloadOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 30,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "platform_data.manage",
    },
    {
        # 基础数据包「导入」页（部署人员用）：仅导入组件，无任务列表。
        "code": "admin.platform_data.import",
        "name": "基础数据包导入",
        "path": "/admin/platform-data/import",
        "icon": "InboxOutlined",
        "parent_code": "admin.basic_data",
        "type": "menu",
        "sort_order": 31,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "platform_data.manage",
    },
    {
        "code": "admin.wind_turbine_calc",
        "name": "单风机计算",
        "path": "/admin/wind-turbine-calc",
        "icon": "ThunderboltFilled",
        "parent_code": None,
        "type": "menu",
        "sort_order": 48,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "wind_turbine_calc.read",
    },
    {
        "code": "admin.elevation",
        "name": "高程数据管理",
        "path": "/admin/elevation",
        "icon": "Database",
        "parent_code": None,
        "type": "menu",
        "sort_order": 55,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "elevation.read",
    },
    # ── 顶层菜单：任务监控（原「系统监控」目录已撤销，任务监控占其位置）──
    {
        "code": "admin.task_monitor",
        "name": "任务监控",
        "path": "/admin/task-monitor",
        "icon": "RadarChart",
        "parent_code": None,
        "type": "menu",
        "sort_order": 98,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "celery.read",
    },
    # ── Children of 系统管理 (admin.system) ──────────────────────────
    {
        "code": "admin.users",
        "name": "用户管理",
        "path": "/admin/users",
        "icon": "Users",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 10,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "user.manage",
    },
    {
        "code": "admin.roles",
        "name": "角色管理",
        "path": "/admin/roles",
        "icon": "ShieldCheck",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 20,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "role.read",
    },
    {
        "code": "admin.menus",
        "name": "菜单管理",
        "path": "/admin/menus",
        "icon": "MenuSquare",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 30,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "menu.read",
    },
    {
        "code": "admin.system_params",
        "name": "系统参数",
        "path": "/admin/system-params",
        "icon": "ControlOutlined",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 40,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "system_param.read",
    },
    {
        "code": "admin.documents",
        "name": "文档管理",
        "path": "/admin/documents",
        "icon": "FileAddOutlined",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 50,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "file.read",
    },
    {
        "code": "admin.dimensions",
        "name": "维度管理",
        "path": "/admin/dimensions",
        "icon": "TableOutlined",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 60,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "system_param.read",
    },
    {
        "code": "admin.scheduled_tasks",
        "name": "定时任务管理",
        "path": "/admin/scheduled-tasks",
        "icon": "CalendarClock",
        "parent_code": "admin.system",
        "type": "menu",
        "sort_order": 70,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "celery.read",
    },
    # ── Children of 系统调试 (admin.debug) ───────────────────────────
    {
        "code": "admin.files",
        "name": "文件管理",
        "path": "/admin/files",
        "icon": "FolderTree",
        "parent_code": "admin.debug",
        "type": "menu",
        "sort_order": 10,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "file.read",
    },
    {
        "code": "admin.matlab_engine",
        "name": "MATLAB引擎管理",
        "path": "/admin/matlab-engine",
        "icon": "ExperimentOutlined",
        "parent_code": "admin.debug",
        "type": "menu",
        "sort_order": 30,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "line.read",
    },
    {
        "code": "admin.ai_chat",
        "name": "AI助手",
        "path": "/admin/ai-chat",
        "icon": "RobotOutlined",
        "parent_code": "admin.debug",
        "type": "menu",
        "sort_order": 40,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "ai_chat.read",
    },
    # ── 2026-11-09 权限策略调整后，type=button 菜单项已失效，LP-28 起不再种子写入 ──
    # 原按钮菜单（约 32 条，如「新建线路」line.create）的三条作用链路均已断开：
    #   1) 接口层 require_*permission 退化为仅登录校验，不再消费 permission_code；
    #   2) 角色配置页只保留目录+页面，勾选页面即按模块前缀自动推导该模块全部权限码；
    #   3) 按钮菜单 path=null / visible=false，侧边栏不渲染。
    # 细粒度权限码仍注册在 DEFAULT_PERMISSIONS / DEFAULT_ROLES 中，不受影响。
    # 防雷改造（2026-09-27：并入种子，带图标；目录含主页路由 /admin/lightning-retrofit）
    # 2026-11-09：图标改为 ToolOutlined（改造施工），与雷电幅值统计的 Zap(ThunderboltOutlined) 区分
    {
        "code": "admin.lightning_retrofit",
        "name": "防雷改造",
        "path": "/admin/lightning-retrofit",
        "icon": "ToolOutlined",
        "parent_code": None,
        "type": "directory",
        "sort_order": 51,
        "status": "enabled",
        "visible": True,
        "cacheable": False,
        "permission_code": "",
    },
]

ROLE_MENU_BINDINGS: dict[str, list[str]] = {
    "admin": [
        "admin.overview",
        "admin.ai_chat",
        "admin.power_lines",
        "admin.fault_analysis",
        "admin.fault_recurrence",
        "admin.fl_analysis",
        "admin.lightning_currents",
        "admin.lightning_distribution",
        "admin.wind_lightning_density",
        "admin.wind_data_prep",
        "admin.wind_farm_calc",
        "admin.wind_turbine_calc",
        "admin.docs_view",
        "admin.basic_data",
        "admin.tower_models",
        "admin.elevation",
        "admin.platform_data.export",
        "admin.platform_data.import",
        "admin.task_monitor",
        "admin.system",
        "admin.users",
        "admin.roles",
        "admin.menus",
        "admin.system_params",
        "admin.documents",
        "admin.dimensions",
        "admin.scheduled_tasks",
        "admin.debug",
        "admin.files",
        "admin.matlab_engine",
    ],
    "user": [],
}


def _default_file_storage_backends() -> list[dict[str, object]]:
    minio_enabled = bool(settings.minio_enabled)
    return [
        {
            "code": "files.vfs.default",
            "name": "本地 VFS 存储",
            "driver_type": "VFS",
            "status": "disabled" if minio_enabled else "enabled",
            "is_default": not minio_enabled,
            "config_json": {"root_dir": settings.file_vfs_root},
        },
        {
            "code": "files.s3.default",
            "name": "S3 对象存储",
            "driver_type": "S3",
            "status": "enabled" if minio_enabled else "disabled",
            "is_default": minio_enabled,
            "config_json": {
                "bucket": settings.minio_bucket,
                "region_name": settings.minio_region,
                "endpoint_url": settings.minio_endpoint,
                "access_key_id": settings.minio_access_key,
                "secret_access_key": settings.minio_secret_key,
            },
        },
    ]


def _default_file_storage_mounts() -> list[dict[str, object]]:
    default_backend_code = "files.s3.default" if settings.minio_enabled else "files.vfs.default"
    return [
        {
            "code": "main",
            "name": "主文件区",
            "backend_code": default_backend_code,
            "mount_path": "/",
            "root_path": "/",
            "is_enabled": True,
        },
    ]


def seed_defaults(db: Session, *, force: bool = False) -> SeedDefaultsResult:
    result = SeedDefaultsResult(force=force)

    try:
        permissions = _seed_permissions(db, result=result, force=force)
        roles = _seed_roles(db, result=result, force=force)
        _seed_role_permissions(db, roles, permissions, result=result, force=force)
        menus = _seed_menus(db, result=result, force=force)
        _seed_role_menus(db, roles, menus, result=result, force=force)
        _seed_file_storage(db, result=result, force=force)
        _seed_initial_admin(db, roles, result=result)
        db.commit()
    except Exception:
        db.rollback()
        raise

    legacy_seed_result = _seed_legacy_tower_models_if_empty(db)
    if legacy_seed_result is not None:
        legacy_summary = result.summary["legacy_tower_models"]
        legacy_summary.created += legacy_seed_result.imported_models
        legacy_summary.updated += legacy_seed_result.updated_models
        legacy_summary.unchanged += legacy_seed_result.skipped_models

    seed_default_scheduled_tasks(db)
    db.commit()

    # ATP 参数注册表种子（SOURCE_VARS → line_binding 翻译；运行期脚本基线）
    _seed_atp_param_definitions(db, result=result, force=force)
    db.commit()

    # 维度种子（ATP/FL 下拉枚举；幂等缺失补齐，force 才覆盖）
    _seed_dimensions(db, result=result, force=force)
    db.commit()

    # 系统参数分类种子（4 分类 + 参数按前缀归类；幂等缺失补齐，force 才覆盖）
    _seed_param_categories(db, result=result, force=force)
    db.commit()

    # LP-36：单风机计算 MATLAB 引擎模块种子（幂等补齐，已存在则不覆盖用户的编辑）
    _seed_matlab_engine_modules(db, result=result)
    db.commit()

    return result

def _seed_matlab_engine_modules(db: Session, *, result: SeedDefaultsResult) -> None:
    """确保 matlab_engine.modules 中含单风机计算模块（幂等，不覆盖已有配置）。"""
    from datetime import datetime, timezone

    key = "matlab_engine.modules"
    param = db.execute(select(SystemParam).where(SystemParam.param_key == key)).scalar_one_or_none()
    if param is None:
        param = SystemParam(
            param_key=key,
            param_name="MATLAB 引擎模块",
            param_value="[]",
            is_encrypted=False,
            description="MATLAB 编译产物引擎模块清单（引擎管理页自动维护）",
            status="enabled",
        )
        db.add(param)
        db.flush()
    modules: list[dict[str, object]] = []
    raw = (param.param_value or "").strip()
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                modules = loaded
        except (json.JSONDecodeError, TypeError):
            modules = []
    if any(isinstance(item, dict) and item.get("slug") == "wind_turbine_calc" for item in modules):
        return
    now = datetime.now(timezone.utc).isoformat()
    modules.append(
        {
            "slug": "wind_turbine_calc",
            "name": "单风机计算",
            "description": "单风机各旋转角屏蔽失效率计算（独立 MATLAB Runtime，matlab-wind 队列）",
            "required_files": ["main_angle.exe", "run_main_angle.sh"],
            "worker_deploy_path": "/app/matlab-wind",
            "worker_queue": "matlab-wind",
            "created_at": now,
            "updated_at": now,
        }
    )
    param.param_value = json.dumps(modules, ensure_ascii=False)
    summary = result.summary.get("matlab_engine_modules")
    if summary is not None:
        summary.created += 1


def _seed_atp_param_definitions(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    from .atp_param_definition_seed import seed_param_definitions  # noqa: PLC0415

    category = result.summary["atp_param_definitions"]
    try:
        stats = seed_param_definitions(db, force=force, operator="seed")
    except Exception:
        # 表尚未创建（首次 init_db 前）时跳过，不阻断其它种子
        db.rollback()
        return
    category.created += stats["created"]
    category.updated += stats["updated"]
    category.unchanged += stats["skipped"]


def _seed_dimensions(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    """ATP/FL 维度种子（dimension_type / dimension_item）。"""
    from .dimension_seed import seed_dimensions  # noqa: PLC0415

    category = result.summary["dimensions"]
    try:
        stats = seed_dimensions(db, force=force, operator="seed")
    except Exception:
        # 表尚未创建（首次 init_db 前）时跳过，不阻断其它种子
        db.rollback()
        return
    category.created += stats["created"]
    category.updated += stats["updated"]
    category.unchanged += stats["skipped"]


def _seed_param_categories(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    """系统参数分类种子（分类 + 参数按前缀归类）。"""
    from .param_category_seed import seed_param_categories  # noqa: PLC0415

    category = result.summary["param_categories"]
    try:
        stats = seed_param_categories(db, force=force, operator="seed")
    except Exception:
        # 表尚未创建时跳过，不阻断其它种子
        db.rollback()
        return
    category.created += stats["categories_created"]
    category.unchanged += stats["categories_skipped"] + stats["params_skipped"]
    category.updated += stats["params_mapped"]


def _seed_permissions(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> dict[str, Permission]:
    category = result.summary["permissions"]
    permission_map: dict[str, Permission] = {}
    for code, name in DEFAULT_PERMISSIONS.items():
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if not permission:
            permission = Permission(code=code, name=name)
            db.add(permission)
            category.created += 1
        elif force:
            if permission.name != name:
                permission.name = name
                category.updated += 1
                category.overwritten += 1
            else:
                category.unchanged += 1
        else:
            category.unchanged += 1
        permission_map[code] = permission

    db.flush()
    for code in DEFAULT_PERMISSIONS:
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if not permission:
            msg = f"Permission not found after seeding: {code}"
            raise RuntimeError(msg)
        permission_map[code] = permission
    return permission_map


def _seed_roles(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> dict[str, Role]:
    category = result.summary["roles"]
    role_map: dict[str, Role] = {}
    for code, role_info in DEFAULT_ROLES.items():
        role_name = str(role_info["name"])
        role = db.scalar(select(Role).where(Role.code == code))
        if not role:
            role = Role(code=code, name=role_name)
            db.add(role)
            db.flush()
            category.created += 1
        elif force:
            if role.name != role_name:
                role.name = role_name
                category.updated += 1
                category.overwritten += 1
            else:
                category.unchanged += 1
        else:
            category.unchanged += 1

        role_map[code] = role
    db.flush()
    return role_map


def _seed_role_permissions(
    db: Session,
    role_map: dict[str, Role],
    permission_map: dict[str, Permission],
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    category = result.summary["role_permissions"]
    for role_code, role_info in DEFAULT_ROLES.items():
        role = role_map.get(role_code)
        if not role:
            continue

        default_permissions = [permission_map[code] for code in role_info["permissions"]]
        existing_codes = {permission.code for permission in role.permissions}
        desired_codes = {permission.code for permission in default_permissions}

        if force:
            if existing_codes != desired_codes:
                role.permissions = default_permissions
                category.updated += 1
                if existing_codes:
                    category.overwritten += 1
            else:
                category.unchanged += 1
            continue

        missing_permissions = [
            permission
            for permission in default_permissions
            if permission.code not in existing_codes
        ]
        if missing_permissions:
            role.permissions = [*role.permissions, *missing_permissions]
            category.linked += len(missing_permissions)
        else:
            category.unchanged += 1

    db.flush()


def _seed_menus(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> dict[str, Menu]:
    category = result.summary["menus"]
    menu_map: dict[str, Menu] = {}
    created_codes: set[str] = set()

    for menu_info in DEFAULT_MENUS:
        code = str(menu_info["code"])
        menu = db.scalar(select(Menu).where(Menu.code == code))
        if not menu:
            menu = Menu(code=code, name=str(menu_info["name"]))
            db.add(menu)
            db.flush()
            created_codes.add(code)
            category.created += 1
        menu_map[code] = menu

    for menu_info in DEFAULT_MENUS:
        code = str(menu_info["code"])
        menu = menu_map[code]
        if code in created_codes:
            _apply_menu_defaults(menu, menu_info=menu_info, menu_map=menu_map)
            continue

        if force:
            if _apply_menu_defaults(menu, menu_info=menu_info, menu_map=menu_map):
                category.updated += 1
                category.overwritten += 1
            else:
                category.unchanged += 1
        else:
            category.unchanged += 1

    db.flush()
    return menu_map


def _apply_menu_defaults(
    menu: Menu,
    *,
    menu_info: dict[str, object],
    menu_map: dict[str, Menu],
) -> bool:
    parent_code = menu_info["parent_code"]
    desired_parent_id = menu_map[str(parent_code)].id if parent_code else None
    desired_name = str(menu_info["name"])
    desired_path = menu_info["path"] if isinstance(menu_info["path"], str) else None
    desired_icon = menu_info["icon"] if isinstance(menu_info["icon"], str) else None
    desired_type = str(menu_info["type"])
    desired_sort_order = int(menu_info["sort_order"])
    desired_status = str(menu_info["status"])
    desired_visible = bool(menu_info["visible"])
    desired_cacheable = bool(menu_info["cacheable"])
    desired_permission_code = (
        str(menu_info["permission_code"])
        if menu_info.get("permission_code") is not None
        else None
    )

    changed = (
        menu.name != desired_name
        or menu.path != desired_path
        or menu.icon != desired_icon
        or menu.parent_id != desired_parent_id
        or menu.type != desired_type
        or menu.sort_order != desired_sort_order
        or menu.status != desired_status
        or menu.visible is not desired_visible
        or menu.cacheable is not desired_cacheable
        or menu.permission_code != desired_permission_code
    )

    menu.name = desired_name
    menu.path = desired_path
    menu.icon = desired_icon
    menu.parent_id = desired_parent_id
    menu.type = desired_type
    menu.sort_order = desired_sort_order
    menu.status = desired_status
    menu.visible = desired_visible
    menu.cacheable = desired_cacheable
    menu.permission_code = desired_permission_code
    return changed


def _seed_role_menus(
    db: Session,
    role_map: dict[str, Role],
    menu_map: dict[str, Menu],
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    category = result.summary["role_menus"]
    for role_code, menu_codes in ROLE_MENU_BINDINGS.items():
        role = role_map.get(role_code)
        if not role:
            continue

        desired_menus = [menu_map[menu_code] for menu_code in menu_codes if menu_code in menu_map]
        existing_codes = {menu.code for menu in role.menus}
        desired_codes = {menu.code for menu in desired_menus}

        if force:
            if existing_codes != desired_codes:
                role.menus = desired_menus
                category.updated += 1
                if existing_codes:
                    category.overwritten += 1
            else:
                category.unchanged += 1
            continue

        missing_menus = [
            menu
            for menu in desired_menus
            if menu.code not in existing_codes
        ]
        if missing_menus:
            role.menus = [*role.menus, *missing_menus]
            category.linked += len(missing_menus)
        else:
            category.unchanged += 1

    db.flush()


def _seed_file_storage(
    db: Session,
    *,
    result: SeedDefaultsResult,
    force: bool,
) -> None:
    backend_category = result.summary["file_storage_backends"]
    mount_category = result.summary["file_storage_mounts"]
    backend_map: dict[str, FileStorageBackend] = {}

    for backend_info in _default_file_storage_backends():
        code = str(backend_info["code"])
        backend = db.scalar(select(FileStorageBackend).where(FileStorageBackend.code == code))
        config_json = backend_info.get("config_json")
        normalized_config = config_json if isinstance(config_json, dict) else {}

        if not backend:
            backend = FileStorageBackend(
                code=code,
                name=str(backend_info["name"]),
                driver_type=str(backend_info["driver_type"]),
                status=str(backend_info["status"]),
                is_default=bool(backend_info["is_default"]),
                config_json=normalized_config,
            )
            db.add(backend)
            db.flush()
            backend_category.created += 1
        else:
            if force:
                changed = _apply_backend_defaults(
                    backend,
                    name=str(backend_info["name"]),
                    driver_type=str(backend_info["driver_type"]),
                    status=str(backend_info["status"]),
                    is_default=bool(backend_info["is_default"]),
                    config_json=normalized_config,
                )
                if changed:
                    backend_category.updated += 1
                    backend_category.overwritten += 1
                else:
                    backend_category.unchanged += 1
            elif code == "files.s3.default":
                # The auto-managed S3 default backend must stay in sync with the
                # current deployment env. If MINIO_* vars changed after the first
                # seed, stale DB config would cause S3 SignatureDoesNotMatch on
                # upload. Reconcile only the known managed S3 fields so we don't
                # clobber user edits to other backends / mounts.
                if _reconcile_s3_default_config(backend, normalized_config):
                    backend_category.updated += 1
                else:
                    backend_category.unchanged += 1
            else:
                backend_category.unchanged += 1

        backend_map[code] = backend

    for mount_info in _default_file_storage_mounts():
        code = str(mount_info["code"])
        backend_code = str(mount_info["backend_code"])
        backend = backend_map.get(backend_code)
        if not backend:
            continue

        mount = db.scalar(select(FileStorageMount).where(FileStorageMount.code == code))
        if not mount:
            mount = FileStorageMount(
                code=code,
                name=str(mount_info["name"]),
                backend_id=backend.id,
                mount_path=str(mount_info["mount_path"]),
                root_path=str(mount_info["root_path"]),
                is_enabled=bool(mount_info["is_enabled"]),
            )
            db.add(mount)
            db.flush()
            mount_category.created += 1
            continue

        if force:
            changed = _apply_mount_defaults(
                mount,
                backend_id=backend.id,
                name=str(mount_info["name"]),
                mount_path=str(mount_info["mount_path"]),
                root_path=str(mount_info["root_path"]),
                is_enabled=bool(mount_info["is_enabled"]),
            )
            if changed:
                mount_category.updated += 1
                mount_category.overwritten += 1
            else:
                mount_category.unchanged += 1
        else:
            mount_category.unchanged += 1


def _apply_backend_defaults(
    backend: FileStorageBackend,
    *,
    name: str,
    driver_type: str,
    status: str,
    is_default: bool,
    config_json: dict[str, object],
) -> bool:
    changed = (
        backend.name != name
        or backend.driver_type != driver_type
        or backend.status != status
        or backend.is_default is not is_default
        or backend.config_json != config_json
    )
    backend.name = name
    backend.driver_type = driver_type
    backend.status = status
    backend.is_default = is_default
    backend.config_json = config_json
    return changed


# Fields of the auto-managed default S3 backend that are reconciled from env on
# every seed. Secret access key is included so a rotated credential is applied
# automatically; it is stored in DB config_json (existing behavior).
_S3_DEFAULT_MANAGED_CONFIG_KEYS = (
    "bucket",
    "region_name",
    "endpoint_url",
    "access_key_id",
    "secret_access_key",
)


def _reconcile_s3_default_config(
    backend: FileStorageBackend,
    desired_config: dict[str, object],
) -> bool:
    """Bring the S3 default backend's managed fields in line with env.

    Only touches the managed S3 keys; leaves other config/user data intact.
    Returns True if any field was actually changed.
    """
    current = backend.config_json if isinstance(backend.config_json, dict) else {}
    changed = False
    for key in _S3_DEFAULT_MANAGED_CONFIG_KEYS:
        desired = desired_config.get(key)
        if current.get(key) != desired:
            current[key] = desired
            changed = True
    if changed:
        backend.config_json = current
    return changed


def _apply_mount_defaults(
    mount: FileStorageMount,
    *,
    backend_id: int,
    name: str,
    mount_path: str,
    root_path: str,
    is_enabled: bool,
) -> bool:
    changed = (
        mount.name != name
        or mount.backend_id != backend_id
        or mount.mount_path != mount_path
        or mount.root_path != root_path
        or mount.is_enabled is not is_enabled
    )
    mount.name = name
    mount.backend_id = backend_id
    mount.mount_path = mount_path
    mount.root_path = root_path
    mount.is_enabled = is_enabled
    return changed


def _seed_initial_admin(
    db: Session,
    role_map: dict[str, Role],
    *,
    result: SeedDefaultsResult,
) -> None:
    category = result.summary["admin_users"]
    if not settings.initial_admin_email or not settings.initial_admin_password:
        return

    admin_role = role_map.get("admin")
    if not admin_role:
        return

    admin_user_id = settings.initial_admin_user_id.strip()
    if not admin_user_id:
        return

    admin_email = settings.initial_admin_email.lower()
    user = db.scalar(select(User).where((User.id == admin_user_id) | (User.email == admin_email)))
    created = False
    if not user:
        user = User(
            id=admin_user_id,
            email=admin_email,
            username=settings.initial_admin_username,
            password_hash=hash_password(settings.initial_admin_password),
            status="ENABLED",
        )
        db.add(user)
        db.flush()
        category.created += 1
        created = True

    role_codes = {role.code for role in user.roles}
    if "admin" not in role_codes:
        user.roles.append(admin_role)
        category.linked += 1
    elif not created:
        category.unchanged += 1


def _seed_legacy_tower_models_if_empty(db: Session):
    existing_count = int(db.scalar(select(func.count()).select_from(TowerModel)) or 0)
    if existing_count > 0:
        return None

    actor = db.scalar(select(User).where(User.id == settings.initial_admin_user_id))
    if actor is None:
        actor = db.scalar(select(User).where(User.username == settings.initial_admin_username))
    if actor is None:
        actor = db.scalar(select(User).order_by(User.created_at.asc()))
    if actor is None:
        return None

    try:
        return seed_tower_models_from_legacy(
            db,
            actor=actor,
            overwrite_existing=False,
        )
    except Exception:
        db.rollback()
        return None
