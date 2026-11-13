-- Rollback: LP-11 拆表回滚（P4 清理前有效；P4 删冗余列/视图后不可逆）
-- Target : PostgreSQL 17
-- ⚠️ 前提：全库备份可用。回滚后旧代码（映射 atp_asset 表）可立即恢复运行。
-- 效果：反向 RENAME 回旧结构，删除 atp_model 与新增列，恢复旧列名/约束。
-- 数据零丢失：仅删新增的 model_id / version_code 列，旧列从未删除。

BEGIN;

-- 1) 删除兼容视图（必须先删，否则 RENAME 会撞名）
DROP VIEW IF EXISTS atp_asset;

-- 2) 删除过渡期新增索引
DROP INDEX IF EXISTS uq_atp_asset_version_code;
DROP INDEX IF EXISTS idx_atp_asset_version_model;
DROP INDEX IF EXISTS idx_atp_asset_version_model_published;
DROP INDEX IF EXISTS idx_atp_asset_version_model_state;
DROP INDEX IF EXISTS uq_atp_model_code;
DROP INDEX IF EXISTS idx_atp_model_status;
DROP INDEX IF EXISTS idx_atp_model_dim;

-- 3) 删除新增列（版本表过渡期保留的模型级列本就属于旧表，无需处理）
ALTER TABLE atp_asset_version DROP COLUMN IF EXISTS model_id;
ALTER TABLE atp_asset_version DROP COLUMN IF EXISTS version_code;

-- 4) 反向 RENAME（PG 自动把三张外键表引用指回 atp_asset，数据零改动）
DO $$
BEGIN
    IF to_regclass('atp_asset') IS NULL
       AND to_regclass('atp_asset_version') IS NOT NULL
    THEN
        ALTER TABLE atp_asset_version RENAME TO atp_asset;
    END IF;
END $$;

-- 5) 删除模型主表
DROP TABLE IF EXISTS atp_model;

COMMIT;

-- 回滚后：切回旧代码镜像（ORM AtpAsset → atp_asset 真实表）。
