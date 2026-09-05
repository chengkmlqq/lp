-- Seed: 补齐 ATP 模型管理下拉选枚举（对照 /media/vdb/atp-models/ATP 真实目录）
-- 2026-09-05 探查结果：
--   1. 电压等级：35/66/110/220/330/500/750/800/1000（9 个，种子已有，跳过）
--   2. 塔型：种子缺 6 个「无避雷线」变体 ganzino/guxingno/jiubeino/maotouno/shangzino/sihuitano
--      （仅 110/220kV 存在，真实模型目录 ATP/110/ganzino 等）
--   3. 雷击类型：fanji/raoji1/raoji2/raoji3（4 个，种子已有，跳过）
--   4. 避雷器组合：种子缺 shuzhi-noM（220kV 四回路塔专用，ATP/220/sihuita/fanji/shuzhi-noM）
-- 幂等：NOT EXISTS 去重，可重复执行

-- ============ 1. 塔型补充：无避雷线变体 ============
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'tower_type', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('ganzino', '干字塔（无避雷线）', 10),
  ('guxingno', '鼓型塔（无避雷线）', 11),
  ('jiubeino', '酒杯塔（无避雷线）', 12),
  ('maotouno', '猫头塔（无避雷线）', 13),
  ('shangzino', '上字塔（无避雷线）', 14),
  ('sihuitano', '四回路塔（无避雷线）', 15)
) AS v(code, name, sort_order)
WHERE t.code = 'tower_type'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- ============ 2. 避雷器组合补充：shuzhi-noM ============
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'arrester_combination', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('shuzhi-noM', '树直-noM', 8)
) AS v(code, name, sort_order)
WHERE t.code = 'arrester_combination'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);
