-- Migration: 雷电流幅值模块改造 - LightningAmplitude 新表 + 删旧表
-- Date: 2026-08-01
-- Description:
--   1. 新建 lightning_amplitude 表（状态机 + 元数据 + 波形特征统计 + MinIO 引用），
--      取代 lightning_current_event / lightning_current_sample / lightning_import_batch 三张表。
--   2. 删除 lightning_current_sample / lightning_current_event / lightning_import_batch 三张旧表。
--      - 采样明细不再入库，Sample 表整体删除；
--      - waveform 导入状态迁入新表；distribution 已于 LP-178 改走 LightningDistribution。
-- 新表由应用启动时 Base.metadata.create_all 自动创建（见 app/core/database.py），
-- 本脚本显式创建新表并删除旧表，保证部署可独立执行。

-- 删除旧表（含索引；CASCADE 连带外键约束；先删明细表再删主表/批次表）
DROP TABLE IF EXISTS lightning_current_sample;
DROP TABLE IF EXISTS lightning_current_event;
DROP TABLE IF EXISTS lightning_import_batch;

-- 新表（与 app/models/lightning_amplitude.py 保持一致）
CREATE TABLE IF NOT EXISTS lightning_amplitude (
    id                    VARCHAR(32) PRIMARY KEY,
    event_id              VARCHAR(64),
    source_file_name      VARCHAR(255) NOT NULL DEFAULT 'upload',
    event_time            DATETIME,
    source_object_key     VARCHAR(512) NOT NULL DEFAULT '',
    status                VARCHAR(32) NOT NULL DEFAULT 'pending',
    progress              INTEGER NOT NULL DEFAULT 0,
    task_id               VARCHAR(255),
    error_message         TEXT,
    sample_count          INTEGER NOT NULL DEFAULT 0,
    sample_interval_us    DOUBLE,
    sampling_frequency_hz DOUBLE,
    peak_current_ka       DOUBLE,
    peak_abs_current_ka   DOUBLE,
    wavefront_time_t1_us  DOUBLE,
    half_value_time_t2_us DOUBLE,
    steepness_ka_per_us   DOUBLE,
    action_integral_j_ohm DOUBLE,
    wave_shape            VARCHAR(32),
    polarity              VARCHAR(16) NOT NULL DEFAULT 'unknown',
    stroke_count          INTEGER NOT NULL DEFAULT 1,
    stroke_peaks_json     JSON,
    region_id             VARCHAR(64),
    location_tag          VARCHAR(255),
    city                  VARCHAR(128),
    longitude             DOUBLE,
    latitude              DOUBLE,
    altitude_m            DOUBLE,
    sensor_model          VARCHAR(128),
    install_position      VARCHAR(128),
    weather_level         VARCHAR(64),
    pressure_hpa          DOUBLE,
    humidity_percent      DOUBLE,
    is_synthetic          BOOLEAN NOT NULL DEFAULT FALSE,
    feature_json          JSON,
    notes                 TEXT,
    create_user           VARCHAR(64),
    create_date           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_date           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_user           VARCHAR(64),
    CONSTRAINT uq_la_event_id UNIQUE (event_id)
);

CREATE INDEX idx_la_status      ON lightning_amplitude(status);
CREATE INDEX idx_la_region      ON lightning_amplitude(region_id);
CREATE INDEX idx_la_city        ON lightning_amplitude(city);
CREATE INDEX idx_la_create_date ON lightning_amplitude(create_date);
CREATE INDEX idx_la_peak_abs    ON lightning_amplitude(peak_abs_current_ka);
