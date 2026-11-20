-- LP-50：菜单「风电场地闪密度统计」改名为「地闪密度统计」——MySQL 版。
-- 幂等：仅更新仍为旧名的行；已是新名或已被手工改名时不触碰。
-- PG 版见 ../046_rename_wind_lightning_density_menu.sql

UPDATE menus
SET name = '地闪密度统计'
WHERE code = 'admin.wind_lightning_density'
  AND name = '风电场地闪密度统计';
