from collections.abc import Generator
import logging
from typing import Any

from sqlalchemy import JSON, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 可移植 JSON 列类型：PostgreSQL 上保持 JSONB（与既有 schema / 迁移完全一致），
# 其他方言（如单元测试使用的 SQLite）自动回退为通用 JSON，使 Base.metadata.create_all
# 能建表。历史遗留问题：模型直接用 postgresql.JSONB，导致测试在 SQLite 上
# `create_all` 抛 `UnsupportedCompilationError: can't render element of type JSONB`，
# ~120 个测试因此长期无法执行（详见 LP 权限/回归治理）。
JsonColumn = JSON().with_variant(JSONB(), "postgresql")

database_url = settings.resolved_database_url

connect_args: dict[str, Any] = {}
if database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif database_url.startswith("postgresql"):
    schema = settings.resolved_db_schema
    if schema:
        connect_args["options"] = f"-csearch_path={schema}"

# SQLite 的默认连接池（内存库为 SingletonThreadPool）不接受 pool_size/max_overflow，
# 传了会直接抛 `TypeError: Invalid argument(s) 'max_overflow'` —— 这也是长期没人跑得通
# 全量单测的原因之一（conftest 默认就是内存 SQLite）。仅在非 SQLite 方言下启用连接池参数。
pool_kwargs: dict[str, Any] = {}
if not database_url.startswith("sqlite"):
    pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
    }

engine = create_engine(
    database_url,
    # 开启 pre_ping：长耗时任务（ATP 引擎单塔可达数分钟）跨越 pool_recycle=300s 时，
    # 连接可能已被服务端/网络层丢弃；无 pre_ping 时取到的是死连接，复用会偶发
    # `server closed the connection unexpectedly`，导致整任务被误标 failed（celery 层
    # 其实已 succeeded，2026-09-16 并发4 时分片1 实测）。pre_ping 每次取连先 SELECT 1
    # 探测，死连接自动重连，避免该偶发失败。代价 ~0.1s/请求，对长任务可接受。
    pool_pre_ping=True,
    connect_args=connect_args,
    **pool_kwargs,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def _ensure_user_pk_column_compatibility() -> None:
    """
    Keep legacy databases compatible with the current ORM mapping.

    Historical deployments may still use `users.id` as the primary key column.
    Current models and foreign keys uniformly target `users.user_id`.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("users", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("users", schema=schema)
        }
        if "user_id" in column_names or "id" not in column_names:
            return

        connection.execute(text("ALTER TABLE users RENAME COLUMN id TO user_id"))
        logger.warning(
            "Detected legacy users.id primary key; renamed to users.user_id for schema compatibility.",
        )


def _ensure_user_timestamp_column_compatibility() -> None:
    """
    Keep `users` timestamp columns aligned with the current ORM mapping.

    Legacy deployments may still use `create_date` / `update_date`,
    while current models expect `created_at` / `updated_at`.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("users", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("users", schema=schema)
        }

        if "created_at" not in column_names and "create_date" in column_names:
            connection.execute(text("ALTER TABLE users RENAME COLUMN create_date TO created_at"))
            logger.warning(
                "Detected legacy users.create_date; renamed to users.created_at for schema compatibility.",
            )
            column_names.remove("create_date")
            column_names.add("created_at")

        if "updated_at" not in column_names and "update_date" in column_names:
            connection.execute(text("ALTER TABLE users RENAME COLUMN update_date TO updated_at"))
            logger.warning(
                "Detected legacy users.update_date; renamed to users.updated_at for schema compatibility.",
            )

def _rename_user_column_if_needed(
    connection: Any,
    *,
    column_names: set[str],
    target_column: str,
    legacy_candidates: tuple[str, ...],
) -> set[str]:
    if target_column in column_names:
        return column_names

    legacy_column = next(
        (candidate for candidate in legacy_candidates if candidate in column_names),
        None,
    )
    if not legacy_column:
        return column_names

    connection.execute(
        text(f"ALTER TABLE users RENAME COLUMN {legacy_column} TO {target_column}"),
    )
    logger.warning(
        "Detected legacy users.%s; renamed to users.%s for schema compatibility.",
        legacy_column,
        target_column,
    )
    column_names.remove(legacy_column)
    column_names.add(target_column)
    return column_names


def _ensure_user_audit_column_compatibility() -> None:
    """
    Keep `users` audit columns aligned with the current ORM mapping.

    Some legacy deployments use `create_by` / `created_by` and
    `update_by` / `updated_by`, or may miss these nullable columns.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("users", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("users", schema=schema)
        }

        column_names = _rename_user_column_if_needed(
            connection,
            column_names=column_names,
            target_column="create_user",
            legacy_candidates=("create_by", "created_by"),
        )
        column_names = _rename_user_column_if_needed(
            connection,
            column_names=column_names,
            target_column="update_user",
            legacy_candidates=("update_by", "updated_by"),
        )

        if "create_user" not in column_names:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS create_user VARCHAR(64)"),
            )
            logger.warning(
                "Detected missing users.create_user; added nullable create_user column for schema compatibility.",
            )
            column_names.add("create_user")

        if "update_user" not in column_names:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS update_user VARCHAR(64)"),
            )
            logger.warning(
                "Detected missing users.update_user; added nullable update_user column for schema compatibility.",
            )


def _ensure_elevation_dataset_column_compatibility() -> None:
    """
    Keep `elevation_dataset` columns aligned with the current ORM mapping.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("elevation_dataset", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("elevation_dataset", schema=schema)
        }

        if "dataset_dir" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS dataset_dir VARCHAR(2048)"),
            )
            connection.execute(
                text("UPDATE elevation_dataset SET dataset_dir = '/elevation/datasets/' || code WHERE dataset_dir IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE elevation_dataset ALTER COLUMN dataset_dir SET NOT NULL"),
            )
            logger.warning(
                "Detected missing elevation_dataset.dataset_dir; added and backfilled from dataset code.",
            )

        if "usage_status" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS usage_status VARCHAR(32)"),
            )
            connection.execute(
                text("UPDATE elevation_dataset SET usage_status = 'idle' WHERE usage_status IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE elevation_dataset ALTER COLUMN usage_status SET NOT NULL"),
            )
            logger.warning(
                "Detected missing elevation_dataset.usage_status; added with default 'idle'.",
            )

        if "analysis_task_id" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS analysis_task_id VARCHAR(128)"),
            )
            logger.warning(
                "Detected missing elevation_dataset.analysis_task_id; added nullable analysis task id column.",
            )

        if "analysis_status" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(32)"),
            )
            connection.execute(
                text("UPDATE elevation_dataset SET analysis_status = 'not_started' WHERE analysis_status IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE elevation_dataset ALTER COLUMN analysis_status SET NOT NULL"),
            )
            logger.warning(
                "Detected missing elevation_dataset.analysis_status; added with default 'not_started'.",
            )

        if "analysis_error_message" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS analysis_error_message TEXT"),
            )
            logger.warning(
                "Detected missing elevation_dataset.analysis_error_message; added nullable analysis error column.",
            )

        if "analysis_started_at" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS analysis_started_at TIMESTAMPTZ"),
            )
            logger.warning(
                "Detected missing elevation_dataset.analysis_started_at; added nullable analysis start time column.",
            )

        if "analysis_finished_at" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS analysis_finished_at TIMESTAMPTZ"),
            )
            logger.warning(
                "Detected missing elevation_dataset.analysis_finished_at; added nullable analysis finish time column.",
            )

        if "terrain_status" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_status VARCHAR(32)"),
            )
            connection.execute(
                text(
                    """
                    UPDATE elevation_dataset
                    SET terrain_status = CASE
                        WHEN lower(coalesce(file_format, '')) IN ('img', 'tif', 'tiff') THEN 'pending'
                        ELSE 'not_supported'
                    END
                    WHERE terrain_status IS NULL
                    """
                ),
            )
            connection.execute(
                text("ALTER TABLE elevation_dataset ALTER COLUMN terrain_status SET NOT NULL"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_status; added and backfilled by file format.",
            )

        if "terrain_task_id" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_task_id VARCHAR(128)"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_task_id; added nullable terrain task id column.",
            )

        if "terrain_error_message" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_error_message TEXT"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_error_message; added nullable terrain error column.",
            )

        if "terrain_root_path" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_root_path VARCHAR(2048)"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_root_path; added nullable terrain root path column.",
            )

        if "terrain_url_template" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_url_template VARCHAR(2048)"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_url_template; added nullable terrain URL template column.",
            )

        if "terrain_min_zoom" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_min_zoom INTEGER"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_min_zoom; added nullable terrain min zoom column.",
            )

        if "terrain_max_zoom" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_max_zoom INTEGER"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_max_zoom; added nullable terrain max zoom column.",
            )

        if "terrain_bounds" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_bounds JSON"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_bounds; added nullable terrain bounds column.",
            )

        if "terrain_metadata" not in column_names:
            connection.execute(
                text("ALTER TABLE elevation_dataset ADD COLUMN IF NOT EXISTS terrain_metadata JSON"),
            )
            logger.warning(
                "Detected missing elevation_dataset.terrain_metadata; added nullable terrain metadata column.",
            )


def _ensure_atp_simulation_run_column_compatibility() -> None:
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("atp_simulation_run", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("atp_simulation_run", schema=schema)
        }
        if "task_id" in column_names:
            return

        connection.execute(
            text("ALTER TABLE atp_simulation_run ADD COLUMN IF NOT EXISTS task_id VARCHAR(128)"),
        )
        logger.warning(
            "Detected missing atp_simulation_run.task_id; added nullable task id column.",
        )


def _ensure_atp_asset_column_compatibility() -> None:
    """
    Keep `atp_asset` columns aligned with the current ORM mapping.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("atp_asset", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("atp_asset", schema=schema)
        }

        if "storage_mount_code" not in column_names:
            connection.execute(
                text("ALTER TABLE atp_asset ADD COLUMN IF NOT EXISTS storage_mount_code VARCHAR(64)"),
            )
            logger.warning(
                "Detected missing atp_asset.storage_mount_code; added nullable mount code column.",
            )

        if "storage_root_path" not in column_names:
            connection.execute(
                text("ALTER TABLE atp_asset ADD COLUMN IF NOT EXISTS storage_root_path VARCHAR(2048)"),
            )
            logger.warning(
                "Detected missing atp_asset.storage_root_path; added nullable storage root path column.",
            )


def _ensure_atp_asset_run_column_compatibility() -> None:
    """
    Keep `atp_asset_run` columns aligned with the current ORM mapping.

    ⚠️ 2026-09-19 生产实测：`stderr_text` / `timed_out` 由模型与执行侧写入，
    但迁移 019 未执行到生产库 → SELECT 报 UndefinedColumn（ATP 运行记录接口 500）。
    迁移写了却漏执行是反复出现的故障类，故在此加启动自愈（与 atp_asset 等同款约定）。
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("atp_asset_run", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("atp_asset_run", schema=schema)
        }

        if "stderr_text" not in column_names:
            connection.execute(
                text("ALTER TABLE atp_asset_run ADD COLUMN IF NOT EXISTS stderr_text TEXT"),
            )
            logger.warning(
                "Detected missing atp_asset_run.stderr_text; added nullable engine stderr column.",
            )

        if "timed_out" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE atp_asset_run "
                    "ADD COLUMN IF NOT EXISTS timed_out BOOLEAN NOT NULL DEFAULT false"
                ),
            )
            logger.warning(
                "Detected missing atp_asset_run.timed_out; added boolean timeout flag column.",
            )


def _ensure_atp_param_template_column_compatibility() -> None:
    """
    Keep `atp_param_template` columns aligned with the current ORM mapping.

    `defaults_json`（测试默认参数集，迁移 020）同样需要启动自愈，避免漏执行迁移
    导致参数模板接口 500。
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("atp_param_template", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("atp_param_template", schema=schema)
        }

        if "defaults_json" not in column_names:
            connection.execute(
                text(
                    "ALTER TABLE atp_param_template "
                    "ADD COLUMN IF NOT EXISTS defaults_json JSONB NOT NULL DEFAULT '{}'::jsonb"
                ),
            )
            logger.warning(
                "Detected missing atp_param_template.defaults_json; added JSONB defaults column.",
            )


def _ensure_tower_model_column_compatibility() -> None:
    """
    Keep `tower_model` columns aligned with the current ORM mapping.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("tower_model", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("tower_model", schema=schema)
        }

        if "source_tag" not in column_names:
            connection.execute(
                text("ALTER TABLE tower_model ADD COLUMN IF NOT EXISTS source_tag VARCHAR(64)"),
            )
            logger.warning(
                "Detected missing tower_model.source_tag; added nullable source tag column.",
            )

        if "sort_order" not in column_names:
            connection.execute(
                text("ALTER TABLE tower_model ADD COLUMN IF NOT EXISTS sort_order INTEGER"),
            )
            connection.execute(
                text("UPDATE tower_model SET sort_order = 0 WHERE sort_order IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE tower_model ALTER COLUMN sort_order SET NOT NULL"),
            )
            logger.warning(
                "Detected missing tower_model.sort_order; added with default 0.",
            )

        if "default_raw_json" not in column_names:
            connection.execute(
                text("ALTER TABLE tower_model ADD COLUMN IF NOT EXISTS default_raw_json JSON"),
            )
            connection.execute(
                text("UPDATE tower_model SET default_raw_json = '{}'::json WHERE default_raw_json IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE tower_model ALTER COLUMN default_raw_json SET NOT NULL"),
            )
            logger.warning(
                "Detected missing tower_model.default_raw_json; added with default empty JSON.",
            )


def _ensure_tower_profile_column_compatibility() -> None:
    """
    Keep `tower_profile` columns aligned with the current ORM mapping.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("tower_profile", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("tower_profile", schema=schema)
        }

        if "structure_kind" not in column_names:
            connection.execute(
                text("ALTER TABLE tower_profile ADD COLUMN IF NOT EXISTS structure_kind VARCHAR(64)"),
            )
            logger.warning(
                "Detected missing tower_profile.structure_kind; added nullable structure kind column.",
            )

        if "stroke_mode" not in column_names:
            connection.execute(
                text("ALTER TABLE tower_profile ADD COLUMN IF NOT EXISTS stroke_mode VARCHAR(32)"),
            )
            logger.warning(
                "Detected missing tower_profile.stroke_mode; added nullable stroke mode column.",
            )


def _ensure_user_login_lockout_column_compatibility() -> None:
    """
    Keep `users` login lockout columns aligned with the current ORM mapping.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("users", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("users", schema=schema)
        }

        if "failed_login_attempts" not in column_names:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER"),
            )
            connection.execute(
                text("UPDATE users SET failed_login_attempts = 0 WHERE failed_login_attempts IS NULL"),
            )
            connection.execute(
                text("ALTER TABLE users ALTER COLUMN failed_login_attempts SET NOT NULL"),
            )
            logger.warning(
                "Detected missing users.failed_login_attempts; added with default 0.",
            )

        if "failed_login_locked_until" not in column_names:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_locked_until TIMESTAMP"),
            )
            logger.warning(
                "Detected missing users.failed_login_locked_until; added nullable lockout time column.",
            )


def _ensure_user_email_nullable() -> None:
    """
    Ensure `users.email` column is nullable to match the current ORM mapping.

    The email field is optional in the application layer but may have been
    created with NOT NULL constraint in legacy deployments.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("users", schema=schema):
            return

        columns = db_inspector.get_columns("users", schema=schema)
        email_column = next((col for col in columns if col["name"] == "email"), None)

        if email_column and not email_column.get("nullable", True):
            connection.execute(text("ALTER TABLE users ALTER COLUMN email DROP NOT NULL"))
            logger.warning(
                "Detected users.email with NOT NULL constraint; removed constraint to allow optional email.",
            )


def _ensure_dimension_item_type_id_column_compatibility() -> None:
    """
    Keep `dimension_item.type_id` column aligned with the current ORM mapping.

    The ORM expects a `type_id` FK column (LP-207: 维度类型管理), but legacy
    deployments created `dimension_item` before it existed and never ran the
    `add_dimension_type.sql` migration. Without it, every SELECT on
    `dimension_item` fails with "column dimension_item.type_id does not exist".
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("dimension_item", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("dimension_item", schema=schema)
        }
        if "type_id" in column_names:
            return

        # 依赖 dimension_type 表存在才能建 FK；若该表尚不存在（如首次从旧库升级时，
        # dimension_type 要等 create_all 创建），则先加无 FK 的列，避免引导失败。
        if db_inspector.has_table("dimension_type", schema=schema):
            connection.execute(
                text(
                    "ALTER TABLE dimension_item ADD COLUMN IF NOT EXISTS type_id VARCHAR(32) "
                    "REFERENCES dimension_type(id) ON DELETE RESTRICT"
                )
            )
        else:
            connection.execute(
                text("ALTER TABLE dimension_item ADD COLUMN IF NOT EXISTS type_id VARCHAR(32)")
            )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS idx_dimension_item_type_id ON dimension_item(type_id)")
        )
        logger.warning(
            "Detected missing dimension_item.type_id; added type_id FK column for ORM compatibility.",
        )


