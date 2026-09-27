-- Add the overview (系统总览) menu + admin role binding for existing DBs.
-- Idempotent, non-destructive inserts; fresh installs get the same rows via
-- seed_service DEFAULT_MENUS / ROLE_MENU_BINDINGS.

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.overview', '系统总览', '/admin/overview', 'DashboardOutlined', NULL, 'menu', -10, 'enabled', TRUE, FALSE, NULL, 'menu.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.overview');

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.overview'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );