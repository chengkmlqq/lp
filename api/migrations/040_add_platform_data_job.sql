-- Migration: LP-14 — 平台基础数据包任务表 platform_data_job
-- Target : PostgreSQL 17（线上 lp-pg）；MySQL 方言下由 init_db() 的
--          Base.metadata.create_all 自动建表（本脚本仅作手工 / 灰度演练用）。
-- Date   : 2026-11-14
--
-- 作用：记录每一次「基础数据包」的导入 / 导出任务及其产物，支撑异步轮询与产物复用
--       （再下载、基于历史 export job 直接再导入、审计）。
-- ⚠️ 执行前务必全库备份；若表已存在则跳过（幂等）。

BEGIN;

DO $$
BEGIN
    IF to_regclass('platform_data_job') IS NOT NULL THEN
        RAISE NOTICE 'platform_data_job 已存在，跳过建表';
        RETURN;
    END IF;

    CREATE TABLE platform_data_job (
        id                       VARCHAR(32)  NOT NULL PRIMARY KEY,
        kind                     VARCHAR(16)  NOT NULL,
        status                   VARCHAR(16)  NOT NULL DEFAULT 'pending',
        request_payload_json     JSON         NOT NULL DEFAULT '{}'::json,
        manifest_json            JSON,
        artifact_storage_path    VARCHAR(2048),
        artifact_file_id         INTEGER,
        result_summary_json      JSON,
        error_message           TEXT,
        create_user              VARCHAR(64),
        create_date              TIMESTAMPTZ  NOT NULL DEFAULT now(),
        finish_date              TIMESTAMPTZ
    );

    CREATE INDEX idx_platform_data_job_kind     ON platform_data_job (kind);
    CREATE INDEX idx_platform_data_job_status   ON platform_data_job (status);
    CREATE INDEX idx_platform_data_job_create   ON platform_data_job (create_date);
    CREATE INDEX idx_platform_data_job_artifact ON platform_data_job (artifact_storage_path);
    CREATE INDEX idx_platform_data_job_file     ON platform_data_job (artifact_file_id);
END $$;

COMMIT;
