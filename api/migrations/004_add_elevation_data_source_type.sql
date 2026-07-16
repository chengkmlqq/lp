-- 添加高程数据源类型字段以支持GDEM V2数据集
-- 迁移时间: 2026-07-04

-- 为 elevation_dataset 表添加 data_source_type 字段
ALTER TABLE elevation_dataset
ADD COLUMN data_source_type VARCHAR(32) DEFAULT 'generic' NOT NULL;

CREATE INDEX idx_elevation_dataset_data_source_type ON elevation_dataset(data_source_type);

COMMENT ON COLUMN elevation_dataset.data_source_type IS '数据源类型: generic(通用), gdemv2(ASTER GDEM V2), gdemv3(ASTER GDEM V3), srtm(SRTM)';

-- 为 elevation_file_record 表添加 data_source_type 字段
ALTER TABLE elevation_file_record
ADD COLUMN data_source_type VARCHAR(32) DEFAULT 'generic' NOT NULL;

CREATE INDEX idx_elevation_file_record_data_source_type ON elevation_file_record(data_source_type);

COMMENT ON COLUMN elevation_file_record.data_source_type IS '数据源类型: generic(通用), gdemv2(ASTER GDEM V2), gdemv3(ASTER GDEM V3), srtm(SRTM)';

-- 更新 terrain_metadata 字段说明（地形构建工具统一为gdal2tiles）
COMMENT ON COLUMN elevation_dataset.terrain_metadata IS '地形元数据 JSON，包含 tool: gdal2tiles';
COMMENT ON COLUMN elevation_file_record.terrain_metadata IS '地形元数据 JSON，包含 tool: gdal2tiles';
