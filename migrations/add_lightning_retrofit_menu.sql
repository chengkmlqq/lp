-- 防雷改造菜单（/admin/lightning-retrofit）
--
-- 背景：LP-486 上线了防雷改造前端页（高杆塔雷击成因分析 / 改造措施推荐 /
-- 措施推荐非建线），但 menus 表未注册对应菜单，导致用户只能靠直链访问。
-- 本迁移把「防雷改造」注册为「防雷计算」(/admin/fl-analysis) 的同级菜单。
--
-- 幂等：按 code 唯一（ON CONFLICT DO NOTHING）；若同级参照菜单不存在则
-- 不插入任何行（SELECT ... FROM menus WHERE path = ... 返回空集）。

INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, permission_code)
SELECT 'admin.lightning_retrofit', '防雷改造', '/admin/lightning-retrofit', 'ThunderboltOutlined',
       sibling.parent_id, 'menu', COALESCE(sibling.sort_order, 0) + 1, 'enabled', true, false, 'line.read'
FROM menus AS sibling
WHERE sibling.path = '/admin/fl-analysis'
ON CONFLICT (code) DO NOTHING;
