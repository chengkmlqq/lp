-- Migration: ATP 模型「形态识别 + 槽位扫描」改为异步任务的状态列
-- Date: 2026-11-03
-- 背景：判定逻辑本身是毫秒级（实测 7ms），但读模型包要走 OSS（files.s3.default），
--       每次 list_dir / get_object 都是一次 HTTPS 往返，且旧实现串行读包内全部
--       .atp/.dat/.pch —— 单资产实测端到端 2~3 秒。上传请求和「重新检测形态」
--       按钮都被这段 I/O 拖住，故改为 Celery 任务异步执行 + 前端轮询状态。
--
-- analysis_status: pending | running | success | failed（NULL = 从未分析过）
-- analysis_token : 入队时生成的随机串，任务回写前校验，防止慢任务覆盖新结果
-- analysis_error : 失败原因（截断 512 字）

ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(20);

ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS analysis_error VARCHAR(512);

ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS analysis_token VARCHAR(32);

ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS analysis_started_at TIMESTAMPTZ;

ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS analysis_finished_at TIMESTAMPTZ;

COMMENT ON COLUMN atp_asset.analysis_status IS '异步分析状态：pending/running/success/failed，NULL 表示从未分析';
COMMENT ON COLUMN atp_asset.analysis_error IS '异步分析失败原因（截断 512 字），成功时清空';
COMMENT ON COLUMN atp_asset.analysis_token IS '异步任务令牌：入队时生成，任务回写前校验，防止旧任务覆盖新结果';
COMMENT ON COLUMN atp_asset.analysis_started_at IS '异步分析开始时间';
COMMENT ON COLUMN atp_asset.analysis_finished_at IS '异步分析结束时间';
