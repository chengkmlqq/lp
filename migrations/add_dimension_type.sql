-- Migration: add_dimension_type.sql
-- Adds the dimension_type table and a type_id FK on dimension_item.
-- LP-207: 维度管理页面改造 —— 新增维度类型管理，左右布局对齐系统参数页。

CREATE TABLE IF NOT EXISTS dimension_type (
    id          VARCHAR(32) PRIMARY KEY,                    -- uuid4 hex
    code        VARCHAR(64) NOT NULL UNIQUE,                -- 类型编码（如 voltage_level）
    name        VARCHAR(128) NOT NULL,                      -- 类型名称（如 电压等级）
    parent_id   VARCHAR(32) REFERENCES dimension_type(id) ON DELETE SET NULL,  -- 类型树（可多级）
    description TEXT,
    is_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    create_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    create_user VARCHAR(64),
    update_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    update_user VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_dimension_type_parent  ON dimension_type(parent_id);
CREATE INDEX IF NOT EXISTS idx_dimension_type_enabled ON dimension_type(is_enabled);
CREATE INDEX IF NOT EXISTS idx_dimension_type_sort    ON dimension_type(sort_order);
CREATE INDEX IF NOT EXISTS idx_dimension_type_create_date ON dimension_type(create_date);
CREATE INDEX IF NOT EXISTS idx_dimension_type_create_user ON dimension_type(create_user);
CREATE INDEX IF NOT EXISTS idx_dimension_type_update_user ON dimension_type(update_user);

-- dimension_item 增加类型外键（有值引用禁止删类型，ON DELETE RESTRICT）
ALTER TABLE dimension_item ADD COLUMN IF NOT EXISTS type_id VARCHAR(32)
    REFERENCES dimension_type(id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS idx_dimension_item_type_id ON dimension_item(type_id);

-- 说明：
-- - 存量 dimension_item.dimension_type 字符串列保留过渡期（本期不删除、不回填）。
-- - 新代码双写 type_id + dimension_type；读取以 type_id JOIN 为准。