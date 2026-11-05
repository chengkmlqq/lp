-- Migration: atp_asset 增加版本发布状态（is_published / published_date）
-- Date: 2026-11-05
-- 背景：ATP 模型管理页新增「发布 / 下线」版本管理（对齐线路管理页卡片改造）：
--       发布 = 该版本对仿真可见（fl_analysis 资产定位只在已发布版本中选取）；
--       下线 = 暂停对外提供，不参与仿真定位但保留文件与运行记录。
--       存量资产回填为已发布（历史行为不变：此前所有资产默认可用）；
--       新建资产默认未发布，需显式发布后才参与仿真定位。

ALTER TABLE atp_asset
    ADD COLUMN is_published TINYINT(1) NOT NULL DEFAULT 1 COMMENT '版本是否已发布（下线后不参与仿真定位）',
    ADD COLUMN published_date DATETIME NULL COMMENT '最近发布时间';

CREATE INDEX idx_atp_asset_published ON atp_asset (is_published);
