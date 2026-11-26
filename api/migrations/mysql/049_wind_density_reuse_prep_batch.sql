-- LP-136：地闪密度菜单移到「风电场数据准备」之后 + 密度批次支持复用数据准备批次源文件。
-- PG 版见 ../049_wind_density_reuse_prep_batch.sql
--
-- 1) 菜单顺序（一级菜单 sort_order）：
--      风电场数据准备 46 → 地闪密度统计 47 → 风电场计算 48 → 单风机计算 49
-- 2) wind_lightning_density_batch 增加 prep_batch_id（来源数据准备批次，历史手工上传批次为 NULL）。
--
-- 幂等：UPDATE 按 code 定位可重复执行；ADD COLUMN / CREATE INDEX 为一次性 DDL，
--       重复执行会报「列/索引已存在」，忽略即可（与 mysql/047 的处理方式一致）。

UPDATE menus SET sort_order = 46 WHERE code = 'admin.wind_data_prep';
UPDATE menus SET sort_order = 47 WHERE code = 'admin.wind_lightning_density';
UPDATE menus SET sort_order = 48 WHERE code = 'admin.wind_farm_calc';
UPDATE menus SET sort_order = 49 WHERE code = 'admin.wind_turbine_calc';

ALTER TABLE wind_lightning_density_batch
    ADD COLUMN prep_batch_id VARCHAR(32) NULL;

CREATE INDEX idx_wld_batch_prep_batch_id
    ON wind_lightning_density_batch (prep_batch_id);
