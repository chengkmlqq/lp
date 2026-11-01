-- Migration: ATP 测试线路 / 单塔基准（atp_test_line / atp_test_line_circuit）
-- Date: 2026-11-01
--
-- 背景：ATP 模型测试的输入本质是「一基杆塔 + 一档线路」的完整物理描述
-- （呼高、绝缘子串长、避雷线高度与左右中距、保护角、相序、回路几何、档距、接地电阻）。
-- 此前没有一等实体承载它：要么手工填 base_tower/profile 两个 JSON，要么从外业台账
-- 里随手挑一基真实杆塔 —— 同一维度组挑不同塔，结果不可比。
--
-- 本迁移建立受控的「测试线路」实体：
--   * 几何维 voltage_level × tower_type × shield_wire 决定杆塔几何（唯一键）
--   * 标签维 scene_type × arrester_config 不改变几何（只用于模型选择/参数规则）
--   * snapshot_json 冻结装配结果 → 同一条测试线路 = 逐字节相同的输入 = 可复现基准
--
-- 同时对既有表做向后兼容的加列（全部 nullable / 带默认）：
--   atp_asset.test_line_id                       模型级绑定测试线路（优先命中）
--   atp_test_set_case.test_line_id               用例绑定测试线路
--   atp_test_set_case.test_line_snapshot_hash    生成时快照指纹（检测「基准已变更」）
--   dimension_item.extra_json                    维度项工程默认值（派生依据）
--
-- 幂等性：CREATE TABLE / CREATE INDEX 用 IF NOT EXISTS 可重跑；
-- ALTER TABLE ADD COLUMN 重复执行会报 duplicate column（PG 42701），可忽略。

-- ─────────────────────────── 测试线路主表 ───────────────────────────

CREATE TABLE IF NOT EXISTS atp_test_line (
    id VARCHAR(32) PRIMARY KEY,
    code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'enabled',

    -- 维度键
    voltage_level VARCHAR(16) NOT NULL,
    tower_type VARCHAR(64) NOT NULL,
    shield_wire VARCHAR(16) NOT NULL DEFAULT 'with',
    scene_type VARCHAR(32),
    arrester_config VARCHAR(64),
    structure_kind VARCHAR(20),
    circuit_count SMALLINT NOT NULL DEFAULT 1,

    -- 绑定（NULL = 该几何维组共享基准；非空 = 某模型专用样本）
    asset_id VARCHAR(32) REFERENCES atp_asset (id) ON DELETE SET NULL,

    -- 线路环境
    span_small_m DOUBLE PRECISION,
    span_large_m DOUBLE PRECISION,
    ground_resistance_ohm DOUBLE PRECISION,
    lightning_density DOUBLE PRECISION,
    -- 以下三项当前无消费方（几何/仿真管线未读取），仅记录+展示，
    -- compare.json 里显式标注 not_consumed=true
    altitude_m DOUBLE PRECISION,
    terrain VARCHAR(64),
    slope_1 DOUBLE PRECISION,
    slope_2 DOUBLE PRECISION,

    -- 杆塔属性
    tower_no VARCHAR(64),
    tower_model VARCHAR(128),
    call_height_m DOUBLE PRECISION,
    -- 单位：米（TowerProfile 历史存毫米，下游按「>100 视为 mm」自动换算）
    insulator_length_m DOUBLE PRECISION,
    shield_wire_height_m DOUBLE PRECISION,
    shield_wire_left_mid_m DOUBLE PRECISION,
    shield_wire_right_mid_m DOUBLE PRECISION,
    protection_angle_left_deg DOUBLE PRECISION,
    protection_angle_right_deg DOUBLE PRECISION,
    angle_deg DOUBLE PRECISION,
    phase_sequence_1 VARCHAR(32),
    phase_sequence_2 VARCHAR(32),
    phase_sequence_3 VARCHAR(32),
    phase_sequence_4 VARCHAR(32),
    arrester_a VARCHAR(64),
    arrester_b VARCHAR(64),
    arrester_c VARCHAR(64),

    -- 雷电流
    current_ka DOUBLE PRECISION NOT NULL DEFAULT 31.0,
    current_type VARCHAR(32),
    current_head_time_us DOUBLE PRECISION,
    current_tail_time_us DOUBLE PRECISION,

    -- 溯源与冻结
    source_kind VARCHAR(20) NOT NULL DEFAULT 'manual',
    source_asset_id VARCHAR(32),
    source_run_id VARCHAR(32),
    source_tower_id VARCHAR(32),
    derive_rules_json JSON NOT NULL DEFAULT '{}',
    snapshot_json JSON NOT NULL DEFAULT '{}',
    snapshot_hash VARCHAR(64),
    snapshot_date TIMESTAMPTZ,

    used_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,

    create_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    create_user VARCHAR(64),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_user VARCHAR(64),

    CONSTRAINT uq_atp_test_line_code UNIQUE (code),
    CONSTRAINT uq_atp_test_line_geometry_key
        UNIQUE (voltage_level, tower_type, shield_wire, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_atp_test_line_geometry
    ON atp_test_line (voltage_level, tower_type, shield_wire);
CREATE INDEX IF NOT EXISTS idx_atp_test_line_asset ON atp_test_line (asset_id);
CREATE INDEX IF NOT EXISTS idx_atp_test_line_status ON atp_test_line (status);
CREATE INDEX IF NOT EXISTS idx_atp_test_line_scene ON atp_test_line (scene_type);
CREATE INDEX IF NOT EXISTS idx_atp_test_line_create_user ON atp_test_line (create_user);
CREATE INDEX IF NOT EXISTS idx_atp_test_line_update_user ON atp_test_line (update_user);

-- ─────────────────────────── 回路几何（1:N ≤ 4）───────────────────────────

CREATE TABLE IF NOT EXISTS atp_test_line_circuit (
    id VARCHAR(32) PRIMARY KEY,
    test_line_id VARCHAR(32) NOT NULL REFERENCES atp_test_line (id) ON DELETE CASCADE,
    circuit_no SMALLINT NOT NULL,
    phase_sequence VARCHAR(32),
    spacing_upper_m DOUBLE PRECISION,
    spacing_middle_m DOUBLE PRECISION,
    spacing_lower_m DOUBLE PRECISION,
    height_upper_m DOUBLE PRECISION,
    height_middle_m DOUBLE PRECISION,
    height_lower_m DOUBLE PRECISION,
    create_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_atp_test_line_circuit_no UNIQUE (test_line_id, circuit_no)
);

CREATE INDEX IF NOT EXISTS idx_atp_test_line_circuit_line
    ON atp_test_line_circuit (test_line_id);

-- ─────────────────────────── 既有表加列 ───────────────────────────

-- 模型级绑定：非空时优先于几何维匹配（「这个模型必须用专用样本」）
ALTER TABLE atp_asset ADD COLUMN test_line_id VARCHAR(32);

-- 用例绑定测试线路 + 生成时的快照指纹（用于「基准已变更」告警）
ALTER TABLE atp_test_set_case ADD COLUMN test_line_id VARCHAR(32);
ALTER TABLE atp_test_set_case ADD COLUMN test_line_snapshot_hash VARCHAR(64);

-- 维度项工程默认值载体：让「选 500kV」不只拿到标签，还能拿到工程参考值
ALTER TABLE dimension_item ADD COLUMN extra_json JSON NOT NULL DEFAULT '{}';
