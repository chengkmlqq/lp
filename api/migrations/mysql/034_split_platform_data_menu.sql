-- Migration: 拆分「基础数据包」菜单为「导出」「导入」两项（MySQL 版）。
-- PostgreSQL 版见 ../041_split_platform_data_menu.sql。
-- Date   : 2026-11-17

-- 1. 新增两个菜单节点（挂在「基础数据」目录下）
INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.platform_data.export', '基础数据包导出', '/admin/platform-data/export', 'DownloadOutlined', NULL, 'menu', 30, 'enabled', TRUE, FALSE, NULL, 'platform_data.manage'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.platform_data.export');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.platform_data.import', '基础数据包导入', '/admin/platform-data/import', 'InboxOutlined', NULL, 'menu', 31, 'enabled', TRUE, FALSE, NULL, 'platform_data.manage'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.platform_data.import');

-- 2. 挂到「基础数据」目录下
UPDATE menus AS child
JOIN menus AS parent ON parent.code = 'admin.basic_data'
SET child.parent_id = parent.id
WHERE child.code IN ('admin.platform_data.export', 'admin.platform_data.import') AND child.parent_id IS NULL;

-- 3. 给 admin 角色绑定两个新菜单
INSERT INTO role_menus (role_id, menu_id)
SELECT r.id, m.id
FROM roles r
JOIN menus m ON m.code IN ('admin.platform_data.export', 'admin.platform_data.import')
WHERE r.code = 'admin'
  AND NOT EXISTS (
    SELECT 1 FROM role_menus rm
    WHERE rm.role_id = r.id AND rm.menu_id = m.id
  );

-- 4. 清理旧菜单
DELETE FROM role_menus
WHERE menu_id IN (SELECT id FROM menus WHERE code = 'admin.platform_data');

DELETE FROM menus
WHERE code = 'admin.platform_data';
