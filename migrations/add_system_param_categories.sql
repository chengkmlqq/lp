-- Migration: add_system_param_categories.sql
-- Adds the system_param_categories table and category_id FK on system_params.

CREATE TABLE IF NOT EXISTS system_param_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    parent_id INTEGER REFERENCES system_param_categories(id) ON DELETE SET NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_system_param_categories_name ON system_param_categories(name);
CREATE INDEX IF NOT EXISTS idx_system_param_categories_parent_id ON system_param_categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_system_param_categories_sort_order ON system_param_categories(sort_order);

ALTER TABLE system_params ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES system_param_categories(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_system_params_category_id ON system_params(category_id);