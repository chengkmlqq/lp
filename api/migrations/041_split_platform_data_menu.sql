-- Migration: 拆分「基础数据包」菜单为「导出」「导入」两项。
-- Target : PostgreSQL 17（线上 lp-pg）；MySQL 方言见 mysql/034_split_platform_data_menu.sql。
-- Date   : 2026-11-17
--
-- 基础数据包页按受众拆分为两页：
--   /admin/platform-data/export  基础数据包导出（交付人员，导出表单 + 任务列表）
--   /admin/platform-data/import  基础数据包导入（部署人员，仅导入组件）
-- 两页共用权限码 platform_data.manage（方案 A）。
-- 旧菜单 admin.platform_data 下线，避免侧边栏出现重复入口。
-- 幂等：已存在的 code 跳过插入；旧菜单存在才清理。执行前建议全库备份。

BEGIN;

-- 1. 新增两个菜单节点（挂在「基础数据」目录下）
INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.platform_data.export', '基础数据包导出', '/admin/platform-data/export', 'DownloadOutlined', NULL, 'menu', 30, 'enabled', TRUE, FALSE, NULL, 'platform_data.manage'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.platform_data.export');

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, component, permission_code)
SELECT 'admin.platform_data.import', '基础数据包导入', '/admin/platform-data/import', 'InboxOutlined', NULL, 'menu', 31, 'enabled', TRUE, FALSE, NULL, 'platform_data.manage'
WHERE NOT EXISTS (SELECT 1 FROM menus WHERE code = 'admin.platform_data.import');

-- 2. 挂到「基础数据」目录下
UPDATE menus AS child
SET parent_id = parent.id
FROM menus AS parent
WHERE parent.code = 'admin.basic_data'
  AND child.code IN ('admin.platform_data.export', 'admin.platform_data.import')
  AND child.parent_id IS NULL;

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

-- 4. 清理旧菜单的 admin 绑定与菜单节点（保留其它角色若有引用则一并清理，避免悬浮入口）
DELETE FROM role_menus
WHERE menu_id IN (SELECT id FROM menus WHERE code = 'admin.platform_data');

DELETE FROM menus
WHERE code = 'admin.platform_data';

COMMIT;
