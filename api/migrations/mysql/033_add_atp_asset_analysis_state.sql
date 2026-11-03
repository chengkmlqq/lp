-- ATP 模型「形态识别 + 槽位扫描」异步化状态列（MySQL 版）
-- Date: 2026-11-03
-- 背景：判定逻辑毫秒级，但读模型包要走 OSS（每次 list/get 一次 HTTPS 往返），
--       旧实现串行读包内全部 .atp/.dat/.pch，单资产端到端 2~3 秒，把上传请求和
--       「重新检测形态」按钮都拖住 → 改为 Celery 任务 + 前端轮询。
--
-- analysis_status: pending | running | success | failed（NULL = 从未分析过）
-- analysis_token : 入队令牌，任务回写前校验，防止慢任务覆盖新结果
-- analysis_error : 失败原因（截断 512 字）

ALTER TABLE atp_asset
    ADD COLUMN analysis_status VARCHAR(20) NULL
    COMMENT '异步分析状态：pending/running/success/failed，NULL 表示从未分析';

ALTER TABLE atp_asset
    ADD COLUMN analysis_error VARCHAR(512) NULL
    COMMENT '异步分析失败原因（截断 512 字），成功时清空';

ALTER TABLE atp_asset
    ADD COLUMN analysis_token VARCHAR(32) NULL
    COMMENT '异步任务令牌：入队时生成，任务回写前校验，防止旧任务覆盖新结果';

ALTER TABLE atp_asset
    ADD COLUMN analysis_started_at DATETIME NULL
    COMMENT '异步分析开始时间';

ALTER TABLE atp_asset
    ADD COLUMN analysis_finished_at DATETIME NULL
    COMMENT '异步分析结束时间';
