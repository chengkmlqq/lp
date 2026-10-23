-- [mysql] 由 PG 匿名块(DO $$)展开：全新库直接建表/索引（幂等由 CREATE TABLE IF NOT EXISTS 保证）
CREATE TABLE IF NOT EXISTS lightning_density_backfill_task (
            id                  VARCHAR(32) PRIMARY KEY,
            line_id             VARCHAR(32) NOT NULL REFERENCES power_line(id) ON DELETE CASCADE,
            distribution_id     VARCHAR(32),
            prepared_at         DATETIME DEFAULT now(),
            prepared_by_user_id VARCHAR(64),
            radius_km           DOUBLE,
            data_years          DOUBLE,
            updated_tower_count INTEGER      DEFAULT 0,
            missing_geo_count   INTEGER      DEFAULT 0,
            avg_density         DOUBLE,
            min_density         DOUBLE,
            max_density         DOUBLE,
            strike_count        INTEGER,
            warnings            JSON         DEFAULT ('[]'),
            create_date         DATETIME DEFAULT now()
        );
CREATE INDEX idx_ldbf_task_line ON lightning_density_backfill_task(line_id);
CREATE INDEX idx_ldbf_task_dist ON lightning_density_backfill_task(distribution_id);
CREATE INDEX idx_ldbf_task_prepared ON lightning_density_backfill_task(prepared_at);
