-- Migration: fl_analysis_run 的 stdout/stderr 从 TEXT 升级为 MEDIUMTEXT
-- Date: 2026-11-05
-- 背景：35kV 12 塔全量计算收尾回写 run.stdout_text 时撞
--       (1406, "Data too long for column 'stdout_text'")——单塔 stdout 截断上限
--       是 _truncate_output 的 200k 字符（atp_asset_service.LOG_MAX_CHARS），
--       12 塔聚合可达 2.4MB，而 MySQL TEXT 上限 64KB，已成功算完的 12 塔
--       被收尾 DataError 整体标成 failed。
--       模型层已同步改为 Text().with_variant(MEDIUMTEXT, "mysql")。

ALTER TABLE fl_analysis_run
    MODIFY COLUMN stdout_text MEDIUMTEXT;

ALTER TABLE fl_analysis_run
    MODIFY COLUMN stderr_text MEDIUMTEXT;
