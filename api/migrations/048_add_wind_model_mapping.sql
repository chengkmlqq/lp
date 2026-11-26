-- LP-133：机组型号 → 轮毂中心高度、叶片型号 → 叶片长度 两组映射表。
-- 用途：风电数据准备页面在线维护；单风机计算选择型号时自动带出 hub_height / blade_length。
-- 与维度管理隔离：独立表 + 独立 CRUD 接口（/api/v1/wind-models）。
-- 表同时由 ORM 模型 app/models/wind_model_mapping.py 覆盖（create_all 兜底）。
-- 幂等：表 / 索引已存在时跳过；回滚见 048_add_wind_model_mapping_rollback.sql。
-- MySQL 版见 mysql/048_add_wind_model_mapping.sql

CREATE TABLE IF NOT EXISTS wind_turbine_model (
    id              VARCHAR(32)      NOT NULL PRIMARY KEY,
    code            VARCHAR(128)     NOT NULL,
    name            VARCHAR(255)     NOT NULL,
    hub_height_m    DOUBLE PRECISION NOT NULL,
    description     TEXT,
    is_enabled      BOOLEAN          NOT NULL DEFAULT TRUE,
    sort_order      INTEGER          NOT NULL DEFAULT 0,
    create_user     VARCHAR(64),
    create_date     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    update_user     VARCHAR(64),
    update_date     TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wind_turbine_model_code
    ON wind_turbine_model (code);
CREATE INDEX IF NOT EXISTS idx_wind_turbine_model_enabled
    ON wind_turbine_model (is_enabled);
CREATE INDEX IF NOT EXISTS idx_wind_turbine_model_sort
    ON wind_turbine_model (sort_order);

CREATE TABLE IF NOT EXISTS wind_blade_model (
    id              VARCHAR(32)      NOT NULL PRIMARY KEY,
    code            VARCHAR(128)     NOT NULL,
    name            VARCHAR(255)     NOT NULL,
    blade_length_m  DOUBLE PRECISION NOT NULL,
    description     TEXT,
    is_enabled      BOOLEAN          NOT NULL DEFAULT TRUE,
    sort_order      INTEGER          NOT NULL DEFAULT 0,
    create_user     VARCHAR(64),
    create_date     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    update_user     VARCHAR(64),
    update_date     TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_wind_blade_model_code
    ON wind_blade_model (code);
CREATE INDEX IF NOT EXISTS idx_wind_blade_model_enabled
    ON wind_blade_model (is_enabled);
CREATE INDEX IF NOT EXISTS idx_wind_blade_model_sort
    ON wind_blade_model (sort_order);
