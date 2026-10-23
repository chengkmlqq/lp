-- Add user_overview_config: per-user dashboard layout for the 系统总览 page.
-- Idempotent; safe to run on fresh installs (table simply gets created).
-- Stored as JSON text so widget cards (type/title/span/props) can evolve
-- without schema changes.

CREATE TABLE IF NOT EXISTS user_overview_config (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    widgets_json TEXT NOT NULL DEFAULT ('[]'),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX ix_user_overview_config_user_id
    ON user_overview_config(user_id);
