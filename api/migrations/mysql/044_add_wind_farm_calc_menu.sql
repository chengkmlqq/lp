-- LP-35：风电场计算（独立一级菜单）——MySQL 版。
-- 幂等、非破坏性插入；全新库由 seed_service DEFAULT_MENUS / DEFAULT_PERMISSIONS 播种。
-- PG 版见 ../044_add_wind_farm_calc_menu.sql

INSERT INTO permissions (code, name)
SELECT 'wind_farm_calc.read', 'Read wind-farm calculation jobs'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_farm_calc.read');

INSERT INTO permissions (code, name)
SELECT 'wind_farm_calc.manage', 'Create and manage wind-farm calculation jobs'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_farm_calc.manage');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.wind_farm_calc', '风电场计算', '/admin/wind-farm-calc', 'ThunderboltOutlined', NULL, 'menu', 47, 'enabled', TRUE, FALSE, NULL, 'wind_farm_calc.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.wind_farm_calc');

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.wind_farm_calc'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('wind_farm_calc.read', 'wind_farm_calc.manage')
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