def _ensure_lightning_distribution_lp_image_column_compatibility() -> None:
    """
    Keep `lightning_distribution.lp_image_object_key` column aligned with the ORM mapping.

    The ORM expects a `lp_image_object_key` column (LP-224: LP 桌面端 Voronoi 分区密度图),
    but legacy deployments created `lightning_distribution` before it existed and never ran
    the `012_add_lp_image_object_key.sql` migration. Without it, every SELECT on
    `lightning_distribution` fails with "column lightning_distribution.lp_image_object_key does not exist".
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("lightning_distribution", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("lightning_distribution", schema=schema)
        }
        if "lp_image_object_key" in column_names:
            return

        connection.execute(
            text(
                "ALTER TABLE lightning_distribution "
                "ADD COLUMN IF NOT EXISTS lp_image_object_key VARCHAR(512)"
            )
        )
        logger.warning(
            "Detected missing lightning_distribution.lp_image_object_key; "
            "added column for ORM compatibility.",
        )


def _ensure_lightning_density_backfill_async_column_compatibility() -> None:
    """
    Keep `lightning_density_backfill_task` async/status + circle-image columns
    aligned with the ORM mapping.

    The ORM now expects status/progress/task_id/error_message/circle_image_object_key
    columns, but deployments created the table before they existed (migration 021).
    Without them, every SELECT on `lightning_density_backfill_task` fails.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("lightning_density_backfill_task", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("lightning_density_backfill_task", schema=schema)
        }
        additions: list[tuple[str, str]] = [
            ("status", "VARCHAR(32) NOT NULL DEFAULT 'completed'"),
            ("progress", "INTEGER NOT NULL DEFAULT 0"),
            ("task_id", "VARCHAR(255)"),
            ("error_message", "TEXT"),
            ("circle_image_object_key", "VARCHAR(512)"),
        ]
        pending = [(name, ddl) for name, ddl in additions if name not in column_names]
        if not pending:
            return

        for name, ddl in pending:
            connection.execute(
                text(
                    f"ALTER TABLE lightning_density_backfill_task "
                    f"ADD COLUMN IF NOT EXISTS {name} {ddl}"
                )
            )
        logger.warning(
            "Detected missing lightning_density_backfill_task columns (%s); "
            "added columns for ORM compatibility.",
            ", ".join(name for name, _ in pending),
        )


def _ensure_system_param_encrypted_column_compatibility() -> None:
    """
    Keep `system_params.is_encrypted` column aligned with the ORM mapping (LP-310).

    Legacy deployments created `system_params` before the encrypted-storage feature
    existed; without the column every SELECT on `system_params` fails with
    "column system_params.is_encrypted does not exist". Existing rows stay plaintext
    (default FALSE) — no data migration is performed by design.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("system_params", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("system_params", schema=schema)
        }
        if "is_encrypted" in column_names:
            return

        connection.execute(
            text(
                "ALTER TABLE system_params "
                "ADD COLUMN IF NOT EXISTS is_encrypted BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        logger.warning(
            "Detected missing system_params.is_encrypted; added column with default FALSE.",
        )


def _ensure_fault_analysis_upload_files_column_compatibility() -> None:
    """
    Keep `fault_analysis.upload_files` column aligned with the ORM mapping (LP-316).

    Legacy deployments created `fault_analysis` before the discrimination-engine
    integration existed; without the column every INSERT/SELECT on the new JSON
    field fails. Existing rows default to `{}` (no uploaded inputs).
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("fault_analysis", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("fault_analysis", schema=schema)
        }
        if "upload_files" in column_names:
            return

        connection.execute(
            text(
                "ALTER TABLE fault_analysis "
                "ADD COLUMN IF NOT EXISTS upload_files JSONB NOT NULL DEFAULT '{}'::jsonb"
            )
        )
        logger.warning(
            "Detected missing fault_analysis.upload_files; added JSON column with default {}.",
        )


