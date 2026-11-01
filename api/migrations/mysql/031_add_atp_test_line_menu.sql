-- Add the ATP test-line (测试线路管理) menu + admin role binding for existing DBs.
-- Idempotent, non-destructive inserts; fresh installs get the same row via
-- seed_service DEFAULT_MENUS.
--
-- 为什么需要独立菜单：测试线路（单塔基准）是模型测试的默认输入源，
-- 与「ATP模型管理」「测试集管理」同级，但在 UI 上是独立页面。
-- API 侧 /api/v1/atp/test-lines 的菜单守卫同时接受本菜单与 admin.atp_models
-- （见 app/core/dependencies.py MENU_ROUTE_ALTERNATES），
-- 因此只给本菜单的角色也能正常调接口。

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.atp_test_lines', '测试线路管理', '/admin/atp-test-lines', 'ClusterOutlined', NULL, 'menu', 22, 'enabled', TRUE, FALSE, NULL, 'atp.read'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.atp_test_lines');

-- 挂到「基础数据」目录下（与 ATP模型管理/测试集管理同父）
UPDATE menus AS child
JOIN menus AS parent ON parent.code = 'admin.basic_data'
SET child.parent_id = parent.id
WHERE child.code = 'admin.atp_test_lines' AND child.parent_id IS NULL;

INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code = 'admin.atp_test_lines'
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );
