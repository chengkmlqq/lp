-- Migration: add_system_params_is_encrypted.sql
-- Adds the is_encrypted column on system_params (LP-310).
-- 幂等：ADD COLUMN IF NOT EXISTS，可重复执行。
-- 备注：存量参数一律按"不加密明文"处理（默认 FALSE），不做数据迁移。

ALTER TABLE system_params ADD COLUMN IF NOT EXISTS is_encrypted BOOLEAN NOT NULL DEFAULT FALSE;
