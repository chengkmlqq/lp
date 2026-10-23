-- 添加高程数据源类型字段以支持GDEM V2数据集
-- 迁移时间: 2026-07-04

-- 为 elevation_dataset 表添加 data_source_type 字段
ALTER TABLE elevation_dataset
ADD COLUMN data_source_type VARCHAR(32) DEFAULT 'generic' NOT NULL;

CREATE INDEX idx_elevation_dataset_data_source_type ON elevation_dataset(data_source_type);

-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）

-- 为 elevation_file_record 表添加 data_source_type 字段
ALTER TABLE elevation_file_record
ADD COLUMN data_source_type VARCHAR(32) DEFAULT 'generic' NOT NULL;

CREATE INDEX idx_elevation_file_record_data_source_type ON elevation_file_record(data_source_type);

-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）

-- 更新 terrain_metadata 字段说明（地形构建工具统一为gdal2tiles）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）
