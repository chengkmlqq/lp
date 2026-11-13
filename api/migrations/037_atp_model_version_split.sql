-- Migration: LP-11 P1 — ATP 模型 / 版本拆表（模型主表 + 版本表改名）
-- Target : PostgreSQL 17（线上 lp-pg）；只动元数据，不搬对象存储文件。
-- Date   : 2026-11-13
--
-- ⚠️ 部署顺序（硬性约束）：先跑本脚本 → 再切后端镜像 → 最后切前端镜像。
--   脚本必须在**旧代码仍在运行**时执行：RENAME 保留旧 atp_asset.id 与全部数据，
--   随后创建只读/可写兼容视图 atp_asset，让尚未切换的旧代码继续跑（不停机）。
--   P4 清理（删冗余列 / 收紧约束 / 删兼容视图）前可随时执行 039 回滚脚本。
-- ⚠️ 执行前务必全库备份，并先在测试库用线上快照完整演练。
--
-- 目标结构（过渡期 P1–P3，双写）：
--   atp_model          新增模型主表，按五维组合回填 781 行；code 去掉 -vN 段且去重。
--   atp_asset_version  由 atp_asset RENAME 而来，沿用旧 id / 全部列 + 新增 model_id、version_code。
--                      模型级字段（name/description/status/五维）过渡期仍双写保留在版本行上。
--   atp_asset          兼容视图，投影旧列集合，旧代码读写经它落到 atp_asset_version。

BEGIN;

-- 幂等守卫：本脚本对「旧结构」只跑一次。已改名（atp_asset_version 存在）时直接报错，
-- 避免对兼容视图 atp_asset 误发 ALTER TABLE / CREATE INDEX；重跑请先执行 039 回滚。
DO $$
BEGIN
    IF to_regclass('atp_asset_version') IS NOT NULL THEN
        RAISE EXCEPTION 'LP-11 P1 已应用（atp_asset_version 已存在）；如需重跑请先执行 039_atp_model_version_split_rollback.sql';
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────
-- 步骤 1：模型主表 atp_model
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS atp_model (
    id             VARCHAR(32)  PRIMARY KEY,
    code           VARCHAR(64)  NOT NULL,
    name           VARCHAR(255) NOT NULL,
    description    TEXT         DEFAULT '',
    status         VARCHAR(20)  DEFAULT 'enabled',
    voltage_level  VARCHAR(16),
    tower_type     VARCHAR(64),
    scene_type     VARCHAR(32),
    arrester_config VARCHAR(64),
    shield_wire    VARCHAR(16)  NOT NULL DEFAULT 'with',
    create_date    TIMESTAMPTZ,
    create_user    VARCHAR(64),
    update_date    TIMESTAMPTZ,
    update_user    VARCHAR(64)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_atp_model_code ON atp_model (code);
CREATE INDEX IF NOT EXISTS idx_atp_model_status ON atp_model (status);
CREATE INDEX IF NOT EXISTS idx_atp_model_dim
    ON atp_model (voltage_level, tower_type, scene_type, arrester_config, shield_wire);
-- 可选（PG15+）：五维组合杜绝重复模型，NULL 归一（线上 PG17 支持 NULLS NOT DISTINCT）。
-- CREATE UNIQUE INDEX IF NOT EXISTS uq_atp_model_dim
--     ON atp_model (voltage_level, tower_type, scene_type, arrester_config, shield_wire) NULLS NOT DISTINCT;

-- ─────────────────────────────────────────────────────────────
-- 步骤 2：按五维组合回填 781 行模型主表
--   模型 id = md5(五维归一串)，与步骤 4 回填 model_id 用同一公式，保证一一对应。
--   code = 旧 code 去掉 -vN 段（含 -revN / _rN 尾巴）；同名追加 -2/-3 去重。
--   DISTINCT ON 取每组最早版本行代表模型级字段。
-- ─────────────────────────────────────────────────────────────
WITH groups AS (
    SELECT DISTINCT ON (
        voltage_level, tower_type, scene_type, arrester_config,
        COALESCE(NULLIF(shield_wire, ''), 'with')
    )
        voltage_level, tower_type, scene_type, arrester_config,
        COALESCE(NULLIF(shield_wire, ''), 'with') AS shield_wire,
        code, name, description, status,
        create_date, create_user, update_date, update_user
    FROM atp_asset
    ORDER BY voltage_level, tower_type, scene_type, arrester_config,
             COALESCE(NULLIF(shield_wire, ''), 'with'), create_date, code
),
coded AS (
    SELECT *, REGEXP_REPLACE(code, '-v[0-9]+([-_].*)?$', '', 'i') AS base_code
    FROM groups
),
dedup AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY base_code ORDER BY create_date, code) AS rn
    FROM coded
)
INSERT INTO atp_model (
    id, code, name, description, status,
    voltage_level, tower_type, scene_type, arrester_config, shield_wire,
    create_date, create_user, update_date, update_user
)
SELECT
    MD5(CONCAT_WS('|', COALESCE(voltage_level, ''), COALESCE(tower_type, ''),
                       COALESCE(scene_type, ''), COALESCE(arrester_config, ''), shield_wire)),
    CASE WHEN rn = 1 THEN base_code ELSE base_code || '-' || rn END,
    name, description, status,
    voltage_level, tower_type, scene_type, arrester_config, shield_wire,
    create_date, create_user, update_date, update_user
