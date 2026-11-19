-- LP-33：风电场数据准备（独立一级菜单）——MySQL 版。
-- 幂等、非破坏性插入；全新库由 seed_service DEFAULT_MENUS / DEFAULT_PERMISSIONS 播种。
-- PG 版见 ../043_add_wind_data_prep_menu.sql
--
-- 业务表由 `Base.metadata.create_all`（init_db 启动链路）创建，无需手工 DDL。

INSERT INTO permissions (code, name)
SELECT 'wind_data_prep.read', 'Read wind-farm data preparation batches'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_data_prep.read');

INSERT INTO permissions (code, name)
SELECT 'wind_data_prep.manage', 'Create and manage wind-farm data preparation batches'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_data_prep.manage');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.wind_data_prep', '风电场数据准备', '/admin/wind-data-prep', 'CloudUploadOutlined', NULL, 'menu', 46, 'enabled', TRUE, FALSE, NULL, 'wind_data_prep.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.wind_data_prep');

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.wind_data_prep'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('wind_data_prep.read', 'wind_data_prep.manage')
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
