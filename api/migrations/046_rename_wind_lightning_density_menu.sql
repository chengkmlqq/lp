-- LP-50：菜单「风电场地闪密度统计」改名为「地闪密度统计」。
-- 幂等：仅更新仍为旧名的行；已是新名或已被手工改名时不触碰。
-- 全新库由 seed_service.DEFAULT_MENUS 直接播种新名，无需本迁移。
-- MySQL 版见 mysql/046_rename_wind_lightning_density_menu.sql
-- 模块内部标识（code / 权限码 / API 前缀 / 表名 / 任务名）保持不变。

UPDATE menus
SET name = '地闪密度统计'
WHERE code = 'admin.wind_lightning_density'
  AND name = '风电场地闪密度统计';
