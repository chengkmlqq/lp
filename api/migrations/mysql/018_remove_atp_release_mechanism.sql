-- Migration: 移除 ATP 模型发布版本机制，简化 ATP 模型与运行记录结构
-- Date: 2026-08-26

-- 1. 删除版本表及其索引（级联删除关联运行记录，但保留资产本身）
DROP TABLE IF EXISTS atp_asset_release;

-- 2. 简化资产表：移除版本相关字段
-- [mysql] SKIPPED: ALTER TABLE atp_asset 移除版本字段（全新库无此列）

-- 3. 简化运行记录表：移除版本关联字段及索引
-- [mysql] SKIPPED: DROP INDEX IF EXISTS（MySQL 不支持，全新库无此对象）

-- [mysql] SKIPPED: ALTER TABLE atp_asset_run 移除版本字段（全新库无此列）