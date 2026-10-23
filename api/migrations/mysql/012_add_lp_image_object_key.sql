-- Migration: lightning_distribution 表新增 lp_image_object_key 列
-- Date: 2026-08-04
-- Description:
--   LP-224 地闪密度统计 - 操作列新增绘图按钮实现 LP 桌面端分区密度图（Voronoi）。
--   该列存储 LP 桌面端 Voronoi 分区密度图在 MinIO 的对象 Key，与现有
--   image_object_key（均匀网格热力图）并存。由 render_lp_density_job 写入，
--   详情弹窗据此展示「LP 分区图」Tab。
-- 幂等性：ADD COLUMN。

ALTER TABLE lightning_distribution ADD COLUMN lp_image_object_key VARCHAR(512);