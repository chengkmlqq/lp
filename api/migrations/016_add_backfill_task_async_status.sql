-- Migration: 雷电流幅值回填任务异步化（LP-432）
-- Date: 2026-08-22
-- Description:
--   在 lightning_current_backfill_task 增加异步任务状态机字段：
--   status / progress / task_id / error_message，使回填任务可被 Celery
--   驱动、前端可通过 WS 事件 + backfill-tasks 接口跟踪进度。
--   新部署由 ORM create_all 自动建列；本脚本显式兼容老库。
--   历史存量行保持默认 pending / progress=0。

ALTER TABLE lightning_current_backfill_task
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'pending';
ALTER TABLE lightning_current_backfill_task
    ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lightning_current_backfill_task
    ADD COLUMN IF NOT EXISTS task_id VARCHAR(255);
ALTER TABLE lightning_current_backfill_task
    ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_lightning_current_backfill_task_status
    ON lightning_current_backfill_task(status);
