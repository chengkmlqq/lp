-- Migration: 用户表增加手机号字段(短信验证码登录用)
-- Date: 2026-10-28
--
-- 背景：登录图形验证码之后可选启用「短信验证码」(阿里云短信网关)，需要接收手机号。
--       users 表新增 phone 列，可空(未绑定手机号的账号在短信开关开启时无法登录)。
--       索引 + 唯一约束，避免同一手机号绑定多个账号。

ALTER TABLE users
    ADD COLUMN phone VARCHAR(20) NULL AFTER avatar_path;

CREATE UNIQUE INDEX uq_users_phone ON users (phone);
CREATE INDEX idx_users_phone ON users (phone);
