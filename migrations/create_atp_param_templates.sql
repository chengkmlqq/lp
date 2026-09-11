-- ATP 参数模板（配置化）：模板规则表 + 全局槽位表
-- 目标：把 compute_csharp_atp_params 里写死的「塔型 → 槽位映射 + 电压系数 + 钳制」抽成配置，
--       支持从粗到细的覆盖链（L0 全局 → L2 塔型 → L3 电压/回路/场景/避雷器 …），页面可视化维护。
-- 幂等：CREATE TABLE IF NOT EXISTS + 种子按唯一维度键 ON CONFLICT DO UPDATE。
-- 维度列可空 = 通配（不参与匹配）；specificity 由应用层按非空维度个数计算。

CREATE TABLE IF NOT EXISTS atp_param_template (
    id                varchar(36) PRIMARY KEY,
    name              varchar(128) NOT NULL,
    marker            varchar(64),
    tower_type        varchar(64),
    voltage_level     varchar(16),
    circuit_count     integer,
    scene_type        varchar(32),
    arrester_config   varchar(64),
    structure_kind    varchar(32),
    priority          integer     NOT NULL DEFAULT 100,
    mode              varchar(16) NOT NULL DEFAULT 'merge',
    enabled           boolean     NOT NULL DEFAULT true,
    fallback_to       varchar(64),
    fallback_enabled  boolean     NOT NULL DEFAULT true,
    slots_json        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        varchar(64)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atp_param_template_dims ON atp_param_template (
    COALESCE(tower_type, ''),
    COALESCE(voltage_level, ''),
    COALESCE(circuit_count::text, ''),
    COALESCE(scene_type, ''),
    COALESCE(arrester_config, ''),
    COALESCE(structure_kind, '')
);

CREATE INDEX IF NOT EXISTS ix_atp_param_template_tower ON atp_param_template (tower_type);

CREATE TABLE IF NOT EXISTS atp_param_global (
    slot        varchar(32) PRIMARY KEY,
    expr        text,
    value       varchar(32),
    when_expr   text,
    else_value  varchar(32),
    fmt         integer     NOT NULL DEFAULT 2,
    enabled     boolean     NOT NULL DEFAULT true,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  varchar(64)
);

-- ============================ 种子（与 api/app/services/atp_param_mappings/*.json 一致） ============================
INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('ganzi', '干字（默认分支）', 'ganzi', 'ganzi', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "h_u", "fmt": 1}, "RELE02": {"expr": "h_u * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(sp_u)", "fmt": 1}, "RELE04": {"expr": "abs(sp_l)", "fmt": 1}, "RELE05": {"expr": "clamp(abs(h_m - h_u), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "RELE07": {"expr": "clamp(abs(shield_h - h_m), 1.5)", "fmt": 2}, "RELE08": {"expr": "RELE07 * 1.5", "fmt": 2}, "RELE09": {"expr": "abs(lw_l_eff)", "fmt": 2}, "RELE10": {"expr": "abs(lw_r_eff)", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(2.0, 1.2, 2.0, 10.0 / 3.0, 10.0 / 3.0, 8.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 6.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs(h_m - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 6.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 6.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('guxing', '鼓型（含单回 guxingd）', 'guxing', 'guxing', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, 'ganzi', true, '{"RELE01": {"expr": "h_l", "fmt": 1}, "RELE02": {"expr": "h_l * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(sp_l)", "fmt": 1}, "RELE04": {"expr": "clamp(abs(h_m - h_l), 1.5)", "fmt": 2}, "RELE05": {"expr": "RELE04 * 1.5", "fmt": 2}, "RELE06": {"expr": "abs(sp_m)", "fmt": 1}, "RELE07": {"expr": "clamp(abs(h_u - h_m), 1.5)", "fmt": 2}, "RELE08": {"expr": "RELE07 * 1.5", "fmt": 2}, "RELE09": {"expr": "abs(sp_u)", "fmt": 2}, "RELE10": {"expr": "clamp(abs(shield_h - h_u), 1.5)", "fmt": 2}, "RELE11": {"expr": "RELE10 * 1.5", "fmt": 2}, "RELE12": {"expr": "abs(lw_l)", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(2.0, 1.2, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs(h_m - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - v(10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('jiubei', '酒杯型', 'jiubei', 'jiubei', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "abs(tower_h - v(3.5, 8.6, 8.6, 8.5, 10.5, 14.0, 20.0, 28.9))", "fmt": 1}, "RELE02": {"expr": "RELE01 * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(sp_u - v(2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7))", "fmt": 1}, "RELE04": {"expr": "abs(sp_l - v(2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7))", "fmt": 1}, "RELE05": {"expr": "abs(sqrt((abs(lw_l) - v(2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7)) ** 2 + (shield_h - h_u - v(0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0)) ** 2))", "fmt": 2}, "RELE06": {"expr": "abs(sqrt((abs(lw_r) - v(2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7)) ** 2 + (shield_h - h_l - v(0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0)) ** 2))", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(1.2, 2.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - v(1.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs(h_m - insul_m - v(1.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - v(1.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('maotou', '猫头型', 'maotou', 'maotou', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "abs(tower_h - abs(lw_l) * v(0.4245, 0.4245, 0.4245, 0.7954, 0.7954, 0.6249, 0.6249, 0.6249))", "fmt": 2}, "RELE02": {"expr": "RELE01 * 1.5", "fmt": 2}, "RELE03": {"expr": "abs(lw_l) / v(0.9205, 0.9205, 0.9205, 0.7826, 0.7826, 0.8480, 0.8480, 0.8480)", "fmt": 2}, "RELE04": {"expr": "RELE03 * 1.5", "fmt": 2}, "RELE05": {"expr": "clamp(round(abs(shield_h - h_u - v(1.5, 1.5, 1.5, 2.7, 1.9, 3.6, 3.6, 3.6)), 2), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "RELE07": {"expr": "lw_l", "fmt": 2}, "RELE08": {"expr": "lw_r", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(2.0, 2.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - v(10.0 / 3.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - v(10.0 / 3.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs((h_u + shield_h - v(1.5, 1.5, 1.5, 2.0, 2.0, 1.6, 2.0, 3.5)) / 2.0 - v(10.0 / 3.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('maotou_1000', '猫头型 · 1000kV', 'maotou_1000', 'maotou', '1000', NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "abs(tower_h - (abs(lw_l) - 3.5) * 1.19)", "fmt": 2}, "RELE02": {"expr": "RELE01 * 1.5", "fmt": 2}, "RELE03": {"expr": "(abs(lw_l) - 3.5) / 0.6428", "fmt": 2}, "RELE04": {"expr": "RELE03 * 1.5", "fmt": 2}, "RELE05": {"expr": "clamp(round(abs(shield_h - h_u - 3.5), 2), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "RELE07": {"expr": "lw_l - 3.5", "fmt": 2}, "RELE08": {"expr": "lw_r - 3.5", "fmt": 2}, "REHG______": {"expr": "abs(shield_h)", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m)", "fmt": 1}, "REHC2_____": {"expr": "abs((h_u + shield_h - 3.5) / 2.0)", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m)", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('maotou_750', '猫头型 · 750kV', 'maotou_750', 'maotou', '750', NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "tower_h", "fmt": 2}, "RELE02": {"expr": "RELE01 * 1.5", "fmt": 2}, "RELE03": {"expr": "abs(lw_l)", "fmt": 2}, "RELE04": {"expr": "RELE03 * 1.5", "fmt": 2}, "RELE05": {"expr": "clamp(round(abs(shield_h - h_u), 2), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "REHG______": {"expr": "abs(shield_h)", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m)", "fmt": 1}, "REHC2_____": {"expr": "abs((h_u + shield_h) / 2.0)", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m)", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('menxing', '门型', 'menxing', 'menxing', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "tower_h", "fmt": 1}, "RELE02": {"expr": "RELE01 * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(sp_u) / 2.0", "fmt": 1}, "RELE04": {"expr": "abs(sp_l) / 2.0", "fmt": 1}, "RELE05": {"expr": "abs(sqrt((abs(lw_l) - abs(sp_u) / 2.0) ** 2 + (shield_h - h_u - 1.0) ** 2))", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(0.0, 0.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - v(0.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs(h_m - insul_m - v(0.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - v(0.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('shangzi', '上字型', 'shangzi', 'shangzi', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "h_u", "fmt": 1}, "RELE02": {"expr": "h_u * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(sp_u)", "fmt": 1}, "RELE04": {"expr": "abs(sp_l)", "fmt": 1}, "RELE05": {"expr": "clamp(abs(h_m - h_u), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "RELE07": {"expr": "clamp(abs(shield_h - h_m), 1.5)", "fmt": 2}, "RELE08": {"expr": "RELE07 * 1.5", "fmt": 2}, "RELE09": {"expr": "abs(lw_l)", "fmt": 2}, "RELE10": {"expr": "abs(lw_r)", "fmt": 2}, "RELE11": {"expr": "abs(sp_m)", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - 1.2)", "fmt": 1}, "REHC1_____": {"expr": "abs(h_u - insul_m - 1.5)", "fmt": 1}, "REHC2_____": {"expr": "abs(h_m - insul_m - 1.5)", "fmt": 1}, "REHC3_____": {"expr": "abs(h_l - insul_m - 1.5)", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_template (id, name, marker, tower_type, voltage_level, circuit_count, scene_type, arrester_config, structure_kind, priority, mode, enabled, fallback_to, fallback_enabled, slots_json, updated_by)
VALUES ('sihuita', '四回路型', 'sihuita', 'sihuita', NULL, NULL, NULL, NULL, NULL, 100, 'merge', true, NULL, true, '{"RELE01": {"expr": "c3_l", "fmt": 1}, "RELE02": {"expr": "c3_l * 1.5", "fmt": 1}, "RELE03": {"expr": "abs(c3_sp_l)", "fmt": 1}, "RELE04": {"expr": "abs(c4_sp_l)", "fmt": 1}, "RELE05": {"expr": "clamp(abs(c3_m - c3_l), 1.5)", "fmt": 2}, "RELE06": {"expr": "RELE05 * 1.5", "fmt": 2}, "RELE07": {"expr": "abs(c3_sp_m)", "fmt": 2}, "RELE08": {"expr": "abs(c4_sp_m)", "fmt": 2}, "RELE09": {"expr": "clamp(abs(c3_u - c3_m), 1.5)", "fmt": 2}, "RELE10": {"expr": "RELE09 * 1.5", "fmt": 2}, "RELE11": {"expr": "abs(c3_sp_u)", "fmt": 2}, "RELE12": {"expr": "abs(c4_sp_u)", "fmt": 2}, "RELE13": {"expr": "abs(c1_l - c3_u)", "fmt": 2}, "RELE14": {"expr": "RELE13 * 1.5", "fmt": 2}, "RELE15": {"expr": "abs(c1_sp_l)", "fmt": 1}, "RELE16": {"expr": "abs(c2_sp_l)", "fmt": 1}, "RELE17": {"expr": "clamp(abs(c1_m - c1_l), 1.5)", "fmt": 2}, "RELE18": {"expr": "RELE17 * 1.5", "fmt": 2}, "RELE19": {"expr": "abs(c1_sp_m)", "fmt": 2}, "RELE20": {"expr": "abs(c2_sp_m)", "fmt": 2}, "RELE21": {"expr": "clamp(abs(c1_u - c1_m), 1.5)", "fmt": 2}, "RELE22": {"expr": "RELE21 * 1.5", "fmt": 2}, "RELE23": {"expr": "abs(c1_sp_u)", "fmt": 2}, "RELE24": {"expr": "abs(c2_sp_u)", "fmt": 2}, "RELE25": {"expr": "abs(sqrt((shield_h - c1_u) ** 2 + (lw_l - c1_sp_u) ** 2))", "fmt": 2}, "RELE26": {"expr": "abs(sqrt((shield_h - c2_u) ** 2 + (lw_r - c2_sp_u) ** 2))", "fmt": 2}, "REHG______": {"expr": "abs(shield_h - v(2.0, 0.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0))", "fmt": 1}, "REHC1_____": {"expr": "abs(c1_u - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC2_____": {"expr": "abs(c1_m - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC3_____": {"expr": "abs(c1_l - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC4_____": {"expr": "abs(c3_u - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC5_____": {"expr": "abs(c3_m - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}, "REHC6_____": {"expr": "abs(c3_l - insul_m - v(10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0))", "fmt": 1}}'::jsonb, 'migration')
ON CONFLICT (COALESCE(tower_type, ''), COALESCE(voltage_level, ''), COALESCE(circuit_count::text, ''), COALESCE(scene_type, ''), COALESCE(arrester_config, ''), COALESCE(structure_kind, ''))
DO UPDATE SET name = EXCLUDED.name, marker = EXCLUDED.marker, priority = EXCLUDED.priority, mode = EXCLUDED.mode, enabled = EXCLUDED.enabled, fallback_to = EXCLUDED.fallback_to, fallback_enabled = EXCLUDED.fallback_enabled, slots_json = EXCLUDED.slots_json, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('RER001', 'ground_r', NULL, NULL, NULL, 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('RELENS____', 'insul_m', NULL, NULL, NULL, 2, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REIGAN____', 'abs(current_ka)', NULL, NULL, NULL, 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REIAMP____', '-abs(current_ka) * 1000.0', NULL, NULL, NULL, 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('HIAMP_____', '-abs(current_ka) * 1000.0 * 0.5', NULL, NULL, NULL, 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REBB______', '-1.0E6 / head_ms', NULL, 'head_ms and head_ms > 0', '1.', 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REAA1_____', 'head_ms * 1.0E-6', NULL, 'head_ms and head_ms > 0', '1.', 7, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REAA______', '-1.0E6 / tail_ms', NULL, 'tail_ms and tail_ms > 0', '1.', 1, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REBB1_____', 'tail_ms * 1.0E-6', NULL, 'tail_ms and tail_ms > 0', '1.', 7, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REHHEI____', NULL, '1.', 'wave_type != 2 and wave_type != 3', '0.', 2, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REHSLO____', NULL, '1.', 'wave_type == 2', '0.', 2, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;

INSERT INTO atp_param_global (slot, expr, value, when_expr, else_value, fmt, enabled, updated_by)
VALUES ('REHSUR____', NULL, '1.', 'wave_type == 3', '0.', 2, true, 'migration')
ON CONFLICT (slot) DO UPDATE SET expr = EXCLUDED.expr, value = EXCLUDED.value, when_expr = EXCLUDED.when_expr, else_value = EXCLUDED.else_value, fmt = EXCLUDED.fmt, enabled = EXCLUDED.enabled, updated_at = now(), updated_by = EXCLUDED.updated_by;
