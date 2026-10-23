-- Migration: 地闪密度回填历史记录
-- 记录每次 prepare_line_lightning_density 的执行结果，支持历史回填记录查看
-- Date: 2026-08-23

CREATE TABLE IF NOT EXISTS lightning_density_backfill_task (
    id VARCHAR(32) PRIMARY KEY,
    line_id VARCHAR(32) NOT NULL REFERENCES power_line(id) ON DELETE CASCADE,
    distribution_id VARCHAR(32) REFERENCES lightning_distribution(id) ON DELETE SET NULL,
    prepared_at DATETIME NOT NULL DEFAULT NOW(),
    prepared_by_user_id VARCHAR(64),
    radius_km DOUBLE NOT NULL,
    avg_density DOUBLE,
    min_density DOUBLE,
    max_density DOUBLE,
    data_years DOUBLE,
    missing_geo_count INTEGER NOT NULL DEFAULT 0,
    updated_tower_count INTEGER NOT NULL DEFAULT 0,
    warnings JSON NOT NULL DEFAULT ('[]'),
    create_date DATETIME NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_density_backfill_line_id ON lightning_density_backfill_task(line_id);
CREATE INDEX idx_density_backfill_distribution_id ON lightning_density_backfill_task(distribution_id);
CREATE INDEX idx_density_backfill_prepared_at ON lightning_density_backfill_task(prepared_at);