-- Migration: 雷电流地闪密度模块改造 - LightningDistribution 新表
-- Date: 2026-08-01
-- Description:
--   1. 新建 lightning_distribution 表（批次 + 统计结果 + 图片引用），取代
--      lightning_distribution_point（落雷明细逐行入库，整表删除）。
--   2. 删除 lightning_distribution_point 表及其索引。
--   3. lightning_import_batch 表保留：雷电流波形导入（import_type=waveform）
--      仍依赖该表跟踪批次状态；地闪分布导入不再写入该表。
-- 新表由应用启动时 Base.metadata.create_all 自动创建（见 app/core/database.py），
-- 本脚本仅负责删除旧表，并显式创建新表以保证部署可独立执行。

-- 删除旧地闪明细表（含索引，CASCADE 连带其索引）
DROP TABLE IF EXISTS lightning_distribution_point;

-- 新表（与 app/models/lightning_distribution.py 保持一致）
CREATE TABLE IF NOT EXISTS lightning_distribution (
    id VARCHAR(32) PRIMARY KEY,
    region_id VARCHAR(64),
    location_tag VARCHAR(255),
    city VARCHAR(128),
    event_year INTEGER,
    line_id VARCHAR(64),
    source_file_name VARCHAR(255) NOT NULL DEFAULT 'upload',
    source_object_key VARCHAR(512) NOT NULL DEFAULT '',
    import_type VARCHAR(32) NOT NULL DEFAULT 'distribution',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    stage VARCHAR(32) NOT NULL DEFAULT 'parsing',
    progress INTEGER NOT NULL DEFAULT 0,
    task_id VARCHAR(255),
    error_message TEXT,
    total_lines INTEGER NOT NULL DEFAULT 0,
    valid_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    warnings JSON,
    area_km2 DOUBLE,
    data_years DOUBLE,
    grid_size_km DOUBLE,
    overall_ng DOUBLE,
    max_abs_current DOUBLE,
    avg_abs_current DOUBLE,
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    stats_json JSON,
    image_object_key VARCHAR(512),
    thumbnail_key VARCHAR(512),
    create_user VARCHAR(64),
    create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_user VARCHAR(64)
);

CREATE INDEX idx_ld_region ON lightning_distribution(region_id);
CREATE INDEX idx_ld_location_tag ON lightning_distribution(location_tag);
CREATE INDEX idx_ld_city ON lightning_distribution(city);
CREATE INDEX idx_ld_line_id ON lightning_distribution(line_id);
CREATE INDEX idx_ld_status ON lightning_distribution(status);
CREATE INDEX idx_ld_create_date ON lightning_distribution(create_date);
