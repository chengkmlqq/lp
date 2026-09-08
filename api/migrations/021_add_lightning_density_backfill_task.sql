-- 021: 地闪密度回填历史记录表（每次回填生成一条历史，最新在上）
-- 幂等：表已存在则跳过。

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'lightning_density_backfill_task') THEN
        CREATE TABLE lightning_density_backfill_task (
            id                  VARCHAR(32) PRIMARY KEY,
            line_id             VARCHAR(32) NOT NULL REFERENCES power_line(id) ON DELETE CASCADE,
            distribution_id     VARCHAR(32),
            prepared_at         TIMESTAMP WITH TIME ZONE DEFAULT now(),
            prepared_by_user_id VARCHAR(64),
            radius_km           DOUBLE PRECISION,
            data_years          DOUBLE PRECISION,
            updated_tower_count INTEGER      DEFAULT 0,
            missing_geo_count   INTEGER      DEFAULT 0,
            avg_density         DOUBLE PRECISION,
            min_density         DOUBLE PRECISION,
            max_density         DOUBLE PRECISION,
            strike_count        INTEGER,
            warnings            JSON         DEFAULT '[]'::json,
            create_date         TIMESTAMP WITH TIME ZONE DEFAULT now()
        );
        CREATE INDEX idx_ldbf_task_line ON lightning_density_backfill_task(line_id);
        CREATE INDEX idx_ldbf_task_dist ON lightning_density_backfill_task(distribution_id);
        CREATE INDEX idx_ldbf_task_prepared ON lightning_density_backfill_task(prepared_at);
    END IF;
END $$;