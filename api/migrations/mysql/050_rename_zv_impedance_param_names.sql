-- LP-146：ZV 四参数中三段波阻抗参数定义的展示名对齐文档口径——MySQL 版。
--   塔材波阻抗1 → 主材波阻抗
--   塔材波阻抗2 → 横材波阻抗
--   塔材波阻抗3 → 斜材波阻抗
-- 幂等：仅更新 code 命中且 name 仍为旧名的行；已被手工改名则不触碰。
-- 只改展示名与描述，code / 绑定 / 单位 / 默认值全部不变。
-- PG 版见 ../050_rename_zv_impedance_param_names.sql

UPDATE atp_param_definition
SET name = '主材波阻抗',
    description = REPLACE(COALESCE(description, ''), '塔材波阻抗1', '主材波阻抗')
WHERE code = 'tower_z_1'
  AND name = '塔材波阻抗1';

UPDATE atp_param_definition
SET name = '横材波阻抗',
    description = REPLACE(COALESCE(description, ''), '塔材波阻抗2', '横材波阻抗')
WHERE code = 'tower_z_2'
  AND name = '塔材波阻抗2';

UPDATE atp_param_definition
SET name = '斜材波阻抗',
    description = REPLACE(COALESCE(description, ''), '塔材波阻抗3', '斜材波阻抗')
WHERE code = 'tower_z_3'
  AND name = '塔材波阻抗3';