def _ensure_fault_analysis_progress_column_compatibility() -> None:
    """
    Add `fault_analysis.progress` column if missing (for existing deployments).

    The progress field tracks async diagnosis task completion percentage (0-100).
    Existing rows default to 0 (no progress information).
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("fault_analysis", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("fault_analysis", schema=schema)
        }
        if "progress" in column_names:
            return

        connection.execute(
            text(
                "ALTER TABLE fault_analysis "
                "ADD COLUMN IF NOT EXISTS progress FLOAT NOT NULL DEFAULT 0"
            )
        )
        logger.warning(
            "Detected missing fault_analysis.progress; added FLOAT column with default 0.",
        )


def _ensure_fault_analysis_task_id_column_compatibility() -> None:
    """
    Add `fault_analysis.task_id` column if missing (for existing deployments).

    The task_id stores the Celery task id of the async diagnosis task, so the
    frontend can trace the execution log for a given analysis.
    """
    if not database_url.startswith("postgresql"):
        return

    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        db_inspector = inspect(connection)
        if not db_inspector.has_table("fault_analysis", schema=schema):
            return

        column_names = {
            column["name"]
            for column in db_inspector.get_columns("fault_analysis", schema=schema)
        }
        if "task_id" in column_names:
            return

        connection.execute(
            text(
                "ALTER TABLE fault_analysis "
                "ADD COLUMN IF NOT EXISTS task_id VARCHAR(128)"
            )
        )
        logger.warning(
            "Detected missing fault_analysis.task_id; added nullable task id column.",
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_system_message_link_url_column_compatibility() -> None:
    """2026-10-02：system_messages.link_url（消息点击跳转目标）。"""
    if not database_url.startswith("postgresql"):
        return
    schema = settings.resolved_db_schema
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("system_messages", schema=schema):
            return
        columns = {c["name"] for c in inspector.get_columns("system_messages", schema=schema)}
        if "link_url" not in columns:
            connection.execute(
                text("ALTER TABLE system_messages ADD COLUMN IF NOT EXISTS link_url VARCHAR(255)"),
            )
            logger.info("system_messages.link_url column added")


def init_db() -> None:
    # Import models so metadata includes every table before create_all.
    from ..models import (
        atp_asset,
        atp_param_definition,
        audit_log,
        auth_session,
        dimension_item,
        elevation,
        fault_analysis,
        file_storage,
        fl_analysis,
        lightning_amplitude,
        lightning_distribution,
        line,
        line_tower,
        menu,
        object_group,
        param_category,
        rbac,
        scheduled_task,
        system_param,
        task_history,
        tower_analysis,
        tower_circuit,
        tower_lightning_result,
        tower_model,
        tower_profile,
        user,
        worker_registry,
    )  # noqa: F401
    _ensure_user_pk_column_compatibility()
    _ensure_user_timestamp_column_compatibility()
    _ensure_user_audit_column_compatibility()
    _ensure_user_login_lockout_column_compatibility()
    _ensure_user_email_nullable()
    _ensure_elevation_dataset_column_compatibility()
    _ensure_atp_simulation_run_column_compatibility()
    _ensure_atp_asset_column_compatibility()
    _ensure_atp_asset_run_column_compatibility()
    _ensure_atp_param_template_column_compatibility()
    _ensure_tower_model_column_compatibility()
    _ensure_tower_profile_column_compatibility()
    _ensure_dimension_item_type_id_column_compatibility()
    _ensure_lightning_distribution_lp_image_column_compatibility()
    _ensure_lightning_density_backfill_async_column_compatibility()
    _ensure_system_param_encrypted_column_compatibility()
    _ensure_fault_analysis_upload_files_column_compatibility()
    _ensure_fault_analysis_progress_column_compatibility()
    _ensure_fault_analysis_task_id_column_compatibility()
    _ensure_system_message_link_url_column_compatibility()
    Base.metadata.create_all(bind=engine)
