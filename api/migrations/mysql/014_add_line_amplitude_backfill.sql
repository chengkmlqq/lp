-- Migration: 雷电流幅值回填关联线路表 - LineAmplitudeBackfill
-- Date: 2026-08-08
-- Description:
--   新建 line_amplitude_backfill 表（LP-265），记录「雷电流幅值 → 线路回填」关联。
--   现状没有 amplitude ↔ line 的关联存储：LightningAmplitude 无 line_id，
--   preparation source 里也没有 amplitude_ids。本表用于：
--     1. 幅值列表「回填关联线路数」统计（按 amplitude_id 分组 count）；
--     2. 回填线路小窗明细（GET /lightning-currents/amplitudes/{id}/backfill-lines）；
--     3. 支撑杆塔列表页回填数据展示（幂等覆盖，不做历史数据迁移）。
-- 新表由应用启动时 Base.metadata.create_all 自动创建（见 app/core/database.py），
-- 本脚本显式建表，保证部署可独立执行（与 009_add_lightning_amplitude.sql 风格一致）。

CREATE TABLE IF NOT EXISTS line_amplitude_backfill (
    id                    VARCHAR(32) PRIMARY KEY,
    line_id               VARCHAR(32) NOT NULL,
    amplitude_id          VARCHAR(32) NOT NULL,
    prepared_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prepared_by_user_id   VARCHAR(64),
    sampled_event_count   INTEGER NOT NULL DEFAULT 0,
    current_a             DOUBLE,
    current_b             DOUBLE,
    peak_max              DOUBLE,
    peak_min              DOUBLE,
    region_id             VARCHAR(64),
    is_synthetic          BOOLEAN NOT NULL DEFAULT FALSE,
    extra_json            JSON,
    create_date           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    create_user           VARCHAR(64),
    update_date           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_user           VARCHAR(64),
    CONSTRAINT uq_line_amplitude_backfill_pair UNIQUE (line_id, amplitude_id),
    CONSTRAINT fk_lab_line_id FOREIGN KEY (line_id) REFERENCES power_line(id) ON DELETE CASCADE,
    CONSTRAINT fk_lab_amplitude_id FOREIGN KEY (amplitude_id) REFERENCES lightning_amplitude(id) ON DELETE CASCADE
);

CREATE INDEX idx_lab_amplitude_id ON line_amplitude_backfill(amplitude_id);
CREATE INDEX idx_lab_line_id      ON line_amplitude_backfill(line_id);
CREATE INDEX idx_lab_prepared_at  ON line_amplitude_backfill(prepared_at);