-- Add link_url to system_messages: 消息点击跳转到对应任务/结果详情。
-- Idempotent; safe to run on fresh installs (column simply gets created).

ALTER TABLE system_messages ADD COLUMN link_url VARCHAR(255);