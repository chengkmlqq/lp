-- Migration: Add elevation_file_record table and migrate data
-- Date: 2026-06-20
-- Description: Refactor elevation management from dataset-centric to file-centric

-- Step 1: Create new elevation_file_record table
CREATE TABLE IF NOT EXISTS elevation_file_record (
    id VARCHAR(32) PRIMARY KEY,
    file_name VARCHAR(512) NOT NULL,
    file_path VARCHAR(2048) NOT NULL,
    file_format VARCHAR(32) NOT NULL,
    file_size INTEGER DEFAULT 0,
    source VARCHAR(512),
    mount_code VARCHAR(64) NOT NULL,
    resolution_m FLOAT,
    status VARCHAR(32) DEFAULT 'active',
    bbox_min_lon FLOAT,
    bbox_max_lon FLOAT,
    bbox_min_lat FLOAT,
    bbox_max_lat FLOAT,
    sample_count INTEGER DEFAULT 0,
    analysis_task_id VARCHAR(128),
    analysis_status VARCHAR(32) DEFAULT 'not_started',
    analysis_error_message TEXT,
    analysis_started_at TIMESTAMP WITH TIME ZONE,
    analysis_finished_at TIMESTAMP WITH TIME ZONE,
    terrain_status VARCHAR(32) DEFAULT 'not_supported',
    terrain_task_id VARCHAR(128),
    terrain_error_message TEXT,
    terrain_root_path VARCHAR(2048),
    terrain_url_template VARCHAR(2048),
    terrain_min_zoom INTEGER,
    terrain_max_zoom INTEGER,
    terrain_bounds JSON,
    terrain_metadata JSON,
    notes TEXT,
    create_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    create_user VARCHAR(64),
    update_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_user VARCHAR(64)
);

-- Create indexes for elevation_file_record
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_status ON elevation_file_record(status);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_mount_code ON elevation_file_record(mount_code);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_analysis_status ON elevation_file_record(analysis_status);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_terrain_status ON elevation_file_record(terrain_status);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_analysis_task ON elevation_file_record(analysis_task_id);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_terrain_task ON elevation_file_record(terrain_task_id);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_file_name ON elevation_file_record(file_name);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_file_format ON elevation_file_record(file_format);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_source ON elevation_file_record(source);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_create_date ON elevation_file_record(create_date);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_create_user ON elevation_file_record(create_user);
CREATE INDEX IF NOT EXISTS idx_elevation_file_record_update_user ON elevation_file_record(update_user);

-- Step 2: Migrate data from elevation_dataset to elevation_file_record
-- Each dataset becomes a file record
INSERT INTO elevation_file_record (
    id,
    file_name,
    file_path,
    file_format,
    file_size,
    source,
    mount_code,
    resolution_m,
    status,
    bbox_min_lon,
    bbox_max_lon,
    bbox_min_lat,
    bbox_max_lat,
    sample_count,
    analysis_task_id,
    analysis_status,
    analysis_error_message,
    analysis_started_at,
    analysis_finished_at,
    terrain_status,
    terrain_task_id,
    terrain_error_message,
    terrain_root_path,
    terrain_url_template,
    terrain_min_zoom,
    terrain_max_zoom,
    terrain_bounds,
    terrain_metadata,
    notes,
    create_date,
    create_user,
    update_date,
    update_user
)
SELECT
    id,
    SUBSTRING(file_path FROM '[^/]+$') as file_name,  -- Extract filename from path
    file_path,
    file_format,
    0 as file_size,  -- Default to 0, will be updated later
    source,
    mount_code,
    resolution_m,
    status,
    bbox_min_lon,
    bbox_max_lon,
    bbox_min_lat,
    bbox_max_lat,
    sample_count,
    analysis_task_id,
    analysis_status,
    analysis_error_message,
    analysis_started_at,
    analysis_finished_at,
    terrain_status,
    terrain_task_id,
    terrain_error_message,
    terrain_root_path,
    terrain_url_template,
    terrain_min_zoom,
    terrain_max_zoom,
    terrain_bounds,
    terrain_metadata,
    notes,
    create_date,
    create_user,
    update_date,
    update_user
FROM elevation_dataset
WHERE NOT EXISTS (
    SELECT 1 FROM elevation_file_record WHERE elevation_file_record.id = elevation_dataset.id
);

-- Step 3: Add file_record_id column to elevation_apply_job (nullable for backward compatibility)
ALTER TABLE elevation_apply_job ADD COLUMN IF NOT EXISTS file_record_id VARCHAR(32);

-- Create index for file_record_id
CREATE INDEX IF NOT EXISTS idx_elevation_apply_job_file_record ON elevation_apply_job(file_record_id);

-- Migrate dataset_id to file_record_id for existing jobs
UPDATE elevation_apply_job
SET file_record_id = dataset_id
WHERE file_record_id IS NULL AND dataset_id IS NOT NULL;

-- Step 4: Add file_record_id column to elevation_data_import_job (nullable for backward compatibility)
ALTER TABLE elevation_data_import_job ADD COLUMN IF NOT EXISTS file_record_id VARCHAR(32);

-- Create index for file_record_id
CREATE INDEX IF NOT EXISTS idx_elevation_data_import_job_file_record ON elevation_data_import_job(file_record_id);

-- Migrate dataset_id to file_record_id for existing import jobs
UPDATE elevation_data_import_job
SET file_record_id = dataset_id
WHERE file_record_id IS NULL AND dataset_id IS NOT NULL;

-- Note: We keep the old tables and columns for backward compatibility during transition
-- The old elevation_dataset, elevation_dataset_file_meta tables can be dropped after full migration
-- The dataset_id columns in elevation_apply_job and elevation_data_import_job can be dropped later

-- Step 5: Create a view for backward compatibility (optional)
CREATE OR REPLACE VIEW elevation_dataset_compat AS
SELECT
    id,
    file_name as name,
    SUBSTRING(file_name FROM 1 FOR 64) as code,
    source,
    file_format,
    mount_code,
    SUBSTRING(file_path FROM 1 FOR POSITION('/' || file_name IN file_path) - 1) as dataset_dir,
    file_path,
    resolution_m,
    status,
    'idle' as usage_status,
    sample_count,
    bbox_min_lon,
    bbox_max_lon,
    bbox_min_lat,
    bbox_max_lat,
    analysis_task_id,
    analysis_status,
    analysis_error_message,
    analysis_started_at,
    analysis_finished_at,
    terrain_status,
    terrain_task_id,
    terrain_error_message,
    terrain_root_path,
    terrain_url_template,
    terrain_min_zoom,
    terrain_max_zoom,
    terrain_bounds,
    terrain_metadata,
    notes,
    create_date,
    create_user,
    update_date,
    update_user
FROM elevation_file_record;
