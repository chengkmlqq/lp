-- ATP 参数模板管理页面菜单（/admin/atp-param-templates）
-- 幂等：按 code 唯一，ON CONFLICT DO NOTHING。

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, permission_code)
SELECT 'admin.atp_param_templates', '参数模板管理', '/admin/atp-param-templates', 'BranchesOutlined',
       parent.id, 'menu', 25, 'enabled', true, false, 'atp.read'
FROM menus AS parent
WHERE parent.code = 'admin.basic_data'
ON CONFLICT (code) DO NOTHING;
