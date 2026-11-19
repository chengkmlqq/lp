-- LP-36：单风机计算（独立一级菜单，独立 matlab-wind worker + 编译产物引擎管理）。
-- 幂等、非破坏性插入；全新库由 seed_service DEFAULT_MENUS / DEFAULT_PERMISSIONS 播种。
-- 业务表（wind_turbine_calc_job / wind_turbine_calc_result）由 Base.metadata.create_all 创建。
-- MySQL 版见 mysql/045_add_wind_turbine_calc_menu.sql

INSERT INTO permissions (code, name)
SELECT 'wind_turbine_calc.read', 'Read single wind-turbine calculation jobs'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_turbine_calc.read');

INSERT INTO permissions (code, name)
SELECT 'wind_turbine_calc.manage', 'Create and manage single wind-turbine calculation jobs'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_turbine_calc.manage');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.wind_turbine_calc', '单风机计算', '/admin/wind-turbine-calc', 'ThunderboltFilled', NULL, 'menu', 48, 'enabled', TRUE, FALSE, NULL, 'wind_turbine_calc.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.wind_turbine_calc');

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.wind_turbine_calc'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('wind_turbine_calc.read', 'wind_turbine_calc.manage')
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
