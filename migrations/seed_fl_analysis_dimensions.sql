-- Seed: FL分析 / 杆塔拓扑等 8 组硬编码枚举 → 维度管理数据
-- 来源：
--   tower_topology_kind  → web/src/app/admin/power-lines/page.tsx TOWER_TOPOLOGY_KIND_OPTIONS
--                          + api/app/services/tower_topology.py TowerTopologyKind
--   fl_analysis_job_type → web/src/components/fl-analysis/create-job-form.tsx + api/app/schemas/fl_analysis.py FlAnalysisJobType
--   current_waveform     → create-job-form.tsx + FlAnalysisCurrentWaveform
--   flashover_method     → create-job-form.tsx + FlAnalysisFlashoverMethod
--   altitude_correction  → create-job-form.tsx + FlAnalysisAltitudeCorrection
--   fanji_naleishuiping_method / raoji_naleishuiping_method → create-job-form.tsx 方法选择
--   fanji_tzl_method / raoji_tzl_method → create-job-form.tsx 方法选择
-- 目标：在维度数据管理页面可维护这些枚举（dimension_type 类型 + dimension_item 值）
-- 幂等：可重复执行（code 唯一约束 / NOT EXISTS 去重）
-- 备注：fl_analysis_job_type 中 mitigation/report/scenario 为内部类型（is_enabled = FALSE，前端创建表单不展示）；
--       9420: risk（风险评估）同样置为 is_enabled = FALSE，新建任务表单仅展示 normal/tongtiao，历史 risk 任务的
--       展示与详情操作（措施推荐 / 报告入口）不受影响。

-- ============ 1. 维度类型 dimension_type ============
INSERT INTO dimension_type (id, code, name, description, is_enabled, sort_order, create_date, create_user, update_date, update_user)
VALUES
  (replace(gen_random_uuid()::text, '-', ''), 'tower_topology_kind', '杆塔拓扑类型', '来源：线路管理「专用编辑器类型」拓扑选择（迁移）', TRUE, 4, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'fl_analysis_job_type', 'FL分析任务类型', '来源：FL分析创建任务表单「任务类型」下拉选（迁移）', TRUE, 5, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'current_waveform', '雷电流波形', '来源：FL分析创建任务表单「雷电流波形」下拉选（迁移）', TRUE, 6, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'flashover_method', '闪络判据', '来源：FL分析创建任务表单「闪络判据」下拉选（迁移）', TRUE, 7, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'altitude_correction', '海拔修正', '来源：FL分析创建任务表单「海拔修正」下拉选（迁移）', TRUE, 8, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'fanji_naleishuiping_method', '反击耐雷水平方法', '来源：FL分析创建任务表单「反击耐雷水平」方法选择', TRUE, 9, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'raoji_naleishuiping_method', '绕击耐雷水平方法', '来源：FL分析创建任务表单「绕击耐雷水平」方法选择', TRUE, 10, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'fanji_tzl_method', '反击跳闸率方法', '来源：FL分析创建任务表单「反击跳闸率」方法选择', TRUE, 11, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'),
  (replace(gen_random_uuid()::text, '-', ''), 'raoji_tzl_method', '绕击跳闸率方法', '来源：FL分析创建任务表单「绕击跳闸率」方法选择', TRUE, 12, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system')
ON CONFLICT (code) DO NOTHING;

-- ============ 2. 维度值 dimension_item ============
-- 2.1 杆塔拓扑类型（code 对齐枚举值，name 对齐显示名）
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'tower_topology_kind', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('single', '单回', 0),
  ('double', '双回', 1),
  ('quad', '四回', 2),
  ('dc', '直流', 3)
) AS v(code, name, sort_order)
WHERE t.code = 'tower_topology_kind'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.2 FL分析任务类型（risk/mitigation/report/scenario 为内部或暂缓类型，is_enabled = FALSE，前端创建表单不展示）
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'fl_analysis_job_type', t.id, v.code, v.name, v.is_enabled, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('normal', '普通计算', TRUE, 0),
  ('tongtiao', '同跳计算', TRUE, 1),
  ('risk', '风险评估', FALSE, 2),
  ('mitigation', '措施推荐', FALSE, 3),
  ('report', '报告', FALSE, 4),
  ('scenario', '场景', FALSE, 5)
) AS v(code, name, is_enabled, sort_order)
WHERE t.code = 'fl_analysis_job_type'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.3 雷电流波形
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'current_waveform', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('heidler', 'Heidler', 0),
  ('double_slope', '双斜角', 1),
  ('double_exponential', '双指数', 2)
) AS v(code, name, sort_order)
WHERE t.code = 'current_waveform'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.4 闪络判据
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'flashover_method', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('guideline', '规程法', 0),
  ('intersection', '相交法', 1),
  ('leader_development', '先导发展法', 2)
) AS v(code, name, sort_order)
WHERE t.code = 'flashover_method'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.5 海拔修正
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'altitude_correction', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('none', '无', 0),
  ('formula1', '推荐公式1', 1),
  ('formula2', '推荐公式2', 2)
) AS v(code, name, sort_order)
WHERE t.code = 'altitude_correction'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.6 反击耐雷水平方法
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'fanji_naleishuiping_method', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('guicheng', '规程', 0),
  ('atp', 'ATP', 1)
) AS v(code, name, sort_order)
WHERE t.code = 'fanji_naleishuiping_method'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.7 绕击耐雷水平方法
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'raoji_naleishuiping_method', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('guicheng', '规程', 0),
  ('atp', 'ATP', 1)
) AS v(code, name, sort_order)
WHERE t.code = 'raoji_naleishuiping_method'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.8 反击跳闸率方法
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'fanji_tzl_method', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('none', '无', 0),
  ('guicheng', '规程', 1),
  ('egm', 'EGM', 2)
) AS v(code, name, sort_order)
WHERE t.code = 'fanji_tzl_method'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);

-- 2.9 绕击跳闸率方法
INSERT INTO dimension_item (id, dimension_type, type_id, code, name, is_enabled, sort_order, create_date, create_user, update_date, update_user)
SELECT replace(gen_random_uuid()::text, '-', ''), 'raoji_tzl_method', t.id, v.code, v.name, TRUE, v.sort_order, NOW() AT TIME ZONE 'UTC', 'system', NOW() AT TIME ZONE 'UTC', 'system'
FROM dimension_type t
CROSS JOIN (VALUES
  ('none', '无', 0),
  ('guicheng', '规程', 1),
  ('egm', 'EGM', 2)
) AS v(code, name, sort_order)
WHERE t.code = 'raoji_tzl_method'
  AND NOT EXISTS (SELECT 1 FROM dimension_item i WHERE i.type_id = t.id AND i.code = v.code);
