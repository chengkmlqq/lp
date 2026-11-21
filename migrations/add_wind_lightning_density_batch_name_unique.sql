-- Migration: 为风电场地面闪密度批次名加唯一索引（LP-62）
-- Date: 2026-11-21
-- Description:
--   批次名改为后端统一生成并保证唯一；旧逻辑信任前端传入值，历史数据可能同名。
--   先对重名行追加基于主键的去重后缀，再建立唯一索引，避免存量数据导致建索引失败。
-- Usage: psql -f migrations/add_wind_lightning_density_batch_name_unique.sql <dbname>

BEGIN;

-- 历史重名去重：每个 batch_name 按创建时间保留最早一条原名，其余改名。
-- 后缀取主键前 8 位，确定性且不会互相碰撞；总长仍 <= 255。
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY batch_name
            ORDER BY create_date ASC NULLS LAST, id ASC
        ) AS rn
    FROM wind_lightning_density_batch
)
UPDATE wind_lightning_density_batch b
SET batch_name = LEFT(b.batch_name, 240) || '-dup-' || LEFT(b.id, 8)
FROM ranked r
WHERE b.id = r.id
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_wld_batch_name
    ON wind_lightning_density_batch (batch_name);

COMMIT;
