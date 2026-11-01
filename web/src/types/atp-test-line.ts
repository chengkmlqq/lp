/**
 * ATP 测试线路（单塔基准）类型。
 *
 * 语义回顾：
 * - 几何维 `voltage_level × tower_type × shield_wire` 决定杆塔几何，是唯一键；
 *   同一几何维只允许一条 `asset_id = null` 的共享基准（应用层校验）。
 * - `asset_id` 非空 = 模型专用样本（只给该模型用）。
 * - `insulator_length_m` 单位**米**（后端按「> 100 视为毫米」兼容历史数据）。
 * - 快照冻结：`snapshot_hash` 变了说明基准参数变了，历史结果不可直接对比。
 */

export type AtpTestLineStatus = "enabled" | "disabled" | "frozen";
export type AtpTestLineSourceKind = "derived" | "manual" | "from_tower" | "from_asset_run";

/** 派生/resolve 的命中方式 */
export type AtpTestLineMatchedBy = "bound" | "geometry" | "degraded" | "none";

export type AtpTestLineIssue = {
  field: string;
  reason: string;
};

export type AtpTestLineCircuit = {
  circuit_no: number;
  phase_sequence?: string | null;
  spacing_upper_m?: number | null;
  spacing_middle_m?: number | null;
  spacing_lower_m?: number | null;
  height_upper_m?: number | null;
  height_middle_m?: number | null;
  height_lower_m?: number | null;
};

export type AtpTestLineCircuitSummary = AtpTestLineCircuit & { id: string };

export type AtpTestLineSummary = {
  id: string;
  code: string;
  name: string;
  description: string;
  status: AtpTestLineStatus;
  voltage_level: string;
  tower_type: string;
  shield_wire: string;
  scene_type: string | null;
  arrester_config: string | null;
  structure_kind: string | null;
  circuit_count: number;
  asset_id: string | null;
  asset_code: string | null;
  span_small_m: number | null;
  span_large_m: number | null;
  call_height_m: number | null;
  insulator_length_m: number | null;
  current_ka: number;
  source_kind: AtpTestLineSourceKind;
  snapshot_hash: string | null;
  used_count: number;
  last_used_at: string | null;
  create_date: string;
  update_date: string;
  update_user: string | null;
};

/** 详情：在 summary 之上补全工程字段 + 回路几何 + 快照 + 派生来源 */
export type AtpTestLineDetail = AtpTestLineSummary & {
  ground_resistance_ohm: number | null;
  lightning_density: number | null;
  altitude_m: number | null;
  terrain: string | null;
  slope_1: number | null;
  slope_2: number | null;
  tower_no: string | null;
  tower_model: string | null;
  shield_wire_height_m: number | null;
  shield_wire_left_mid_m: number | null;
  shield_wire_right_mid_m: number | null;
  protection_angle_left_deg: number | null;
  protection_angle_right_deg: number | null;
  angle_deg: number | null;
  phase_sequence_1: string | null;
  phase_sequence_2: string | null;
  phase_sequence_3: string | null;
  phase_sequence_4: string | null;
  arrester_a: string | null;
  arrester_b: string | null;
  arrester_c: string | null;
  current_type: string | null;
  current_head_time_us: number | null;
  current_tail_time_us: number | null;
  source_asset_id: string | null;
  source_run_id: string | null;
  source_tower_id: string | null;
  /** 字段 → 来源（L1:run / L2:param_template / L3:tower_model / L4:dimension / L5:builtin / manual） */
  derive_rules_json: Record<string, string>;
  snapshot_json: Record<string, unknown>;
  snapshot_date: string | null;
  circuits: AtpTestLineCircuitSummary[];
};

export type AtpTestLineListResponse = {
  items: AtpTestLineSummary[];
  total: number;
};

/** 提交体：创建时除 code/name 外全部可传；编辑走 PATCH，只传改动字段 */
export type AtpTestLinePayload = Partial<
  Omit<AtpTestLineDetail, "id" | "asset_code" | "derive_rules_json" | "snapshot_json" | "snapshot_date" | "update_date" | "create_date" | "update_user" | "used_count" | "last_used_at" | "circuits">
> & {
  code?: string | null;
  name?: string | null;
  description?: string;
  circuits?: AtpTestLineCircuit[];
  reset_snapshot?: boolean;
};

export type AtpTestLineDeriveRequest = {
  asset_id?: string;
  voltage_level?: string;
  tower_type?: string;
  shield_wire?: string;
  scene_type?: string;
  arrester_config?: string;
  structure_kind?: string;
  source_tower_id?: string;
};

