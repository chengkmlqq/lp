-- LP-32：风电场地闪密度统计（独立一级菜单）。
-- 与 admin/lightning-distribution（GB/T 40621 地闪密度统计）完全隔离：
-- 独立菜单、独立权限点、独立表与接口，仅共用通用基础设施。
--
-- 幂等、非破坏性插入；全新库由 seed_service DEFAULT_MENUS / DEFAULT_PERMISSIONS
-- 自动播种。MySQL 版见 mysql/042_add_wind_lightning_density_menu.sql
--
-- 业务表（wind_lightning_density_batch / _cell / _turbine）由
-- `Base.metadata.create_all`（init_db 启动链路）创建，无需手工 DDL。

INSERT INTO permissions (code, name)
SELECT 'wind_lightning_density.read', 'Read wind-farm ground flash density batches'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_lightning_density.read');

INSERT INTO permissions (code, name)
SELECT 'wind_lightning_density.manage', 'Create and manage wind-farm ground flash density batches'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = 'wind_lightning_density.manage');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.wind_lightning_density', '风电场地闪密度统计', '/admin/wind-lightning-density', 'CloudOutlined', NULL, 'menu', 45, 'enabled', TRUE, FALSE, NULL, 'wind_lightning_density.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.wind_lightning_density');

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.wind_lightning_density'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code IN ('wind_lightning_density.read', 'wind_lightning_density.manage')
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_permissions rp
    WHERE rp.role_id = r.id AND rp.permission_id = p.id
  );
