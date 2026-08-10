from functools import lru_cache
import re
from typing import Literal
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_name: str = "fquiz-api"
    api_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    api_cors_origin_regex: str | None = None

    database_url: str | None = None
    db_host: str = "127.0.0.1"
    db_port: int = 5434
    db_name: str = "postgres"
    db_schema: str = "public"
    db_username: str = "fquiz"
    db_password: str = "fquiz"
    user_username_column: Literal["username", "user_name"] = "username"
    user_password_column: Literal["password", "password_hash"] = "password_hash"
    user_status_column: Literal["status", "state"] = "status"
    file_vfs_root: str = "./data/vfs"
    minio_enabled: bool = True
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "fquiz-files"
    minio_region: str = "us-east-1"

    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 30

    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_timezone: str = "Asia/Shanghai"
    scheduler_expire_interval_seconds: int = 60
    flower_api_base_url: str = "http://flower:5555"
    flower_api_timeout_seconds: int = 10
    flower_basic_auth: str = ""
    worker_registry_ttl_seconds: int = 90

    # --- 任务实时执行日志（SSE 流式） ---
    task_log_flush_interval_seconds: float = 3.0      # worker 增量 flush 周期
    task_log_redis_db: int = 0                        # 复用 broker 库(0)
    task_log_redis_ttl_seconds: int = 86400           # Redis Stream 数据 TTL（1 天）
    task_log_max_buffer_lines: int = 100_000          # 单任务内存缓冲上限（超限丢最旧行并计数）
    task_log_redis_key_prefix: str = "task_log"       # key 前缀（task_log:{task_id}）
    task_log_sse_heartbeat_seconds: int = 15          # SSE 心跳间隔（配置项，XREAD BLOCK 用之）
    task_log_capture_level: str = "INFO"              # 日志捕获最低级别（root handler setLevel，默认 INFO 及以上）
    task_log_noisy_logger_prefixes: str = (           # 噪音 logger 前缀（逗号分隔），其级别被提升到 WARNING 不入任务日志
        "botocore,urllib3,s3transfer,boto3,celery.worker.strategy"
    )
    # 任务日志 MinIO 保留天数（默认 30 天，0=永久保留，不清理）
    task_log_retain_days: int = 30
    # 审计日志保留天数（默认 90 天，0=永久保留，不清理）
    audit_log_retain_days: int = 90

    wine_binary_path: str = "wine"
    wine_allowed_root: str = "./data/wine"
    wine_default_timeout_seconds: int = 300
    wine_max_timeout_seconds: int = 1800

    atp_engine_mode: Literal["wine", "native"] = "wine"
    atp_engine_executable: str = "atp/tpbig.exe"
    atp_storage_root: str = "./data/wine/atp-models"
    atp_engine_workdir: str = "runs"
    atp_engine_default_timeout_seconds: int = 600
    atp_engine_max_timeout_seconds: int = 3600
    atp_legacy_root: str = "./data/wine/ATP"
    atp_tpbig_executable: str = "ATP/tpbig.exe"
    atp_rjtzl_executable: str = "ATP/rjtzl.exe"
    atp_template_root: str = "./data/wine/ATP/templates"
    atp_run_root: str = "./data/wine/atp-runs"
    atp_egm_subdir: str = "EGM"

    initial_admin_email: str | None = None
    initial_admin_user_id: str = "admin"
    initial_admin_username: str = "管理员"
    initial_admin_password: str | None = None

    debug_mode: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "access_token_expire_minutes",
        "refresh_token_expire_days",
        "db_port",
        "scheduler_expire_interval_seconds",
        "flower_api_timeout_seconds",
        "worker_registry_ttl_seconds",
        "wine_default_timeout_seconds",
        "wine_max_timeout_seconds",
        "atp_engine_default_timeout_seconds",
        "atp_engine_max_timeout_seconds",
        "task_log_redis_ttl_seconds",
        "task_log_max_buffer_lines",
        "task_log_sse_heartbeat_seconds",
    )
    @classmethod
    def validate_positive_numbers(cls, value: int) -> int:
        if value <= 0:
            msg = "Value must be greater than 0"
            raise ValueError(msg)
        return value

    @field_validator("task_log_retain_days", "audit_log_retain_days")
    @classmethod
    def validate_retain_days(cls, value: int) -> int:
        # 0=永久保留（不清理），负数为非法配置
        if value < 0:
            msg = "Value must be greater than or equal to 0 (0=keep forever)"
            raise ValueError(msg)
        return value

    @property
    def cors_origins(self) -> list[str]:
        origins: list[str] = []
        for origin in self.api_cors_origins.split(","):
            normalized = origin.strip()
            if not normalized:
                continue
            if normalized == "*" or "*" in normalized:
                continue
            origins.append(normalized)
        return origins

    @property
    def cors_origin_regex(self) -> str | None:
        regex_parts: list[str] = []
        for origin in self.api_cors_origins.split(","):
            normalized = origin.strip()
            if not normalized:
                continue
            if normalized == "*":
                regex_parts.append(".*")
                continue
            if "*" in normalized:
                wildcard_regex = re.escape(normalized).replace(r"\*", ".*")
                regex_parts.append(f"^{wildcard_regex}$")

        if self.api_cors_origin_regex:
            normalized = self.api_cors_origin_regex.strip()
            if normalized:
                regex_parts.append(normalized)

        if not regex_parts:
            return None
        return "|".join(f"(?:{part})" for part in regex_parts)

    @property
    def resolved_database_url(self) -> str:
        explicit_database_url = (self.database_url or "").strip()
        if explicit_database_url:
            return explicit_database_url

        username = quote_plus(self.db_username.strip())
        password = quote_plus(self.db_password.strip())
        host = self.db_host.strip()
        database = self.db_name.strip()
        return f"postgresql+psycopg://{username}:{password}@{host}:{self.db_port}/{database}"

    @property
    def resolved_db_schema(self) -> str | None:
        schema = self.db_schema.strip()
        if not schema:
            return None
        return schema

    @property
    def resolved_celery_broker_url(self) -> str:
        return (self.celery_broker_url or "redis://redis:6379/0").strip()

    @property
    def resolved_celery_result_backend(self) -> str:
        return (self.celery_result_backend or "redis://redis:6379/1").strip()

    @property
    def resolved_flower_api_base_url(self) -> str:
        value = (self.flower_api_base_url or "").strip().rstrip("/")
        if not value:
            return "http://flower:5555"
        return value

    @property
    def resolved_flower_basic_auth(self) -> str:
        return (self.flower_basic_auth or "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