export type AtpTestLineDeriveResponse = {
  draft: Record<string, unknown>;
  /** 字段 → 来源标记（与 draft 同键） */
  sources: Record<string, string>;
  blockers: AtpTestLineIssue[];
  warnings: AtpTestLineIssue[];
  suggested_code: string | null;
  /** 有值但下游不消费的字段（地形/倾角/海拔），仅提示 */
  not_consumed: string[];
};

export type AtpTestLinePreviewResponse = {
  base_tower: Record<string, unknown>;
  profile: Record<string, unknown>;
  snapshot_hash: string;
  not_consumed: string[];
  blockers: AtpTestLineIssue[];
  warnings: AtpTestLineIssue[];
};

export type AtpTestLineUsageItem = {
  kind: "asset" | "test_set_case" | string;
  id: string;
  code: string | null;
  name: string | null;
};

export type AtpTestLineUsageResponse = {
  test_line_id: string;
  items: AtpTestLineUsageItem[];
  total: number;
};

export type AtpTestLineResolveResponse = {
  test_line: AtpTestLineSummary | null;
  matched_by: AtpTestLineMatchedBy;
  hint: string | null;
};

export type TestLineSourceTone =
  | "run"
  | "template"
  | "tower-model"
  | "dimension"
  | "builtin"
  | "manual"
  | "asset";

/**
 * 来源标记 → 展示文案与配色。
 * 越靠后越"软"：`L5:builtin` / `L4:dimension` 属于量级参考，界面上用黄色提醒复核。
 */
const SOURCE_META: Record<string, { label: string; tone: TestLineSourceTone }> = {
  "L1:run": { label: "历史运行", tone: "run" },
  "L1:tower": { label: "真实杆塔", tone: "run" },
  "L1:asset_run": { label: "历史运行", tone: "run" },
  "L2:param_template": { label: "参数模板", tone: "template" },
  "L3:tower_model": { label: "杆塔库", tone: "tower-model" },
  "L4:dimension": { label: "维度配置", tone: "dimension" },
  "L5:builtin": { label: "内置兜底", tone: "builtin" },
  manual: { label: "手填", tone: "manual" },
  asset: { label: "模型维度", tone: "asset" },
};

/** 后端可能返回 `L1:run:abcd1234` / `circuits[1]` 这类带后缀的标记，这里按前缀归一。 */
export function testLineSourceMeta(source: string | undefined | null): { label: string; tone: TestLineSourceTone } {
  if (!source) return { label: "未标注", tone: "manual" };
  if (SOURCE_META[source]) return SOURCE_META[source];
  if (source.startsWith("L1:run")) return { label: "历史运行", tone: "run" };
  if (source.startsWith("L2:")) return { label: "参数模板", tone: "template" };
  if (source.startsWith("L3:")) return { label: "杆塔库", tone: "tower-model" };
  if (source.startsWith("L4:")) return { label: "维度配置", tone: "dimension" };
  if (source.startsWith("L5:")) return { label: "内置兜底", tone: "builtin" };
  if (source.startsWith("circuits")) return { label: "回路几何", tone: "dimension" };
  return { label: source, tone: "manual" };
}

/** Ant Design Tag 配色（tone → color） */
export const SOURCE_TONE_COLOR: Record<TestLineSourceTone, string> = {
  run: "green",
  "tower-model": "geekblue",
  template: "cyan",
  dimension: "gold",
  builtin: "orange",
  manual: "default",
  asset: "purple",
};

export const TEST_LINE_STATUS_META: Record<AtpTestLineStatus, { label: string; color: string }> = {
  enabled: { label: "启用", color: "green" },
  disabled: { label: "停用", color: "default" },
  frozen: { label: "已冻结", color: "blue" },
};

export const TEST_LINE_SOURCE_KIND_LABEL: Record<AtpTestLineSourceKind, string> = {
  derived: "派生",
  manual: "手填",
  from_tower: "真实杆塔派生",
  from_asset_run: "历史运行派生",
};

/** 避雷线配置：with = 双避雷线，without = 单避雷线（决定杆塔几何） */
export const SHIELD_WIRE_OPTIONS = [
  { value: "with", label: "双避雷线" },
  { value: "without", label: "单避雷线" },
];

/** 结构类型（四回同塔用得上；其余为空） */
export const STRUCTURE_KIND_OPTIONS = [
  { value: "single", label: "单回" },
  { value: "double", label: "双回" },
  { value: "four", label: "四回同塔" },
];