FROM dedup
ON CONFLICT (id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────
-- 步骤 3：RENAME 前给版本表加列并回填（此时表仍叫 atp_asset）
--   version_code = 旧 code 原样保留（含 -vN），保证导出/日志/报告外部引用不失效（决策 2）。
--   model_id     = 五维组合对应的 atp_model.id（步骤 2 同公式）。
-- ─────────────────────────────────────────────────────────────
ALTER TABLE atp_asset ADD COLUMN IF NOT EXISTS model_id     VARCHAR(32);
ALTER TABLE atp_asset ADD COLUMN IF NOT EXISTS version_code VARCHAR(64);

UPDATE atp_asset SET version_code = code WHERE version_code IS NULL;
UPDATE atp_asset
   SET model_id = MD5(CONCAT_WS('|', COALESCE(voltage_level, ''), COALESCE(tower_type, ''),
                                    COALESCE(scene_type, ''), COALESCE(arrester_config, ''),
                                    COALESCE(NULLIF(shield_wire, ''), 'with')))
 WHERE model_id IS NULL;

-- version_code 唯一 / model_id 索引在改名后建（见步骤 5），此处不加，避免视图态误操作。

-- ─────────────────────────────────────────────────────────────
-- 步骤 4：一步改名 atp_asset → atp_asset_version（决策 3）
--   PG 的 FK 约束按表 OID 存储，RENAME 会自动把三张外键表
--   （atp_asset_run / atp_test_line / atp_test_set_case）的引用指向新表，
--   asset_id 列值与数据零改动，无需重建 FK。顶部守卫已确认目标表不存在。
-- ─────────────────────────────────────────────────────────────
ALTER TABLE atp_asset RENAME TO atp_asset_version;

-- ─────────────────────────────────────────────────────────────
-- 步骤 5：新表上的索引与唯一性（改名为真实表后操作）
--   约束收紧（UNIQUE(model_id,version) / 部分唯一 is_active）留到 P4，避免脏数据卡死上线。
-- ─────────────────────────────────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS uq_atp_asset_version_code
    ON atp_asset_version (version_code);
CREATE INDEX IF NOT EXISTS idx_atp_asset_version_model
    ON atp_asset_version (model_id);
CREATE INDEX IF NOT EXISTS idx_atp_asset_version_model_published
    ON atp_asset_version (model_id, is_published);
CREATE INDEX IF NOT EXISTS idx_atp_asset_version_model_state
    ON atp_asset_version (model_id, publish_state);

-- 步骤 5b（P4 收紧约束时启用）：组内版本唯一 + 组内唯一生效
-- CREATE UNIQUE INDEX uq_atp_asset_version_model_version
--     ON atp_asset_version (model_id, version) WHERE model_id IS NOT NULL;
-- CREATE UNIQUE INDEX uq_atp_asset_version_active
--     ON atp_asset_version (model_id) WHERE is_active = true AND model_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────
-- 步骤 6：兼容视图 atp_asset（旧代码 / 外部查询 / 回滚窗口）
--   单表简单投影 → PG 自动可更新：旧代码 INSERT/UPDATE/DELETE 经它落到
--   atp_asset_version；未提供的 model_id / version_code 取 NULL，
--   过渡期由新版代码双写或校验脚本补回填。P4 稳定后删除。
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW atp_asset AS
SELECT
    id, code, name, description, status,
    voltage_level, tower_type, scene_type, arrester_config,
    version, is_active, is_published, published_date, publish_state, release_notes,
    shield_wire, storage_mount_code, storage_root_path, tags_json, test_line_id,
    slots_json, model_format, format_check_json,
    analysis_status, analysis_error, analysis_token,
    analysis_started_at, analysis_finished_at,
    test_status, test_message, test_date,
    create_date, create_user, update_date, update_user
FROM atp_asset_version;

COMMIT;

-- 上线前必须执行 038_atp_model_version_split_validate.sql，确认零差异。
-- 回滚见 039_atp_model_version_split_rollback.sql（P4 清理后不可逆）。
