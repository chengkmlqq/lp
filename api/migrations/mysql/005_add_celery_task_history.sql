-- Migration: Add celery_task_history table for persistent task monitoring
-- Date: 2026-07-04
-- Description: Store Celery task lifecycle events in PostgreSQL so the
--   task-monitor page retains history across Flower/container restarts.
--   Flower's in-memory state is ephemeral; this table provides durable storage.

CREATE TABLE IF NOT EXISTS celery_task_history (
    task_id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(512) NOT NULL DEFAULT '',
    state VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    queue_name VARCHAR(128),
    worker VARCHAR(128),
    retries INTEGER DEFAULT 0,
    eta DATETIME,
    started_at DATETIME,
    done_at DATETIME,
    runtime_seconds DOUBLE,
    error TEXT,
    create_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_date DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_celery_task_history_state ON celery_task_history(state);
CREATE INDEX idx_celery_task_history_name ON celery_task_history(name);
CREATE INDEX idx_celery_task_history_create_date ON celery_task_history(create_date);
CREATE INDEX idx_celery_task_history_done_at ON celery_task_history(done_at);
CREATE INDEX idx_celery_task_history_worker ON celery_task_history(worker);
