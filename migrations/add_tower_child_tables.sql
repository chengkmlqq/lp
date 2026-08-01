-- Migration: Decompose tower JSON columns into dedicated child tables
-- Issue: LP-181 【需求评审】杆塔数据级联表改造：JSON 参数拆分建表
-- Date: 2026-08-01
-- Description:
--   - tower.circuit_geometry_json        -> tower_circuit (1:N, I~IV)
--   - tower.lightning_result_json        -> tower_lightning_result (1:1)
--   - profile.geometry_layers_json       -> REMOVED (回路几何单表 tower_circuit, 消除双写)
--   - profile.extra_profile_json(cause/mitigation) -> tower_analysis (1:1)
--   - line.phase_sequence_json / arrester_install_json / lightning_param_json 保持过渡期(后续拆列)
-- Usage: psql -f migrations/add_tower_child_tables.sql <dbname>

BEGIN;

-- ① 回路几何表（新增，1:N，每基杆塔最多 4 回）
CREATE TABLE IF NOT EXISTS tower_circuit (
    id               VARCHAR(32) PRIMARY KEY,
    tower_id         VARCHAR(32) NOT NULL REFERENCES power_line_tower(id) ON DELETE CASCADE,
    circuit_no       SMALLINT NOT NULL,
    phase_sequence   VARCHAR(32),
    spacing_upper_m  DOUBLE PRECISION,
    spacing_middle_m DOUBLE PRECISION,
    spacing_lower_m  DOUBLE PRECISION,
    height_upper_m   DOUBLE PRECISION,
    height_middle_m  DOUBLE PRECISION,
    height_lower_m   DOUBLE PRECISION,
    create_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    update_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tower_circuit_tower_circuit_no ON tower_circuit(tower_id, circuit_no);
CREATE INDEX IF NOT EXISTS idx_tower_circuit_tower_id ON tower_circuit(tower_id);

-- ② 雷电计算结果表（新增，1:1）
CREATE TABLE IF NOT EXISTS tower_lightning_result (
    id                      VARCHAR(32) PRIMARY KEY,
    tower_id                VARCHAR(32) NOT NULL UNIQUE REFERENCES power_line_tower(id) ON DELETE CASCADE,
    counterstroke_indicator SMALLINT,
    counterstroke_withstand_ka DOUBLE PRECISION,
    counterstroke_trip_rate   DOUBLE PRECISION,
    shielding_withstand_ka    DOUBLE PRECISION,
    shielding_trip_rate       DOUBLE PRECISION,
    angle_deg               DOUBLE PRECISION,
    current_a_ka            DOUBLE PRECISION,
    current_b_ka            DOUBLE PRECISION,
    risk_level              VARCHAR(32),
    create_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    update_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_tower_lightning_result_tower_id ON tower_lightning_result(tower_id);

-- ③ 分析建议表（新增，1:1）
CREATE TABLE IF NOT EXISTS tower_analysis (
    id          VARCHAR(32) PRIMARY KEY,
    tower_id    VARCHAR(32) NOT NULL UNIQUE REFERENCES power_line_tower(id) ON DELETE CASCADE,
    cause_analysis        TEXT,
    mitigation_recommendation TEXT,
    create_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    update_date TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

CREATE INDEX IF NOT EXISTS idx_tower_analysis_tower_id ON tower_analysis(tower_id);

-- ④ 数据搬迁：回路几何（I~IV 回逐回）
-- 从 tower.circuit_geometry_json（优先）与 profile.geometry_layers_json（兜底）拆出
-- phase_sequence 取自 tower_profile.phase_sequence_1..4（按回路号 I=1,II=2,III=3,IV=4）
INSERT INTO tower_circuit (id, tower_id, circuit_no, phase_sequence,
                           spacing_upper_m, spacing_middle_m, spacing_lower_m,
                           height_upper_m, height_middle_m, height_lower_m)
SELECT
    md5(tower.id || ':' || 1)::uuid::text,
    tower.id,
    1,
    profile.phase_sequence_1,
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_spacing_m,upper}')::float,
             (profile.geometry_layers_json #>> '{I,phase_spacing_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_spacing_m,middle}')::float,
             (profile.geometry_layers_json #>> '{I,phase_spacing_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_spacing_m,lower}')::float,
             (profile.geometry_layers_json #>> '{I,phase_spacing_m,lower}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_height_m,upper}')::float,
             (profile.geometry_layers_json #>> '{I,phase_height_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_height_m,middle}')::float,
             (profile.geometry_layers_json #>> '{I,phase_height_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{I,phase_height_m,lower}')::float,
             (profile.geometry_layers_json #>> '{I,phase_height_m,lower}')::float)
FROM power_line_tower tower
LEFT JOIN tower_profile profile ON profile.tower_id = tower.id
WHERE COALESCE((tower.circuit_geometry_json #>> '{I,phase_spacing_m,upper}'),
               (tower.circuit_geometry_json #>> '{I,phase_spacing_m,middle}'),
               (tower.circuit_geometry_json #>> '{I,phase_spacing_m,lower}'),
               (tower.circuit_geometry_json #>> '{I,phase_height_m,upper}'),
               (tower.circuit_geometry_json #>> '{I,phase_height_m,middle}'),
               (tower.circuit_geometry_json #>> '{I,phase_height_m,lower}'),
               (profile.geometry_layers_json #>> '{I,phase_spacing_m,upper}'),
               (profile.geometry_layers_json #>> '{I,phase_spacing_m,middle}'),
               (profile.geometry_layers_json #>> '{I,phase_spacing_m,lower}'),
               (profile.geometry_layers_json #>> '{I,phase_height_m,upper}'),
               (profile.geometry_layers_json #>> '{I,phase_height_m,middle}'),
               (profile.geometry_layers_json #>> '{I,phase_height_m,lower}')) IS NOT NULL;

INSERT INTO tower_circuit (id, tower_id, circuit_no, phase_sequence,
                           spacing_upper_m, spacing_middle_m, spacing_lower_m,
                           height_upper_m, height_middle_m, height_lower_m)
SELECT
    md5(tower.id || ':' || 2)::uuid::text,
    tower.id,
    2,
    profile.phase_sequence_2,
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_spacing_m,upper}')::float,
             (profile.geometry_layers_json #>> '{II,phase_spacing_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_spacing_m,middle}')::float,
             (profile.geometry_layers_json #>> '{II,phase_spacing_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_spacing_m,lower}')::float,
             (profile.geometry_layers_json #>> '{II,phase_spacing_m,lower}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_height_m,upper}')::float,
             (profile.geometry_layers_json #>> '{II,phase_height_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_height_m,middle}')::float,
             (profile.geometry_layers_json #>> '{II,phase_height_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{II,phase_height_m,lower}')::float,
             (profile.geometry_layers_json #>> '{II,phase_height_m,lower}')::float)
FROM power_line_tower tower
LEFT JOIN tower_profile profile ON profile.tower_id = tower.id
WHERE COALESCE((tower.circuit_geometry_json #>> '{II,phase_spacing_m,upper}'),
               (tower.circuit_geometry_json #>> '{II,phase_spacing_m,middle}'),
               (tower.circuit_geometry_json #>> '{II,phase_spacing_m,lower}'),
               (tower.circuit_geometry_json #>> '{II,phase_height_m,upper}'),
               (tower.circuit_geometry_json #>> '{II,phase_height_m,middle}'),
               (tower.circuit_geometry_json #>> '{II,phase_height_m,lower}'),
               (profile.geometry_layers_json #>> '{II,phase_spacing_m,upper}'),
               (profile.geometry_layers_json #>> '{II,phase_spacing_m,middle}'),
               (profile.geometry_layers_json #>> '{II,phase_spacing_m,lower}'),
               (profile.geometry_layers_json #>> '{II,phase_height_m,upper}'),
               (profile.geometry_layers_json #>> '{II,phase_height_m,middle}'),
               (profile.geometry_layers_json #>> '{II,phase_height_m,lower}')) IS NOT NULL;

INSERT INTO tower_circuit (id, tower_id, circuit_no, phase_sequence,
                           spacing_upper_m, spacing_middle_m, spacing_lower_m,
                           height_upper_m, height_middle_m, height_lower_m)
SELECT
    md5(tower.id || ':' || 3)::uuid::text,
    tower.id,
    3,
    profile.phase_sequence_3,
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_spacing_m,upper}')::float,
             (profile.geometry_layers_json #>> '{III,phase_spacing_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_spacing_m,middle}')::float,
             (profile.geometry_layers_json #>> '{III,phase_spacing_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_spacing_m,lower}')::float,
             (profile.geometry_layers_json #>> '{III,phase_spacing_m,lower}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_height_m,upper}')::float,
             (profile.geometry_layers_json #>> '{III,phase_height_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_height_m,middle}')::float,
             (profile.geometry_layers_json #>> '{III,phase_height_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{III,phase_height_m,lower}')::float,
             (profile.geometry_layers_json #>> '{III,phase_height_m,lower}')::float)
FROM power_line_tower tower
LEFT JOIN tower_profile profile ON profile.tower_id = tower.id
WHERE COALESCE((tower.circuit_geometry_json #>> '{III,phase_spacing_m,upper}'),
               (tower.circuit_geometry_json #>> '{III,phase_spacing_m,middle}'),
               (tower.circuit_geometry_json #>> '{III,phase_spacing_m,lower}'),
               (tower.circuit_geometry_json #>> '{III,phase_height_m,upper}'),
               (tower.circuit_geometry_json #>> '{III,phase_height_m,middle}'),
               (tower.circuit_geometry_json #>> '{III,phase_height_m,lower}'),
               (profile.geometry_layers_json #>> '{III,phase_spacing_m,upper}'),
               (profile.geometry_layers_json #>> '{III,phase_spacing_m,middle}'),
               (profile.geometry_layers_json #>> '{III,phase_spacing_m,lower}'),
               (profile.geometry_layers_json #>> '{III,phase_height_m,upper}'),
               (profile.geometry_layers_json #>> '{III,phase_height_m,middle}'),
               (profile.geometry_layers_json #>> '{III,phase_height_m,lower}')) IS NOT NULL;

INSERT INTO tower_circuit (id, tower_id, circuit_no, phase_sequence,
                           spacing_upper_m, spacing_middle_m, spacing_lower_m,
                           height_upper_m, height_middle_m, height_lower_m)
SELECT
    md5(tower.id || ':' || 4)::uuid::text,
    tower.id,
    4,
    profile.phase_sequence_4,
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_spacing_m,upper}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_spacing_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_spacing_m,middle}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_spacing_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_spacing_m,lower}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_spacing_m,lower}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_height_m,upper}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_height_m,upper}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_height_m,middle}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_height_m,middle}')::float),
    COALESCE((tower.circuit_geometry_json #>> '{IV,phase_height_m,lower}')::float,
             (profile.geometry_layers_json #>> '{IV,phase_height_m,lower}')::float)
FROM power_line_tower tower
LEFT JOIN tower_profile profile ON profile.tower_id = tower.id
WHERE COALESCE((tower.circuit_geometry_json #>> '{IV,phase_spacing_m,upper}'),
               (tower.circuit_geometry_json #>> '{IV,phase_spacing_m,middle}'),
               (tower.circuit_geometry_json #>> '{IV,phase_spacing_m,lower}'),
               (tower.circuit_geometry_json #>> '{IV,phase_height_m,upper}'),
               (tower.circuit_geometry_json #>> '{IV,phase_height_m,middle}'),
               (tower.circuit_geometry_json #>> '{IV,phase_height_m,lower}'),
               (profile.geometry_layers_json #>> '{IV,phase_spacing_m,upper}'),
               (profile.geometry_layers_json #>> '{IV,phase_spacing_m,middle}'),
               (profile.geometry_layers_json #>> '{IV,phase_spacing_m,lower}'),
               (profile.geometry_layers_json #>> '{IV,phase_height_m,upper}'),
               (profile.geometry_layers_json #>> '{IV,phase_height_m,middle}'),
               (profile.geometry_layers_json #>> '{IV,phase_height_m,lower}')) IS NOT NULL;

-- 注：profile.geometry_layers_json / tower.circuit_geometry_json / tower.lightning_result_json
-- 在过渡期保留，验证通过后再删除（见需求「删除 JSON 列（保留过渡期）」）。

-- ⑤ 数据搬迁：雷电结果
INSERT INTO tower_lightning_result (id, tower_id,
    counterstroke_indicator, counterstroke_withstand_ka, counterstroke_trip_rate,
    shielding_withstand_ka, shielding_trip_rate, risk_level)
SELECT
    md5('lr:' || tower.id)::uuid::text,
    tower.id,
    (tower.lightning_result_json ->> 'counterstroke_indicator')::smallint,
    (tower.lightning_result_json ->> 'counterstroke_withstand_ka')::float,
    (tower.lightning_result_json ->> 'counterstroke_trip_rate')::float,
    (tower.lightning_result_json ->> 'shielding_withstand_ka')::float,
    (tower.lightning_result_json ->> 'shielding_trip_rate')::float,
    tower.lightning_result_json ->> 'risk_level'
FROM power_line_tower tower
WHERE tower.lightning_result_json IS NOT NULL
  AND COALESCE((tower.lightning_result_json ->> 'counterstroke_withstand_ka'),
               (tower.lightning_result_json ->> 'shielding_withstand_ka'),
               (tower.lightning_result_json ->> 'counterstroke_trip_rate'),
               (tower.lightning_result_json ->> 'shielding_trip_rate')) IS NOT NULL;

-- ⑥ 数据搬迁：分析建议
INSERT INTO tower_analysis (id, tower_id, cause_analysis, mitigation_recommendation)
SELECT
    md5('ta:' || profile.tower_id)::uuid::text,
    profile.tower_id,
    profile.extra_profile_json ->> 'cause_analysis',
    profile.extra_profile_json ->> 'mitigation_recommendation'
FROM tower_profile profile
WHERE profile.extra_profile_json IS NOT NULL
  AND COALESCE((profile.extra_profile_json ->> 'cause_analysis'),
               (profile.extra_profile_json ->> 'mitigation_recommendation')) IS NOT NULL;

-- ⑦ 条数一致性校验（仅供人工核对，不影响迁移）
-- SELECT 'tower_circuit' AS table_name, count(*) FROM tower_circuit
-- UNION ALL SELECT 'tower_lightning_result', count(*) FROM tower_lightning_result
-- UNION ALL SELECT 'tower_analysis', count(*) FROM tower_analysis
-- UNION ALL SELECT 'power_line_tower', count(*) FROM power_line_tower;

COMMIT;
