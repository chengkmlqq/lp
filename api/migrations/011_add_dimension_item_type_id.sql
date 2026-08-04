-- Migration: dimension_item 表补充 type_id 外键列
-- Date: 2026-08-03
-- Description:
--   LP-213 维度管理页面报错：`column dimension_item.type_id does not exist`。
--   存量部署在 dimension_item 表创建后才引入 type_id 字段（LP-207 维度类型管理），
--   且未执行 add_dimension_type.sql，导致 ORM 查询该表时列不存在。
--   本脚本幂等补齐该列及其索引，与 app/models/dimension_item.py 保持一致。
--   应用启动时 init_db() 也会自动补齐（见 app/core/database.py），本脚本保证
--   部署可独立执行。
-- 幂等性：ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS。

ALTER TABLE dimension_item ADD COLUMN IF NOT EXISTS type_id VARCHAR(32)
    REFERENCES dimension_type(id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS idx_dimension_item_type_id ON dimension_item(type_id);
