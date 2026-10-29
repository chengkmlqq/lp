-- ============================================================
-- ⚠️ DEPRECATED：已被 api/app/services/dimension_seed.py 取代（代码化 ORM 种子，
--    兼容 PG/MySQL/SQLite，启动自动播种），此 SQL 仅保留作历史参考，勿再手动执行。
-- ============================================================
-- Seed: ATP 模型管理下拉选枚举 → 维度管理数据
-- 来源：web/src/app/admin/atp-models/page.tsx 的 DEFAULT_VOLTAGE_LEVELS /
--       DEFAULT_TOWER_TYPES / DEFAULT_SCENE_TYPES / DEFAULT_ARRESTER_CONFIGS
-- 目标：在维度数据管理页面可维护这些枚举（dimension_type 类型 + dimension_item 值）
-- 幂等：可重复执行（code 唯一约束 / NOT EXISTS 去重）

-- ============ 1. 维度类型 dimension_type ============
INSERT INTO dimension_type (id, code, name, description, is_enabled, sort_order, create_date, create_user, update_date, update_user)
VALUES
  (replace(gen_random_uuid()::text, '-', ''), 'voltage_level', '电压等级', '来源：ATP 模型管理页面「电压等级」下拉选（迁移）', TRUE, 0, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'tower_type', '塔型', '来源：ATP 模型管理页面「塔型」下拉选（迁移）', TRUE, 1, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'scenario', '场景', '来源：ATP 模型管理页面「场景」下拉选（迁移）', TRUE, 2, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'arrester_combination', '避雷器配置组合', '来源：ATP 模型管理页面「避雷器配置组合」下拉选（迁移）', TRUE, 3, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system')
ON CONFLICT (code) DO NOTHING;

-- ============ 2. 维度值 dimension_item ============
-- 2.1 电压等级（code 对齐 ATP 下拉 value，name 对齐 label）
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'voltage_level', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('35', '35kV', 0),
  ('66', '66kV', 1),
  ('110', '110kV', 2),
  ('220', '220kV', 3),
  ('330', '330kV', 4),
  ('500', '500kV', 5),
  ('750', '750kV', 6),
  ('800', '800kV', 7),
  ('1000', '1000kV', 8)
) AS v(code, name, sort_order)
WHERE t.code = 'voltage_level'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.2 塔型
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'tower_type', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('ganzi', '干字塔', 0),
  ('guxing', '鼓型塔', 1),
  ('guxingd', '鼓型双回路塔', 2),
  ('jiubei', '酒杯塔', 3),
  ('maotou', '猫头塔', 4),
  ('shangzi', '上字塔', 5),
  ('sihuita', '四回路塔', 6),
  ('vzhiliu', '直流V型塔', 7),
  ('zhiliu', '直流塔', 8)
) AS v(code, name, sort_order)
WHERE t.code = 'tower_type'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.3 场景
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'scenario', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('fanji', '反击', 0),
  ('raoji1', '绕击1', 1),
  ('raoji2', '绕击2', 2),
  ('raoji3', '绕击3', 3)
) AS v(code, name, sort_order)
WHERE t.code = 'scenario'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.4 避雷器配置组合
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'arrester_combination', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('M1', 'M1', 0),
  ('M2', 'M2', 1),
  ('M3', 'M3', 2),
  ('M12', 'M12', 3),
  ('M13', 'M13', 4),
  ('M23', 'M23', 5),
  ('M123', 'M123', 6),
  ('noM', 'noM', 7)
) AS v(code, name, sort_order)
WHERE t.code = 'arrester_combination'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);
