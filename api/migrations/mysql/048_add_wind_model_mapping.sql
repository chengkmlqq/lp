-- LP-133：机组型号 / 叶片型号映射表（MySQL 版，PG 版见 ../048_add_wind_model_mapping.sql）。
-- 用途：风电数据准备页面在线维护；单风机计算选择型号时自动带出 hub_height / blade_length。
-- 幂等：表已存在时跳过；回滚见 048_add_wind_model_mapping_rollback.sql。

CREATE TABLE IF NOT EXISTS wind_turbine_model (
    id              VARCHAR(32)  NOT NULL PRIMARY KEY,
    code            VARCHAR(128) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    hub_height_m    DOUBLE       NOT NULL,
    description     TEXT NULL,
    is_enabled      TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order      INT          NOT NULL DEFAULT 0,
    create_user     VARCHAR(64)  NULL,
    create_date     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_user     VARCHAR(64)  NULL,
    update_date     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ux_wind_turbine_model_code (code),
    KEY idx_wind_turbine_model_enabled (is_enabled),
    KEY idx_wind_turbine_model_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wind_blade_model (
    id              VARCHAR(32)  NOT NULL PRIMARY KEY,
    code            VARCHAR(128) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    blade_length_m  DOUBLE       NOT NULL,
    description     TEXT NULL,
    is_enabled      TINYINT(1)   NOT NULL DEFAULT 1,
    sort_order      INT          NOT NULL DEFAULT 0,
    create_user     VARCHAR(64)  NULL,
    create_date     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_user     VARCHAR(64)  NULL,
    update_date     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY ux_wind_blade_model_code (code),
    KEY idx_wind_blade_model_enabled (is_enabled),
    KEY idx_wind_blade_model_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
