-- Migration: LP-28 — 删除已失效的 type=button 菜单项（2026-11-09 权限策略调整遗留）
-- Target : PostgreSQL 17（线上 lp-pg）；MySQL 8 版见 mysql/041_remove_button_menus.sql
-- Date   : 2026-11-17
--
-- 背景：菜单管理列表里的「新建线路 / 编辑线路」等按钮菜单（约 32 条，type=button，
--       code 形如 admin.power_lines:btn.create，permission_code 形如 line.create）
--       在 2026-11-09 权限策略调整后已完全失效：
--         1) require_permission / require_any_permission / require_enabled_menu_route
--            全部退化为「仅要求登录」，接口层不再消费 permission_code；
--         2) 角色配置页只保留目录 + 页面，勾选页面即按模块前缀自动推导该模块全部权限码，
--            button 行不再展示也无需逐个配置；
--         3) 按钮菜单 path=null / visible=false，侧边栏不渲染。
--       DEFAULT_MENUS 已在 LP-28 中移除这些条目；本迁移负责清理存量库，避免重建后复现。
--
-- 删除前核查（建议先手工执行以下只读查询，确认绑定情况）：
--   SELECT r.code AS role_code, m.code AS menu_code, m.permission_code
--   FROM role_menus rm
--   JOIN roles r ON r.id = rm.role_id
--   JOIN menus m ON m.id = rm.menu_id
--   WHERE LOWER(m.type) = 'button';
-- 结论：按钮菜单的 permission_code 已不被任何接口用于鉴权，角色配置与侧边栏也跳过它们，
--       因此上述查询结果即使非空也属于无效绑定，可随菜单一并清除；不存在误删有效权限的风险。
--       细粒度权限码仍注册在 permissions 表（DEFAULT_PERMISSIONS）与角色 permission_codes 中，
--       不受本次删除影响。
--
-- 幂等性：DELETE 无匹配行即可安全重跑。
-- ⚠️ 执行前务必全库备份。

BEGIN;

-- 先清理角色-按钮菜单绑定（role_menus.menu_id 对 menus.id 有 ON DELETE CASCADE，
-- 此处显式删除以便在缺失外键约束的存量库上也能清理干净）。
DELETE FROM role_menus
WHERE menu_id IN (SELECT id FROM menus WHERE LOWER(type) = 'button');

-- 再删除按钮菜单本身。LOWER() 兼容历史库中 type='BUTTON' 的写法。
DELETE FROM menus
WHERE LOWER(type) = 'button';

COMMIT;
