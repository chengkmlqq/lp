-- Create traveling_wave_job table for async task persistence
CREATE TABLE IF NOT EXISTS traveling_wave_job (
    id VARCHAR(32) PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    task_id VARCHAR(128),
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    sample_rate_hz INTEGER,
    fault_distance_km FLOAT,
    tower_no VARCHAR(128),
    file_a_path VARCHAR(512),
    file_b_path VARCHAR(512),
    file_c_path VARCHAR(512),
    result_json JSONB,
    error_message TEXT,
    log_text TEXT
);

CREATE INDEX idx_traveling_wave_job_status ON traveling_wave_job(status);
CREATE INDEX idx_traveling_wave_job_created_at ON traveling_wave_job(created_at);
