-- Migration: lightning_distribution 表新增 lp_draw_task_id 列
-- Date: 2026-08-08
-- Description:
--   LP-261 地闪密度统计页面处理日志查看功能。draw-lp 绘图任务（render_lp_density_job）
--   的 task_id 此前提交时返回但未持久化，刷新页面后无法追溯绘图日志。该列存储
--   最近一次 LP 分区绘图任务的 Celery task_id，与现有 task_id（import 任务）并存，
--   由 render_lp_density_job 起始处写入，详情弹窗据此展示「绘图日志」。
-- 幂等性：ADD COLUMN IF NOT EXISTS。

ALTER TABLE lightning_distribution ADD COLUMN IF NOT EXISTS lp_draw_task_id VARCHAR(255);