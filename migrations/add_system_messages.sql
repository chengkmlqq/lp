-- Migration: Add system_messages table for system notifications
-- Date: 2026-06-13
-- Description: Create system_messages table to support sending notifications to users

CREATE TABLE IF NOT EXISTS system_messages (
    message_id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    message_type VARCHAR(32) NOT NULL DEFAULT 'info',
    target_user_id VARCHAR(36),
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    read_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX idx_system_messages_target_user ON system_messages(target_user_id);
CREATE INDEX idx_system_messages_is_read ON system_messages(is_read);
CREATE INDEX idx_system_messages_created_at ON system_messages(created_at);
CREATE INDEX idx_system_messages_type ON system_messages(message_type);

-- Notes:
-- - target_user_id is NULL for broadcast messages (sent to all users)
-- - target_user_id references users.user_id for user-specific messages
-- - message_type values: 'info', 'warning', 'error', 'success'
-- - is_read tracks whether the message has been read by the target user
