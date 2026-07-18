-- Migration: Add output column to audit_logs table
-- Date: 2026-07-18
-- Description: Add output column to support displaying response/return parameters in system log page

ALTER TABLE audit_logs ADD COLUMN output TEXT;
