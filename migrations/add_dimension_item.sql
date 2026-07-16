-- Migration: Add dimension_item table for dimension management
-- Date: 2026-06-28
-- Description: Create dimension_item table to support managing voltage levels, tower types, scenarios, and arrester combinations in a tree structure

CREATE TABLE IF NOT EXISTS dimension_item (
    id VARCHAR(32) PRIMARY KEY,
    dimension_type VARCHAR(64) NOT NULL,
    code VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    parent_id VARCHAR(32),
    description TEXT,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    create_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    create_user VARCHAR(64),
    update_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    update_user VARCHAR(64)
);

CREATE INDEX idx_dimension_item_type ON dimension_item(dimension_type);
CREATE INDEX idx_dimension_item_parent ON dimension_item(parent_id);
CREATE INDEX idx_dimension_item_code ON dimension_item(code);
CREATE INDEX idx_dimension_item_enabled ON dimension_item(is_enabled);
CREATE INDEX idx_dimension_item_sort ON dimension_item(sort_order);
CREATE INDEX idx_dimension_item_create_date ON dimension_item(create_date);
CREATE INDEX idx_dimension_item_create_user ON dimension_item(create_user);
CREATE INDEX idx_dimension_item_update_user ON dimension_item(update_user);

-- Notes:
-- - dimension_type values: 'voltage_level', 'tower_type', 'scenario', 'arrester_combination'
-- - parent_id references dimension_item.id for tree structure (NULL for root nodes)
-- - code should be unique within the same dimension_type
-- - sort_order determines display order (lower values first)
