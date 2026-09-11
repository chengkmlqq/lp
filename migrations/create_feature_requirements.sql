-- 功能需求单（2026-09-12）
-- 表：feature_requirement；菜单：/admin/feature-requirements；种子：本需求

CREATE TABLE IF NOT EXISTS feature_requirement (
  id          varchar(36) PRIMARY KEY,
  title       varchar(200) NOT NULL,
  module      varchar(64),
  priority    varchar(16) NOT NULL DEFAULT '中',
  status      varchar(32) NOT NULL DEFAULT '待处理',
  description text,
  created_by  varchar(64),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feature_requirement_module ON feature_requirement(module);
CREATE INDEX IF NOT EXISTS idx_feature_requirement_status ON feature_requirement(status);
CREATE INDEX IF NOT EXISTS idx_feature_requirement_created ON feature_requirement(created_at DESC);

-- 菜单入口
INSERT INTO menus (code, name, path, icon, parent_id, type, sort_order, status, visible, cacheable, permission_code)
SELECT 'admin.feature_requirements', '功能需求单', '/admin/feature-requirements', 'ProfileOutlined',
       parent.id, 'menu', 30, 'enabled', true, false, 'atp.read'
FROM menus AS parent
WHERE parent.code = 'admin.basic_data'
ON CONFLICT (code) DO NOTHING;

-- 种子需求：新建防雷计算页面布局调整
INSERT INTO feature_requirement (id, title, module, priority, status, description, created_by)
SELECT 'fr-20260912-fl-create-layout',
       '新建防雷计算页面布局调整',
       '防雷计算',
       '中',
       '待处理',
       E'需求描述：\n1. 基础信息：任务名表单框占一整行，任务类型+线路一行\n2. 计算线路改为杆塔列表，与计算方法占一行\n   （"计算方法"下面是放选模板，不在这里）',
       'admin'
WHERE NOT EXISTS (SELECT 1 FROM feature_requirement WHERE id = 'fr-20260912-fl-create-layout');
