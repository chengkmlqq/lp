-- Migration: Lightning current backfill history tables
-- Issue: LP-428 【改造】雷电流幅值回填历史记录：任务快照 + 杆塔明细 + 前端回填记录页面
-- Date: 2026-08-22
-- Description:
--   - lightning_current_backfill_task    回填任务表（每次回填的数据快照）
--   - lightning_current_backfill_tower   回填杆塔明细表（逐杆塔回填前/后值 + 变化量）
-- Usage: psql -f migrations/add_lightning_current_backfill_tables.sql <dbname>

BEGIN;

-- ① 回填任务表（新增，1:N 线路 1 → 任务 N）
CREATE TABLE IF NOT EXISTS lightning_current_backfill_task (
    id                     VARCHAR(32) PRIMARY KEY,
    line_id                VARCHAR(32) NOT NULL REFERENCES power_line(id) ON DELETE CASCADE,
    prepared_at            TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    prepared_by_user_id    VARCHAR(64),
    current_a              DOUBLE PRECISION,
    current_b              DOUBLE PRECISION,
    peak_max               DOUBLE PRECISION,
    peak_min               DOUBLE PRECISION,
    sampled_event_count    INTEGER NOT NULL DEFAULT 0,
    region_id              VARCHAR(64),
    is_synthetic           BOOLEAN NOT NULL DEFAULT FALSE,
    updated_tower_count    INTEGER NOT NULL DEFAULT 0,
    created_profile_count  INTEGER NOT NULL DEFAULT 0,
    warnings               JSON NOT NULL DEFAULT '[]'::json,
    source_amplitude_ids   JSON NOT NULL DEFAULT '[]'::json,
    create_date            TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_lcbt_line_id ON lightning_current_backfill_task(line_id);
CREATE INDEX IF NOT EXISTS idx_lcbt_prepared_at ON lightning_current_backfill_task(prepared_at);

-- ② 回填杆塔明细表（新增，1:N 任务 1 → 杆塔明细 N）
CREATE TABLE IF NOT EXISTS lightning_current_backfill_tower (
    id                   VARCHAR(32) PRIMARY KEY,
    task_id              VARCHAR(32) NOT NULL REFERENCES lightning_current_backfill_task(id) ON DELETE CASCADE,
    tower_id             VARCHAR(32) NOT NULL REFERENCES power_line_tower(id) ON DELETE CASCADE,
    current_a            DOUBLE PRECISION,
    current_b            DOUBLE PRECISION,
    previous_current_a   DOUBLE PRECISION,
    previous_current_b   DOUBLE PRECISION,
    action               VARCHAR(32) NOT NULL DEFAULT 'updated',
    create_date          TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_lcbtw_task_id ON lightning_current_backfill_tower(task_id);
CREATE INDEX IF NOT EXISTS idx_lcbtw_tower_id ON lightning_current_backfill_tower(tower_id);

COMMIT;
