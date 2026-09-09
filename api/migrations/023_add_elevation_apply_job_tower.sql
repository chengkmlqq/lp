-- 023: 高程回填任务杆塔明细表（每次回填任务逐杆塔快照：回填前/后值 + 结果）
-- 幂等：表已存在则跳过。

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'elevation_apply_job_tower') THEN
        CREATE TABLE elevation_apply_job_tower (
            id               VARCHAR(32) PRIMARY KEY,
            job_id           VARCHAR(32) NOT NULL REFERENCES elevation_apply_job(id) ON DELETE CASCADE,
            tower_id         VARCHAR(32) NOT NULL REFERENCES power_line_tower(id) ON DELETE CASCADE,
            tower_no         VARCHAR(64),
            seq_no           INTEGER,
            longitude        DOUBLE PRECISION,
            latitude         DOUBLE PRECISION,
            action           VARCHAR(32) NOT NULL DEFAULT 'updated',
            altitude_before_m DOUBLE PRECISION,
            altitude_after_m  DOUBLE PRECISION,
            slope_1_before   DOUBLE PRECISION,
            slope_1_after    DOUBLE PRECISION,
            slope_2_before   DOUBLE PRECISION,
            slope_2_after    DOUBLE PRECISION,
            create_date      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        );
        CREATE INDEX idx_elevation_apply_job_tower_job ON elevation_apply_job_tower(job_id);
        CREATE INDEX idx_elevation_apply_job_tower_tower ON elevation_apply_job_tower(tower_id);
    END IF;
END $$;
