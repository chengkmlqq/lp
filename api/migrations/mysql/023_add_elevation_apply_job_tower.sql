-- [mysql] 由 PG 匿名块(DO $$)展开：全新库直接建表/索引（幂等由 CREATE TABLE IF NOT EXISTS 保证）
CREATE TABLE IF NOT EXISTS elevation_apply_job_tower (
            id               VARCHAR(32) PRIMARY KEY,
            job_id           VARCHAR(32) NOT NULL REFERENCES elevation_apply_job(id) ON DELETE CASCADE,
            tower_id         VARCHAR(32) NOT NULL REFERENCES power_line_tower(id) ON DELETE CASCADE,
            tower_no         VARCHAR(64),
            seq_no           INTEGER,
            longitude        DOUBLE,
            latitude         DOUBLE,
            action           VARCHAR(32) NOT NULL DEFAULT 'updated',
            altitude_before_m DOUBLE,
            altitude_after_m  DOUBLE,
            slope_1_before   DOUBLE,
            slope_1_after    DOUBLE,
            slope_2_before   DOUBLE,
            slope_2_after    DOUBLE,
            create_date      DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP())
        );
CREATE INDEX idx_elevation_apply_job_tower_job ON elevation_apply_job_tower(job_id);
CREATE INDEX idx_elevation_apply_job_tower_tower ON elevation_apply_job_tower(tower_id);
