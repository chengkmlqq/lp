-- Migration: Add elevation_dataset_file_meta table for storing file-level coordinate ranges
-- Date: 2026-06-13
-- Description: Create new table to store bbox and metadata for each elevation file in a dataset

CREATE TABLE IF NOT EXISTS elevation_dataset_file_meta (
    id VARCHAR(32) PRIMARY KEY,
    dataset_id VARCHAR(32) NOT NULL,
    file_path VARCHAR(2048) NOT NULL,
    file_name VARCHAR(512) NOT NULL,
    bbox_min_lon DOUBLE PRECISION,
    bbox_max_lon DOUBLE PRECISION,
    bbox_min_lat DOUBLE PRECISION,
    bbox_max_lat DOUBLE PRECISION,
    sample_count INTEGER DEFAULT 0,
    create_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    update_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    FOREIGN KEY (dataset_id) REFERENCES elevation_dataset(id) ON DELETE CASCADE
);

CREATE INDEX idx_elevation_file_meta_dataset ON elevation_dataset_file_meta(dataset_id);
CREATE INDEX idx_elevation_file_meta_path ON elevation_dataset_file_meta(dataset_id, file_path);

-- Notes:
-- After running this migration, run the elevation dataset analysis task for each dataset
-- to populate the file metadata with coordinate ranges.
