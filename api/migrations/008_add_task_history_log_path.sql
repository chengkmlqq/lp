-- Migration: Add log_path column to celery_task_history for durable log addressing
-- Date: 2026-08-01
-- Description: Store the fixed MinIO log path (logs/{task_id}.log) on the task record
--   so log retrieval no longer relies on inferring the path from the current UTC date.
--   Uploaded at task end, then written back here via Upsert.

ALTER TABLE celery_task_history
    ADD COLUMN IF NOT EXISTS log_path VARCHAR(512);

CREATE INDEX IF NOT EXISTS idx_celery_task_history_log_path
    ON celery_task_history (log_path);
