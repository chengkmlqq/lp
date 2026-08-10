-- Migration: 为 audit_logs.created_at 补充索引（LP-293）
-- Date: 2026-08-10
-- Description:
--   审计日志定期清理（scheduled_task 的 syslog_cleanup 类型）按
--   created_at < threshold 批量删除，模型字段已加 index=True（应用启动时
--   create_all 会为新建表建索引），但仍需对已存在的表显式建索引，避免
--   大表上 DELETE WHERE created_at < ... 全表扫描。
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
