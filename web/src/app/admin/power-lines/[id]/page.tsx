"use client";
import Link from "next/link";
import dayjs from "dayjs";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Alert,
  Button,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type MenuProps,
} from "antd";
import { ArrowLeftOutlined, MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { DefaultOptionType } from "antd/es/select";
import type { ColumnsType } from "antd/es/table";
import type { CSSProperties, ReactNode } from "react";
import { Component, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useDimensionOptions } from "@/hooks/use-dimension-options";
import { PowerLineCesiumMap } from "@/components/power-line-cesium-map";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import { readLinePreparation } from "@/lib/line-preparation";
import type {
  ElevationDatasetListResponse,
  ElevationDatasetSummary,
  ElevationFileRecordListResponse,
  ElevationFileRecordSummary,
  ElevationApplyJobCreateResponse,
  LineListResponse,
  LineSummary,
  LineTowerImportResponse,
  LineTowerListResponse,
  LineTowerSummary,
  TowerCircuitSummary,
  TowerModelSummary,
  TowerProfileDetail,
  LightningAmplitudeListResponse,
  LightningCurrentPreparationResponse,
  LightningDensityPreparationResponse,
} from "@/types/auth";
// ErrorBoundary to prevent the "线路参数准备" modal from crashing the whole page
type ErrorBoundaryProps = { children: ReactNode; fallback?: ReactNode };
type ErrorBoundaryState = { hasError: boolean; error: Error | null };
class ParamPrepErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return this.props.fallback ?? (
        <Alert message="线路参数准备加载异常" description={this.state.error?.message} type="error" showIcon />
      );
    }
    return this.props.children;
  }
}
type LineFormValues = {
  name: string;
  voltage_level: string | null;
};
type TowerFormValues = {
  seq_no: number;
  tower_no: string;
  tower_model: string;
  tower_type: string;
  longitude: number | null;
  latitude: number | null;
  altitude_m: number | null;
  terrain: string;
  ground_resistance_ohm: number | null;
  lightning_density: number | null;
  span_small_m: number | null;
  span_large_m: number | null;
  slope_1: number | null;
  slope_2: number | null;
  risk_level: string;
};
type TowerProfileFormValues = {
  structure_kind: string;
  stroke_mode: string;
  phase_sequence_1: string;
  phase_sequence_2: string;
  phase_sequence_3: string;
  phase_sequence_4: string;
  arrester_a: string;
  arrester_b: string;
  arrester_c: string;
  protection_angle_left_deg: number | null;
  protection_angle_right_deg: number | null;
  shield_wire_height_m: number | null;
  insulator_length_m: number | null;
  call_height_m: number | null;
  angle_deg: number | null;
  current_a: number | null;
  current_b: number | null;
  current_type: string;
  current_head_time_us: number | null;
  current_tail_time_us: number | null;
  cause_analysis: string;
  mitigation_recommendation: string;
  geometry_layers_json: string;
  extra_profile_json: string;
};
const TOWER_TYPE_OPTIONS = [
  { value: "", label: "全部塔型" },
  { value: "直线", label: "直线" },
  { value: "耐张", label: "耐张" },
] as const;
const ARRESTER_INSTALL_OPTIONS: DefaultOptionType[] = [
  { value: "是", label: "是" },
  { value: "否", label: "否" },
];
const LINE_VOLTAGE_OPTIONS = [
  { value: "dc_500", label: "直流500kV", voltage_kv: 500 },
  { value: "dc_800", label: "直流800kV", voltage_kv: 800 },
  { value: "dc_1000", label: "直流1000kV", voltage_kv: 1000 },
  { value: "ac_35", label: "交流35kV", voltage_kv: 35 },
  { value: "ac_66", label: "交流66kV", voltage_kv: 66 },
  { value: "ac_110", label: "交流110kV", voltage_kv: 110 },
  { value: "ac_220", label: "交流220kV", voltage_kv: 220 },
  { value: "ac_330", label: "交流330kV", voltage_kv: 330 },
  { value: "ac_500", label: "交流500kV", voltage_kv: 500 },
  { value: "ac_750", label: "交流750kV", voltage_kv: 750 },
  { value: "ac_800", label: "交流800kV", voltage_kv: 800 },
  { value: "ac_1000", label: "交流1000kV", voltage_kv: 1000 },
  { value: "ac_110_x4", label: "交流110kV|交流110kV|交流110kV|交流110kV", voltage_kv: 110 },
  { value: "ac_220_x4", label: "交流220kV|交流220kV|交流220kV|交流220kV", voltage_kv: 220 },
] as const;
const LINE_VOLTAGE_VALUE_TO_KV: Record<(typeof LINE_VOLTAGE_OPTIONS)[number]["value"], number> = {
  dc_500: 500,
  dc_800: 800,
  dc_1000: 1000,
  ac_35: 35,
  ac_66: 66,
  ac_110: 110,
  ac_220: 220,
  ac_330: 330,
  ac_500: 500,
  ac_750: 750,
  ac_800: 800,
  ac_1000: 1000,
  ac_110_x4: 110,
  ac_220_x4: 220,
};
const LINE_VOLTAGE_KV_TO_DEFAULT_OPTION: Partial<Record<number, (typeof LINE_VOLTAGE_OPTIONS)[number]["value"]>> = {
  35: "ac_35",
  66: "ac_66",
  110: "ac_110",
  220: "ac_220",
  330: "ac_330",
  500: "dc_500",
  750: "ac_750",
  800: "dc_800",
  1000: "dc_1000",
};
const TOWER_TABLE_DEFAULT_PAGE_SIZE = 20;
const TOWER_MAP_QUERY_LIMIT = 500;
const POWER_LINES_MAP_DETAIL_HEIGHT = 480;
const TERRAIN_EXAGGERATION_OPTIONS = [
  { label: "1.0x", value: 1 },
  { label: "1.5x", value: 1.5 },
  { label: "2.0x", value: 2 },
] as const;
const EMPTY_LINE_FORM: LineFormValues = {
  name: "",
  voltage_level: null,
};
const EMPTY_TOWER_FORM: TowerFormValues = {
  seq_no: 1,
  tower_no: "",
  tower_model: "",
  tower_type: "",
  longitude: null,
  latitude: null,
  altitude_m: null,
  terrain: "",
  ground_resistance_ohm: null,
  lightning_density: null,
  span_small_m: null,
  span_large_m: null,
  slope_1: null,
  slope_2: null,
  risk_level: "",
};
const EMPTY_TOWER_PROFILE_FORM: TowerProfileFormValues = {
  structure_kind: "",
  stroke_mode: "",
  phase_sequence_1: "",
  phase_sequence_2: "",
  phase_sequence_3: "",
  phase_sequence_4: "",
  arrester_a: "",
  arrester_b: "",
  arrester_c: "",
  protection_angle_left_deg: null,
  protection_angle_right_deg: null,
  shield_wire_height_m: null,
  insulator_length_m: null,
  call_height_m: null,
  angle_deg: null,
  current_a: null,
  current_b: null,
  current_type: "",
  current_head_time_us: null,
  current_tail_time_us: null,
  cause_analysis: "",
  mitigation_recommendation: "",
  geometry_layers_json: "{}",
  extra_profile_json: "{}",
};
function resolveVoltageOptionFromKv(voltageKv: number | null): LineFormValues["voltage_level"] {
  if (voltageKv === null) {
    return null;
  }
  return LINE_VOLTAGE_KV_TO_DEFAULT_OPTION[voltageKv] ?? null;
}
function formatJsonText(value: unknown): string {
  if (!value || Array.isArray(value) || typeof value !== "object") {
    return "{}";
  }
  return JSON.stringify(value, null, 2);
}
function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}
function parseJsonObjectText(value: string, label: string): Record<string, unknown> {
  const normalized = value.trim();
  if (!normalized) {
    return {};
  }
  const parsed: unknown = JSON.parse(normalized);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} 需要是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}
const CIRCUIT_KEY_BY_NO: Record<number, TowerCircuitKey> = { 1: "I", 2: "II", 3: "III", 4: "IV" };
const CIRCUIT_NO_BY_KEY: Record<TowerCircuitKey, number> = { I: 1, II: 2, III: 3, IV: 4 };
function circuitsToGeometryLayers(circuits: TowerCircuitSummary[]): Record<string, unknown> {
  const geometry: Record<string, unknown> = {};
  circuits.forEach((circuit) => {
    const circuitKey = CIRCUIT_KEY_BY_NO[circuit.circuit_no];
    if (!circuitKey) {
      return;
    }
    geometry[circuitKey] = {
      phase_spacing_m: {
        upper: circuit.spacing_upper_m,
        middle: circuit.spacing_middle_m,
        lower: circuit.spacing_lower_m,
      },
      phase_height_m: {
        upper: circuit.height_upper_m,
        middle: circuit.height_middle_m,
        lower: circuit.height_lower_m,
      },
    };
  });
  return geometry;
}
function geometryLayersToCircuits(geometry: Record<string, unknown>): TowerCircuitSummary[] {
  const circuits: TowerCircuitSummary[] = [];
  Object.entries(CIRCUIT_NO_BY_KEY).forEach(([circuitKey, circuitNo]) => {
    const rawCircuit = asObjectRecord(geometry[circuitKey]);
    if (!rawCircuit) {
      return;
    }
    const spacing = asObjectRecord(rawCircuit.phase_spacing_m) ?? {};
    const height = asObjectRecord(rawCircuit.phase_height_m) ?? {};
    const hasValue = [
      spacing.upper,
      spacing.middle,
      spacing.lower,
      height.upper,
      height.middle,
      height.lower,
    ].some((item) => toGeometryNumber(item) !== null);
    if (!hasValue) {
      return;
    }
    circuits.push({
      id: null,
      tower_id: null,
      circuit_no: circuitNo,
      phase_sequence: null,
      spacing_upper_m: toGeometryNumber(spacing.upper),
      spacing_middle_m: toGeometryNumber(spacing.middle),
      spacing_lower_m: toGeometryNumber(spacing.lower),
      height_upper_m: toGeometryNumber(height.upper),
      height_middle_m: toGeometryNumber(height.middle),
      height_lower_m: toGeometryNumber(height.lower),
    });
  });
  return circuits;
}
type TowerTopologyKind = "single" | "double" | "quad" | "dc";
type TowerCircuitKey = "I" | "II" | "III" | "IV";
type TowerPhaseKey = "upper" | "middle" | "lower";
type TowerGeometryMetricKey = "phase_spacing_m" | "phase_height_m";
type TowerArresterField = "arrester_a" | "arrester_b" | "arrester_c";
type TowerProfileGeometryEditorMode = "structured" | "advanced";
type TowerTopologySpec = {
  kind: TowerTopologyKind;
  label: string;
  description: string;
  circuitKeys: TowerCircuitKey[];
  phaseKeys: TowerPhaseKey[];
  phaseLabels: Record<TowerPhaseKey, string>;
  phaseSequenceFields: Array<1 | 2 | 3 | 4>;
  arresterFields: Array<{ field: TowerArresterField; label: string }>;
};
const ALL_TOWER_CIRCUIT_KEYS: TowerCircuitKey[] = ["I", "II", "III", "IV"];
const TOWER_TOPOLOGY_KIND_OPTIONS: Array<{ label: string; value: TowerTopologyKind }> = [
  { label: "单回", value: "single" },
  { label: "双回", value: "double" },
  { label: "四回", value: "quad" },
  { label: "直流", value: "dc" },
];
const TOWER_PROFILE_EDITOR_MODE_OPTIONS: Array<{ label: string; value: TowerProfileGeometryEditorMode }> = [
  { label: "专用编辑器", value: "structured" },
  { label: "高级 JSON", value: "advanced" },
];
const TOWER_TOPOLOGY_SPECS: Record<TowerTopologyKind, TowerTopologySpec> = {
  single: {
    kind: "single",
    label: "单回路交流塔",
    description: "按 I 回上中下三层导线录入，适合源端单回杆塔窗体。",
    circuitKeys: ["I"],
    phaseKeys: ["upper", "middle", "lower"],
    phaseLabels: { upper: "上相", middle: "中相", lower: "下相" },
    phaseSequenceFields: [1],
    arresterFields: [
      { field: "arrester_a", label: "A相避雷器" },
      { field: "arrester_b", label: "B相避雷器" },
      { field: "arrester_c", label: "C相避雷器" },
    ],
  },
  double: {
    kind: "double",
    label: "双回路交流塔",
    description: "按 I / II 回分别录入上中下三层导线几何。",
    circuitKeys: ["I", "II"],
    phaseKeys: ["upper", "middle", "lower"],
    phaseLabels: { upper: "上相", middle: "中相", lower: "下相" },
    phaseSequenceFields: [1, 2],
    arresterFields: [
      { field: "arrester_a", label: "A相避雷器" },
      { field: "arrester_b", label: "B相避雷器" },
      { field: "arrester_c", label: "C相避雷器" },
    ],
  },
  quad: {
    kind: "quad",
    label: "四回路交流塔",
    description: "按 I / II / III / IV 回分别录入上中下三层导线几何。",
    circuitKeys: ["I", "II", "III", "IV"],
    phaseKeys: ["upper", "middle", "lower"],
    phaseLabels: { upper: "上相", middle: "中相", lower: "下相" },
    phaseSequenceFields: [1, 2, 3, 4],
    arresterFields: [
      { field: "arrester_a", label: "A相避雷器" },
      { field: "arrester_b", label: "B相避雷器" },
      { field: "arrester_c", label: "C相避雷器" },
    ],
  },
  dc: {
    kind: "dc",
    label: "直流塔",
    description: "按左极 / 右极两侧导线录入，内部映射到 I 回几何结构。",
    circuitKeys: ["I"],
    phaseKeys: ["upper", "lower"],
    phaseLabels: { upper: "左极", middle: "中极", lower: "右极" },
    phaseSequenceFields: [],
    arresterFields: [
      { field: "arrester_a", label: "左极避雷器" },
      { field: "arrester_c", label: "右极避雷器" },
    ],
  },
};
function asObjectRecord(value: unknown): Record<string, unknown> | null {
  if (!value || Array.isArray(value) || typeof value !== "object") {
    return null;
  }
  return value as Record<string, unknown>;
}
function parseTowerTopologyOverride(value: unknown): TowerTopologyKind | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (["single", "single_circuit", "1", "1h", "1hui", "1回", "单回"].includes(normalized)) {
    return "single";
  }
  if (["double", "double_circuit", "2", "2h", "2hui", "2回", "双回"].includes(normalized)) {
    return "double";
  }
  if (["quad", "four", "four_circuit", "4", "4h", "4hui", "4回", "四回"].includes(normalized)) {
    return "quad";
  }
  if (["dc", "hvdc", "zhiliu", "vzhiliu", "直流"].includes(normalized)) {
    return "dc";
  }
  return null;
}
function inferTowerTopology(values: {
  towerModel?: string | null;
  towerType?: string | null;
  structureKind?: string | null;
  geometryLayers?: Record<string, unknown>;
}): TowerTopologyKind {
  const override = parseTowerTopologyOverride(values.geometryLayers?.topology_kind);
  if (override) {
    return override;
  }
  const marker = [
    values.towerModel ?? "",
    values.towerType ?? "",
    values.structureKind ?? "",
  ].join("|").toLowerCase();
  if (
    marker.includes("直流")
    || marker.includes("zhiliu")
    || marker.includes("vzhiliu")
    || marker.startsWith("dc")
    || marker.includes("|dc")
    || marker.includes("dc_")
  ) {
    return "dc";
  }
  if (marker.includes("sihuita") || marker.includes("四回") || marker.includes("4回")) {
    return "quad";
  }
  if (marker.includes("guxing") || marker.includes("双回") || marker.includes("2回")) {
    return "double";
  }
  return "single";
}
function toGeometryNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}
function normalizeGeometryForTopology(
  geometryLayers: Record<string, unknown>,
  topology: TowerTopologyKind,
): Record<string, unknown> {
  const spec = TOWER_TOPOLOGY_SPECS[topology];
  const next: Record<string, unknown> = {};
  Object.entries(geometryLayers).forEach(([key, value]) => {
    if (!ALL_TOWER_CIRCUIT_KEYS.includes(key as TowerCircuitKey)) {
      next[key] = value;
    }
  });
  next.topology_kind = topology;
  spec.circuitKeys.forEach((circuitKey) => {
    const rawCircuit = asObjectRecord(geometryLayers[circuitKey]);
    const nextCircuit: Record<string, unknown> = { ...(rawCircuit ?? {}) };
    const spacing = { ...(asObjectRecord(rawCircuit?.phase_spacing_m) ?? {}) };
    const height = { ...(asObjectRecord(rawCircuit?.phase_height_m) ?? {}) };
    if (topology === "dc") {
      delete spacing.middle;
      delete height.middle;
    }
    nextCircuit.phase_spacing_m = spacing;
    nextCircuit.phase_height_m = height;
    next[circuitKey] = nextCircuit;
  });
  return next;
}
function getCircuitGeometryMetric(
  geometryLayers: Record<string, unknown>,
  circuitKey: TowerCircuitKey,
  metricKey: TowerGeometryMetricKey,
  phaseKey: TowerPhaseKey,
): number | null {
  const circuit = asObjectRecord(geometryLayers[circuitKey]);
  const metric = asObjectRecord(circuit?.[metricKey]);
  return toGeometryNumber(metric?.[phaseKey]);
}
function setCircuitGeometryMetric(
  geometryLayers: Record<string, unknown>,
  topology: TowerTopologyKind,
  circuitKey: TowerCircuitKey,
  metricKey: TowerGeometryMetricKey,
  phaseKey: TowerPhaseKey,
  value: number | null,
): Record<string, unknown> {
  const next = normalizeGeometryForTopology(geometryLayers, topology);
  const circuit = { ...(asObjectRecord(next[circuitKey]) ?? {}) };
  const metric = { ...(asObjectRecord(circuit[metricKey]) ?? {}) };
  if (value === null) {
    delete metric[phaseKey];
  } else {
    metric[phaseKey] = value;
  }
  circuit[metricKey] = metric;
  next[circuitKey] = circuit;
  return next;
}
function getLightningWireMetric(
  geometryLayers: Record<string, unknown>,
  field: "left_mid_distance_m" | "right_mid_distance_m" | "height_m",
): number | null {
  const lightningWire = asObjectRecord(geometryLayers.lightning_wire);
  return toGeometryNumber(lightningWire?.[field]);
}
function setLightningWireMetric(
  geometryLayers: Record<string, unknown>,
  topology: TowerTopologyKind,
  field: "left_mid_distance_m" | "right_mid_distance_m" | "height_m",
  value: number | null,
): Record<string, unknown> {
  const next = normalizeGeometryForTopology(geometryLayers, topology);
  const lightningWire = { ...(asObjectRecord(next.lightning_wire) ?? {}) };
  if (value === null) {
    delete lightningWire[field];
  } else {
    lightningWire[field] = value;
  }
  next.lightning_wire = lightningWire;
  return next;
}
function validateStructuredGeometry(
  geometryLayers: Record<string, unknown>,
  topology: TowerTopologyKind,
): string | null {
  const spec = TOWER_TOPOLOGY_SPECS[topology];
  for (const circuitKey of spec.circuitKeys) {
    for (const phaseKey of spec.phaseKeys) {
      const phaseLabel = spec.phaseLabels[phaseKey];
      const spacing = getCircuitGeometryMetric(geometryLayers, circuitKey, "phase_spacing_m", phaseKey);
      if (spacing === null || Math.abs(spacing) <= Number.EPSILON) {
        return `${circuitKey}回${phaseLabel}导线中距不能为空`;
      }
      const height = getCircuitGeometryMetric(geometryLayers, circuitKey, "phase_height_m", phaseKey);
      if (height === null || height <= 0) {
        return `${circuitKey}回${phaseLabel}导线高度必须大于 0`;
      }
    }
  }
  const leftDistance = getLightningWireMetric(geometryLayers, "left_mid_distance_m");
  if (leftDistance === null || Math.abs(leftDistance) <= Number.EPSILON) {
    return "左避雷中距不能为空";
  }
  const rightDistance = getLightningWireMetric(geometryLayers, "right_mid_distance_m");
  if (rightDistance === null || Math.abs(rightDistance) <= Number.EPSILON) {
    return "右避雷中距不能为空";
  }
  return null;
}
function terrainStatusLabel(status: ElevationDatasetSummary["terrain_status"]): string {
  if (status === "ready") return "已就绪";
  if (status === "processing") return "生成中";
  if (status === "pending") return "待生成";
  if (status === "failed") return "生成失败";
  if (status === "not_supported") return "格式不支持";
  return status || "-";
}
export default function AdminPowerLineDetailPage() {
  const params = useParams();
  const router = useRouter();
  const lineId = params.id as string;
  const { user, initializing, fetchWithAuth, getAccessToken, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const { optionMap: topologyDimensionOptions } = useDimensionOptions({ tower_topology_kind: "tower_topology_kind" });
  const { message: messageApi } = App.useApp();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [lineForm] = Form.useForm<LineFormValues>();
  const [towerForm] = Form.useForm<TowerFormValues>();
  const [towerProfileForm] = Form.useForm<TowerProfileFormValues>();
  const watchedTowerProfileStructureKind = Form.useWatch("structure_kind", towerProfileForm) as string | undefined;
  const watchedTowerProfileGeometryText = (Form.useWatch("geometry_layers_json", towerProfileForm) as string | undefined)
    ?? EMPTY_TOWER_PROFILE_FORM.geometry_layers_json;
  const [towerKeyword, setTowerKeyword] = useState("");
  const [towerTypeFilter, setTowerTypeFilter] = useState("");
  const [towerRiskFilter, setTowerRiskFilter] = useState("");
  const [towerPagination, setTowerPagination] = useState({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE });
  const [lineModalOpen, setLineModalOpen] = useState(false);
  const [towerModalOpen, setTowerModalOpen] = useState(false);
  const [towerProfileModalOpen, setTowerProfileModalOpen] = useState(false);
  const [lineParamModalOpen, setLineParamModalOpen] = useState(false);
  const [towerProfileGeometryEditorMode, setTowerProfileGeometryEditorMode] = useState<TowerProfileGeometryEditorMode>("structured");
  const [editingLine, setEditingLine] = useState<LineSummary | null>(null);
  const [editingTower, setEditingTower] = useState<LineTowerSummary | null>(null);
  const [editingTowerProfileTower, setEditingTowerProfileTower] = useState<LineTowerSummary | null>(null);
  const [towerViewMode, setTowerViewMode] = useState<"table" | "map">("table");
  const [selectedTerrainDatasetId, setSelectedTerrainDatasetId] = useState<string | null | undefined>(undefined);
  const [terrainExaggeration, setTerrainExaggeration] = useState<number>(1.5);
  const [prepareDensityRadiusKm, setPrepareDensityRadiusKm] = useState(3);
  const [prepareDensityYears, setPrepareDensityYears] = useState<number | null>(null);
  const [elevationBackfillFileId, setElevationBackfillFileId] = useState<string | null>(null);
  const [elevationBackfillMode, setElevationBackfillMode] = useState<"fill_null_only" | "overwrite_all">("fill_null_only");
  const [selectedCurrentEventId, setSelectedCurrentEventId] = useState<string | null>(null);
  const [currentEventPickerOpen, setCurrentEventPickerOpen] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [routeLengthMap, setRouteLengthMap] = useState<Record<string, number>>({});
  // line id whose route length is still being computed by the map (shows placeholder instead of "-")
  const [routeLengthPendingLineId, setRouteLengthPendingLineId] = useState<string | null>(null);
  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  const canLineManage = hasPermission("line.manage");
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage");
  const canTowerManage = hasPermission("tower.manage");
  const canElevationRead = hasPermission("elevation.read") || hasPermission("elevation.manage");
  const canRead = canLineRead || canTowerRead;
  const activeTowerLineId = lineId;
  const towerQueryCurrent = towerPagination.current;
  const towerQueryPageSize = towerPagination.pageSize;
  const towerListPath = useMemo(() => {
    if (!activeTowerLineId) {
      return "";
    }
    const params = new URLSearchParams();
    if (towerKeyword.trim()) {
      params.set("keyword", towerKeyword.trim());
    }
    if (towerTypeFilter) {
      params.set("tower_type", towerTypeFilter);
    }
    if (towerRiskFilter.trim()) {
      params.set("risk_level", towerRiskFilter.trim());
    }
    if (towerViewMode === "table") {
      params.set("limit", String(towerQueryPageSize));
      params.set("offset", String((towerQueryCurrent - 1) * towerQueryPageSize));
    } else {
      params.set("limit", String(TOWER_MAP_QUERY_LIMIT));
      params.set("offset", "0");
    }
    const query = params.toString();
    return `/api/v1/lines/${activeTowerLineId}/towers?${query}`;
  }, [
    activeTowerLineId,
    towerKeyword,
    towerTypeFilter,
    towerRiskFilter,
    towerViewMode,
    towerQueryCurrent,
    towerQueryPageSize,
  ]);
  const lineQuery = useQuery({
    queryKey: ["/api/v1/lines", lineId],
    enabled: !!user && !!lineId && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineSummary;
    },
  });

  const towersQuery = useQuery({
    queryKey: [towerListPath],
    enabled: !!user && !!activeTowerLineId && canRead,
    queryFn: async () => {
      if (!towerListPath) {
        return { items: [], total: 0 } satisfies LineTowerListResponse;
      }
      const response = await fetchWithAuth(towerListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });
  const towerModelOptionsQuery = useQuery({
    queryKey: ["/api/v1/tower-models/selector"],
    enabled: !!user && canTowerRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/tower-models/selector");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerModelSummary[];
    },
  });
  const elevationDatasetsQuery = useQuery({
    queryKey: ["/api/v1/elevation/datasets"],
    enabled: !!user && canElevationRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/elevation/datasets");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationDatasetListResponse;
    },
  });
  const elevationFileRecordsQuery = useQuery({
    queryKey: ["/api/v1/elevation/records"],
    enabled: !!user && canElevationRead && lineParamModalOpen && !!lineId,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/elevation/records?limit=1000");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationFileRecordListResponse;
    },
  });
  const lightningEventsQuery = useQuery({
    queryKey: ["/api/v1/lightning-currents", { limit: 200, offset: 0 }],
    enabled: !!user && (canTowerRead || canLineRead) && currentEventPickerOpen,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/lightning-currents?limit=200&offset=0");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeListResponse;
    },
  });
  const towerProfileQuery = useQuery({
    queryKey: ["tower-profile", editingTowerProfileTower?.id],
    enabled: !!user && !!editingTowerProfileTower && towerProfileModalOpen && canTowerRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/tower-profiles/${editingTowerProfileTower?.id}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerProfileDetail;
    },
  });
  const lineError = lineQuery.error instanceof Error ? lineQuery.error.message : "";
  const towerError = towersQuery.error instanceof Error ? towersQuery.error.message : "";
  const elevationDatasetError = elevationDatasetsQuery.error instanceof Error ? elevationDatasetsQuery.error.message : "";
  useToastFeedback({
    errorMessage: error || lineError || towerError || elevationDatasetError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });
  const towerProfileGeometryParseResult = useMemo(() => {
    try {
      return {
        geometry: parseJsonObjectText(String(watchedTowerProfileGeometryText ?? "{}"), "回路几何 JSON"),
        error: null as string | null,
      };
    } catch (candidate) {
      return {
        geometry: {} as Record<string, unknown>,
        error: candidate instanceof Error ? candidate.message : "回路几何 JSON 解析失败",
      };
    }
  }, [watchedTowerProfileGeometryText]);
  const towerProfileTopology = useMemo(
    () => inferTowerTopology({
      towerModel: editingTowerProfileTower?.tower_model ?? towerProfileQuery.data?.tower_model ?? "",
      towerType: editingTowerProfileTower?.tower_type ?? towerProfileQuery.data?.tower_type ?? "",
      structureKind: watchedTowerProfileStructureKind ?? towerProfileQuery.data?.structure_kind ?? "",
      geometryLayers: towerProfileGeometryParseResult.geometry,
    }),
    [
      editingTowerProfileTower?.tower_model,
      editingTowerProfileTower?.tower_type,
      towerProfileGeometryParseResult.geometry,
      towerProfileQuery.data?.structure_kind,
      towerProfileQuery.data?.tower_model,
      towerProfileQuery.data?.tower_type,
      watchedTowerProfileStructureKind,
    ],
  );
  const towerProfileTopologySpec = TOWER_TOPOLOGY_SPECS[towerProfileTopology];
  // 专用编辑器拓扑类型：优先取维度管理数据（仅保留已知枚举值），加载失败/未 seed 时回退硬编码选项
  const towerTopologyKindOptions = useMemo<Array<{ label: string; value: TowerTopologyKind }>>(() => {
    const dimensionItems = topologyDimensionOptions.tower_topology_kind ?? [];
    if (dimensionItems.length === 0) {
      return TOWER_TOPOLOGY_KIND_OPTIONS;
    }
    return dimensionItems.flatMap((item) =>
      (TOWER_TOPOLOGY_KIND_OPTIONS.some((option) => option.value === item.value)
        ? [{ label: item.label, value: item.value as TowerTopologyKind }]
        : []),
    );
  }, [topologyDimensionOptions]);
  const updateTowerProfileGeometryText = useCallback(
    (updater: (current: Record<string, unknown>) => Record<string, unknown>) => {
      let currentGeometry: Record<string, unknown> = {};
      try {
        currentGeometry = parseJsonObjectText(
          String(towerProfileForm.getFieldValue("geometry_layers_json") ?? "{}"),
          "回路几何 JSON",
        );
      } catch {
        currentGeometry = {};
      }
      towerProfileForm.setFieldValue("geometry_layers_json", formatJsonText(updater(currentGeometry)));
    },
    [towerProfileForm],
  );
  const handleTowerProfileTopologyChange = useCallback(
    (nextTopology: TowerTopologyKind) => {
      updateTowerProfileGeometryText((currentGeometry) => normalizeGeometryForTopology(currentGeometry, nextTopology));
    },
    [updateTowerProfileGeometryText],
  );
  const refreshLines = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lines"),
    });
  }, [queryClient]);
  const refreshTowers = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].includes("/towers"),
    });
  }, [queryClient]);
  useEffect(() => {
    const profile = towerProfileQuery.data;
    if (!profile) {
      return;
    }
    towerProfileForm.setFieldsValue({
      structure_kind: profile.structure_kind ?? "",
      stroke_mode: profile.stroke_mode ?? "",
      phase_sequence_1: profile.phase_sequence_1 ?? "",
      phase_sequence_2: profile.phase_sequence_2 ?? "",
      phase_sequence_3: profile.phase_sequence_3 ?? "",
      phase_sequence_4: profile.phase_sequence_4 ?? "",
      arrester_a: profile.arrester_a ?? "",
      arrester_b: profile.arrester_b ?? "",
      arrester_c: profile.arrester_c ?? "",
      protection_angle_left_deg: profile.protection_angle_left_deg ?? null,
      protection_angle_right_deg: profile.protection_angle_right_deg ?? null,
      shield_wire_height_m: profile.shield_wire_height_m ?? null,
      insulator_length_m: profile.insulator_length_m ?? null,
      call_height_m: profile.call_height_m ?? null,
      angle_deg: profile.angle_deg ?? null,
      current_a: profile.current_a ?? null,
      current_b: profile.current_b ?? null,
      current_type: profile.current_type ?? "",
      current_head_time_us: profile.current_head_time_us ?? null,
      current_tail_time_us: profile.current_tail_time_us ?? null,
      cause_analysis: profile.cause_analysis ?? "",
      mitigation_recommendation: profile.mitigation_recommendation ?? "",
      geometry_layers_json: formatJsonText(circuitsToGeometryLayers(profile.circuits ?? [])),
      extra_profile_json: formatJsonText(profile.extra_profile_json),
    });
  }, [towerProfileForm, towerProfileQuery.data]);
  useTopicSubscription("admin.power-lines", useCallback(() => {
    void refreshLines();
    void refreshTowers();
  }, [refreshLines, refreshTowers]));
  useTopicSubscription("admin.elevation", useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/elevation/datasets"] });
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/elevation/records"] });
  }, [queryClient]));
  useTopicSubscription("admin.tower-models", useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/tower-models/selector"] });
  }, [queryClient]));
  const towers = useMemo(() => towersQuery.data?.items ?? [], [towersQuery.data?.items]);
  const towerModels = useMemo(() => towerModelOptionsQuery.data ?? [], [towerModelOptionsQuery.data]);
  const elevationDatasets = useMemo(() => elevationDatasetsQuery.data?.items ?? [], [elevationDatasetsQuery.data?.items]);
  const selectableTerrainDatasets = useMemo(
    () =>
      elevationDatasets.filter(
        (item) => item.status === "active" && item.terrain_status !== "not_supported",
      ),
    [elevationDatasets],
  );
  const preferredTerrainDatasetId = useMemo(
    () =>
      selectableTerrainDatasets.find((item) => item.terrain_status === "ready")?.id
      ?? selectableTerrainDatasets[0]?.id
      ?? null,
    [selectableTerrainDatasets],
  );
  const effectiveTerrainDatasetId = useMemo(() => {
    if (selectedTerrainDatasetId === undefined) {
      return preferredTerrainDatasetId;
    }
    if (selectedTerrainDatasetId === null) {
      return null;
    }
    return selectableTerrainDatasets.some((item) => item.id === selectedTerrainDatasetId)
      ? selectedTerrainDatasetId
      : preferredTerrainDatasetId;
  }, [preferredTerrainDatasetId, selectableTerrainDatasets, selectedTerrainDatasetId]);
  const selectedTerrainDataset = useMemo(
    () => selectableTerrainDatasets.find((item) => item.id === effectiveTerrainDatasetId) ?? null,
    [effectiveTerrainDatasetId, selectableTerrainDatasets],
  );
  const terrainDatasetOptions = useMemo(
    () =>
      selectableTerrainDatasets.map((item) => ({
        value: item.id,
        label: `${item.code} - ${item.name}（${terrainStatusLabel(item.terrain_status)}）`,
      })),
    [selectableTerrainDatasets],
  );
  const towerModelOptions = towerModels.map((item) => ({ value: item.code, label: `${item.code} - ${item.name}` }));
  const selectedLine = lineQuery.data ?? null;
  const selectedLinePreparation = useMemo(() => readLinePreparation(selectedLine), [selectedLine]);
  const handleRouteLengthChange = useCallback((value: number) => {
    const id = selectedLine?.id ?? "";
    setRouteLengthMap((prev) => ({ ...prev, [id]: value }));
    setRouteLengthPendingLineId((prev) => (prev === id ? null : prev));
  }, [selectedLine]);

  // Compute line bbox from towers for elevation backfill matching
  const lineBbox = useMemo(() => {
    if (!towers.length) return null;
    let minLon = Infinity, maxLon = -Infinity;
    let minLat = Infinity, maxLat = -Infinity;
    for (const tower of towers) {
      if (tower.longitude != null && tower.latitude != null) {
        if (tower.longitude < minLon) minLon = tower.longitude;
        if (tower.longitude > maxLon) maxLon = tower.longitude;
        if (tower.latitude < minLat) minLat = tower.latitude;
        if (tower.latitude > maxLat) maxLat = tower.latitude;
      }
    }
    if (!isFinite(minLon)) return null;
    return { minLon, maxLon, minLat, maxLat };
  }, [towers]);
  const elevationFileRecords = useMemo(
    () => elevationFileRecordsQuery.data?.items ?? [],
    [elevationFileRecordsQuery.data?.items],
  );
  // Filter elevation records that have bbox intersecting with line bbox
  const matchedElevationRecords = useMemo(() => {
    if (!lineBbox) return [];
    return elevationFileRecords.filter((file) => {
      if (
        file.bbox_min_lon == null ||
        file.bbox_max_lon == null ||
        file.bbox_min_lat == null ||
        file.bbox_max_lat == null
      ) {
        return false;
      }
      return (
        file.bbox_max_lon >= lineBbox.minLon &&
        file.bbox_min_lon <= lineBbox.maxLon &&
        file.bbox_max_lat >= lineBbox.minLat &&
        file.bbox_min_lat <= lineBbox.maxLat
      );
    });
  }, [elevationFileRecords, lineBbox]);
  const applyTowerModelDefaults = useCallback((modelCode: string | null | undefined) => {
    if (!modelCode) {
      return;
    }
    const matched = towerModels.find((item) => item.code === modelCode);
    if (!matched) {
      return;
    }
    towerForm.setFieldsValue({
      tower_type: matched.tower_type ?? "",
      altitude_m: matched.default_altitude_m ?? null,
      terrain: matched.default_terrain ?? "",
      ground_resistance_ohm: matched.default_ground_resistance_ohm ?? null,
      lightning_density: matched.default_lightning_density ?? null,
      span_small_m: matched.default_span_small_m ?? null,
      span_large_m: matched.default_span_large_m ?? null,
      slope_1: matched.default_slope_1 ?? null,
      slope_2: matched.default_slope_2 ?? null,
      risk_level: matched.default_risk_level ?? "",
    });
  }, [towerForm, towerModels]);
  const saveLineMutation = useMutation({
    mutationFn: async (values: LineFormValues) => {
      if (!canLineManage) {
        throw new Error("缺少 line.manage 权限");
      }
      const payload = {
        name: values.name.trim(),
        voltage_kv: values.voltage_level ? LINE_VOLTAGE_VALUE_TO_KV[values.voltage_level] : null,
      };
      if (editingLine) {
        const response = await fetchWithAuth(`/api/v1/lines/${editingLine.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: payload.name,
            voltage_kv: payload.voltage_kv,
          }),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        return "updated" as const;
      }
      const response = await fetchWithAuth("/api/v1/lines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "created" as const;
    },
    onSuccess: async (mode) => {
      setError("");
      messageApi.success(mode === "created" ? "线路已创建" : "线路已更新");
      setLineModalOpen(false);
      setEditingLine(null);
      lineForm.resetFields();
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存线路失败");
    },
  });
  const deleteLineMutation = useMutation({
    mutationFn: async (lineId: string) => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return lineId;
    },
    onMutate: (lineId) => {
      if (lineId === lineId) {
      }
    },
    onSuccess: async (lineId) => {
      if (lineId === lineId) {
      }
      setError("");
      messageApi.success("线路已删除");
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除线路失败");
    },
    onSettled: () => {
    },
  });
  const saveTowerMutation = useMutation({
    mutationFn: async (values: TowerFormValues) => {
      if (!lineId) {
        throw new Error("请先选择线路");
      }
      if (!canTowerManage) {
        throw new Error("缺少 tower.manage 权限");
      }
      const payload = {
        seq_no: Number(values.seq_no),
        tower_no: values.tower_no.trim(),
        tower_model: values.tower_model.trim() || null,
        tower_type: values.tower_type.trim() || null,
        longitude: values.longitude ?? null,
        latitude: values.latitude ?? null,
        altitude_m: values.altitude_m ?? null,
        terrain: values.terrain.trim() || null,
        ground_resistance_ohm: values.ground_resistance_ohm ?? null,
        lightning_density: values.lightning_density ?? null,
        span_small_m: values.span_small_m ?? null,
        span_large_m: values.span_large_m ?? null,
        slope_1: values.slope_1 ?? null,
        slope_2: values.slope_2 ?? null,
        risk_level: values.risk_level.trim() || null,
      };
      if (editingTower) {
        const response = await fetchWithAuth(`/api/v1/lines/towers/${editingTower.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        return "updated" as const;
      }
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "created" as const;
    },
    onSuccess: async (mode) => {
      setError("");
      messageApi.success(mode === "created" ? "杆塔已创建" : "杆塔已更新");
      setTowerModalOpen(false);
      setEditingTower(null);
      towerForm.resetFields();
      await refreshTowers();
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存杆塔失败");
    },
  });
  const deleteTowerMutation = useMutation({
    mutationFn: async (towerId: string) => {
      const response = await fetchWithAuth(`/api/v1/lines/towers/${towerId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return towerId;
    },
    onSuccess: async () => {
      setError("");
      messageApi.success("杆塔已删除");
      await refreshTowers();
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除杆塔失败");
    },
  });
  const saveTowerProfileMutation = useMutation({
    mutationFn: async (values: TowerProfileFormValues) => {
      if (!editingTowerProfileTower) {
        throw new Error("未选择杆塔");
      }
      const geometryLayers = parseJsonObjectText(values.geometry_layers_json, "回路几何 JSON");
      const extraProfile = parseJsonObjectText(values.extra_profile_json, "额外字段 JSON");
      const circuits = geometryLayersToCircuits(geometryLayers);
      const response = await fetchWithAuth(`/api/v1/tower-profiles/${editingTowerProfileTower.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          structure_kind: (values.structure_kind ?? "").trim() || null,
          stroke_mode: (values.stroke_mode ?? "").trim() || null,
          phase_sequence_1: (values.phase_sequence_1 ?? "").trim() || null,
          phase_sequence_2: (values.phase_sequence_2 ?? "").trim() || null,
          phase_sequence_3: (values.phase_sequence_3 ?? "").trim() || null,
          phase_sequence_4: (values.phase_sequence_4 ?? "").trim() || null,
          arrester_a: (values.arrester_a ?? "").trim() || null,
          arrester_b: (values.arrester_b ?? "").trim() || null,
          arrester_c: (values.arrester_c ?? "").trim() || null,
          protection_angle_left_deg: values.protection_angle_left_deg ?? null,
          protection_angle_right_deg: values.protection_angle_right_deg ?? null,
          shield_wire_height_m: values.shield_wire_height_m ?? null,
          insulator_length_m: values.insulator_length_m ?? null,
          call_height_m: values.call_height_m ?? null,
          angle_deg: values.angle_deg ?? null,
          current_a: values.current_a ?? null,
          current_b: values.current_b ?? null,
          current_type: (values.current_type ?? "").trim() || null,
          current_head_time_us: values.current_head_time_us ?? null,
          current_tail_time_us: values.current_tail_time_us ?? null,
          cause_analysis: (values.cause_analysis ?? "").trim() || null,
          mitigation_recommendation: (values.mitigation_recommendation ?? "").trim() || null,
          circuits,
          extra_profile_json: extraProfile,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerProfileDetail;
    },
    onSuccess: async () => {
      setError("");
      messageApi.success("专业参数已保存");
      setTowerProfileModalOpen(false);
      setEditingTowerProfileTower(null);
      towerProfileForm.resetFields();
      await queryClient.invalidateQueries({ queryKey: ["tower-profile"] });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存专业参数失败");
    },
  });
  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!lineId) {
        throw new Error("请先选择线路");
      }
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerImportResponse;
    },
    onSuccess: async (result) => {
      setError("");
      messageApi.success(
        `导入完成：新增 ${result.imported_count} 条，更新 ${result.updated_count} 条，跳过 ${result.skipped_count} 条`,
      );
      await refreshLines();
      await refreshTowers();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "导入失败");
    },
  });
  const exportMutation = useMutation({
    mutationFn: async () => {
      if (!lineId) {
        throw new Error("请先选择线路");
      }
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/export`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const contentDisposition = response.headers.get("Content-Disposition") || "";
      const matched = contentDisposition.match(/filename=\"([^\"]+)\"/i);
      const filename = matched?.[1] ?? "towers_export.csv";
      return { blob, filename };
    },
    onSuccess: ({ blob, filename }) => {
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
      setError("");
      messageApi.success("导出成功");
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "导出失败");
    },
  });
  const prepareCurrentMutation = useMutation({
    mutationFn: async () => {
      if (!lineId) {
        throw new Error("请先选择线路");
      }
      const body: Record<string, unknown> = {
        line_id: lineId,
      };
      if (selectedCurrentEventId) {
        body.event_id = selectedCurrentEventId;
      }
      const response = await fetchWithAuth("/api/v1/lightning-currents/prepare-current", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentPreparationResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(`已为 ${payload.line.name || payload.line.code} 回填雷电流幅值`);
      await refreshLines();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "雷电流幅值回填失败");
    },
  });
  const prepareDensityMutation = useMutation({
    mutationFn: async () => {
      if (!lineId) {
        throw new Error("请先选择线路");
      }
      const response = await fetchWithAuth("/api/v1/lightning-currents/prepare-density", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          line_id: lineId,
          radius_km: prepareDensityRadiusKm,
          years: prepareDensityYears,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDensityPreparationResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(`已为 ${payload.line.name || payload.line.code} 回填地闪密度`);
      await refreshLines();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "地闪密度回填失败");
    },
  });
  const elevationBackfillMutation = useMutation({
    mutationFn: async () => {
      if (!lineId || !elevationBackfillFileId) {
        throw new Error("请选择线路和高程文件");
      }
      const response = await fetchWithAuth("/api/v1/elevation/jobs/apply-line", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          line_id: lineId,
          file_record_id: elevationBackfillFileId,
          mode: elevationBackfillMode,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationApplyJobCreateResponse;
    },
    onSuccess: async () => {
      setError("");
      messageApi.success("高程回填任务已创建");
      await refreshLines();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "高程回填失败");
    },
  });
  const openCreateLineModal = () => {
    setEditingLine(null);
    lineForm.setFieldsValue(EMPTY_LINE_FORM);
    setLineModalOpen(true);
  };
  const openEditLineModal = (line: LineSummary) => {
    setEditingLine(line);
    lineForm.setFieldsValue({
      name: line.name,
      voltage_level: resolveVoltageOptionFromKv(line.voltage_kv),
    });
    setLineModalOpen(true);
  };
  const openCreateTowerModal = () => {
    setEditingTower(null);
    towerForm.setFieldsValue(EMPTY_TOWER_FORM);
    setTowerModalOpen(true);
    if (towerModels.length > 0) {
      const preferred = towerModels[0]?.code;
      if (preferred) {
        towerForm.setFieldsValue({ tower_model: preferred });
        applyTowerModelDefaults(preferred);
      }
    }
  };
  const openEditTowerModal = (item: LineTowerSummary) => {
    setEditingTower(item);
    towerForm.setFieldsValue({
      seq_no: item.seq_no,
      tower_no: item.tower_no,
      tower_model: item.tower_model ?? "",
      tower_type: item.tower_type ?? "",
      longitude: item.longitude,
      latitude: item.latitude,
      altitude_m: item.altitude_m,
      terrain: item.terrain ?? "",
      ground_resistance_ohm: item.ground_resistance_ohm,
      lightning_density: item.lightning_density,
      span_small_m: item.span_small_m,
      span_large_m: item.span_large_m,
      slope_1: item.slope_1,
      slope_2: item.slope_2,
      risk_level: item.risk_level ?? "",
    });
    setTowerModalOpen(true);
  };
  const openTowerProfileModal = (item: LineTowerSummary) => {
    setEditingTowerProfileTower(item);
    towerProfileForm.setFieldsValue(EMPTY_TOWER_PROFILE_FORM);
    setTowerProfileGeometryEditorMode("structured");
    setTowerProfileModalOpen(true);
  };
  const openLineParamModal = () => {
    setLineParamModalOpen(true);
  };
  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: "序号", dataIndex: "seq_no", width: 80 },
    {
      title: "塔号",
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: "模型", dataIndex: "tower_model", width: 180, render: (value: string | null) => value || "-" },
    { title: "塔型", dataIndex: "tower_type", width: 100, render: (value: string | null) => value || "-" },
    {
      title: "坐标",
      key: "geo",
      width: 200,
      render: (_: unknown, row) =>
        row.longitude !== null && row.latitude !== null
          ? `${row.longitude.toFixed(6)}, ${row.latitude.toFixed(6)}`
          : "-",
    },
    { title: "接地电阻", dataIndex: "ground_resistance_ohm", width: 100, render: (value: number | null) => value ?? "-" },
    { title: "地闪密度", dataIndex: "lightning_density", width: 100, render: (value: number | null) => value ?? "-" },
    {
      title: "风险等级",
      dataIndex: "risk_level",
      width: 100,
      render: (value: string | null) => {
        if (!value) return "-";
        const riskLevel = value.trim();
        let color = "default";
        if (riskLevel === "1") {
          color = "green";
        } else if (riskLevel === "2") {
          color = "orange";
        } else if (riskLevel === "3") {
          color = "red";
        }
        return <Tag color={color}>{value}</Tag>;
      },
    },
    {
      title: "更新时间",
      dataIndex: "update_date",
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      fixed: "right",
      render: (_: unknown, row) => {
        const moreMenuItems: MenuProps["items"] = [
          {
            key: "delete",
            label: "删除",
            danger: true,
            disabled: deleteTowerMutation.isPending,
          },
        ];
        return (
          <Space size="small" wrap>
            {canTowerManage && (
              <Button size="small" onClick={() => openEditTowerModal(row)}>
                编辑
              </Button>
            )}
            {canTowerManage && (
              <Button size="small" onClick={() => openTowerProfileModal(row)}>
                专业参数
              </Button>
            )}
            {canTowerManage && (
              <Dropdown
                menu={{
                  items: moreMenuItems,
                  onClick: ({ key }) => {
                    if (key === "delete") {
                      Modal.confirm({
                        title: "删除杆塔",
                        content: `确认删除杆塔 ${row.tower_no} 吗？`,
                        okText: "删除",
                        cancelText: "取消",
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          await deleteTowerMutation.mutateAsync(row.id);
                        },
                      });
                    }
                  },
                }}
                trigger={["click"]}
              >
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            )}
          </Space>
        );
      },
    },
  ];
  const terrainSelectionHint = useMemo(() => {
    if (!canElevationRead) {
      return "当前账号没有高程数据读取权限，线路分布图将使用椭球地表。";
    }
    if (!selectedTerrainDataset) {
      return null;
    }
    if (selectedTerrainDataset.terrain_status === "ready") {
      const bounds = selectedTerrainDataset.terrain_bounds;
      const boundsText = bounds
        ? `范围 ${bounds.west.toFixed(4)}, ${bounds.south.toFixed(4)} ~ ${bounds.east.toFixed(4)}, ${bounds.north.toFixed(4)}`
        : "范围待同步";
      return `当前 DEM：${selectedTerrainDataset.code}，地形已就绪，${boundsText}。`;
    }
    if (selectedTerrainDataset.terrain_status === "failed") {
      return `当前 DEM：${selectedTerrainDataset.code}，地形生成失败，将回退到椭球地表。`;
    }
    return `当前 DEM：${selectedTerrainDataset.code}，地形状态为${terrainStatusLabel(selectedTerrainDataset.terrain_status)}，就绪前将回退到椭球地表。`;
  }, [canElevationRead, selectedTerrainDataset]);
  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }
  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再访问线路管理页面。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `tower.read`）。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
        <Space align="center" size={8}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/admin/power-lines")}>
            返回列表
          </Button>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {selectedLine ? `${selectedLine.name} - 线路详情` : "线路详情"}
          </Typography.Title>
          {selectedLine?.code ? <Tag>{selectedLine.code}</Tag> : null}
        </Space>
        {lineQuery.isError ? (
          <Card>
            <Alert type="error" showIcon message="加载线路失败" description={lineQuery.error instanceof Error ? lineQuery.error.message : ""} />
          </Card>
        ) : (
          <>
            <Card size="small" className="power-line-detail-meta">
              <Card size="small" className="power-line-detail-meta">
                <Descriptions bordered size="small" column={3}>
                  <Descriptions.Item label="电压等级">
                    {selectedLine?.voltage_kv ?? "-"} kV
                  </Descriptions.Item>
                  <Descriptions.Item label="杆塔总数">
                    {selectedLine?.tower_count ?? towers.length}
                  </Descriptions.Item>
                  <Descriptions.Item label="估算长度">
                    {selectedLine?.estimated_length_km && selectedLine.estimated_length_km > 0 ? `${selectedLine.estimated_length_km.toFixed(2)} km` : "-"}
                  </Descriptions.Item>
                  <Descriptions.Item label="更新时间">
                    {selectedLine ? formatDateTime(selectedLine.update_date) : "-"}
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            </Card>
            <div className="mb-3 flex items-center justify-between gap-3">
              <Space size={8} wrap>
                {selectedLine && (
                  <Button onClick={openLineParamModal}>
                    线路参数准备
                  </Button>
                )}
                {canTowerManage && (
                  <Button onClick={() => importInputRef.current?.click()} loading={importMutation.isPending} disabled={!lineId}>
                    导入 CSV
                  </Button>
                )}
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file && lineId) {
                      importMutation.mutate(file);
                    }
                    event.target.value = "";
                  }}
                />
                <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending} disabled={!lineId}>
                  导出 CSV
                </Button>
                {canTowerManage && (
                  <Button type="primary" onClick={openCreateTowerModal} disabled={!lineId}>
                    新建杆塔
                  </Button>
                )}
              </Space>
              <Radio.Group
                value={towerViewMode}
                onChange={(e) => setTowerViewMode(e.target.value as "table" | "map")}
                optionType="button"
                buttonStyle="solid"
              >
                <Radio.Button value="map">地图</Radio.Button>
                <Radio.Button value="table">杆塔列表</Radio.Button>
              </Radio.Group>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-3" style={{ display: towerViewMode === "map" ? "flex" : "none" }}>
              <div className="flex flex-wrap items-center gap-3">
                <Select
                  className="w-72"
                  placeholder={canElevationRead ? "选择地形数据集" : "无高程读取权限"}
                  value={effectiveTerrainDatasetId ?? undefined}
                  allowClear
                  disabled={!canElevationRead}
                  loading={elevationDatasetsQuery.isFetching}
                  onChange={(value) => setSelectedTerrainDatasetId(value ?? null)}
                  options={terrainDatasetOptions}
                />
                <Segmented
                  value={terrainExaggeration}
                  options={[...TERRAIN_EXAGGERATION_OPTIONS]}
                  onChange={(value) => setTerrainExaggeration(value)}
                />
              </div>
              {terrainSelectionHint ? (
                <Typography.Text type="secondary">{terrainSelectionHint}</Typography.Text>
              ) : null}
              <PowerLineCesiumMap
                lineCode={selectedLine?.code}
                lineName={selectedLine?.name}
                towers={towers}
                terrainDataset={selectedTerrainDataset}
                accessToken={getAccessToken()}
                exaggeration={terrainExaggeration}
                loading={towersQuery.isFetching}
                height={POWER_LINES_MAP_DETAIL_HEIGHT}
                onRouteLengthChange={handleRouteLengthChange}
              />
            </div>
            <Space direction="vertical" size={12} className="w-full" style={{ display: towerViewMode === "table" ? "flex" : "none" }}>
              <div className="admin-filter-bar">
                <Form layout="inline">
                  <Form.Item label="关键词" className="admin-filter-keyword-item">
                    <Input value={towerKeyword} allowClear onChange={(event) => setTowerKeyword(event.target.value)} placeholder="按塔号/模型筛选" />
                  </Form.Item>
                  <Form.Item label="塔型" className="admin-filter-keyword-item">
                    <Select value={towerTypeFilter} options={[...TOWER_TYPE_OPTIONS]} onChange={(value) => setTowerTypeFilter(value)} />
                  </Form.Item>
                  <Form.Item label="风险等级" className="admin-filter-keyword-item">
                    <Input value={towerRiskFilter} allowClear onChange={(event) => setTowerRiskFilter(event.target.value)} placeholder="按风险等级筛选" />
                  </Form.Item>
                  <Form.Item>
                    <Button htmlType="button" icon={<SearchOutlined />} onClick={() => refreshTowers()} className="admin-search-btn">
                      查询
                    </Button>
                  </Form.Item>
                </Form>
              </div>
              <div className="relative overflow-x-auto">
                <Table<LineTowerSummary>
                  rowKey={(row) => row.id}
                  columns={towerColumns}
                  dataSource={towers}
                  loading={towersQuery.isFetching}
                  pagination={{
                    current: towerPagination.current,
                    pageSize: towerPagination.pageSize,
                    total: towersQuery.data?.total ?? 0,
                    showSizeChanger: true,
                    showTotal: (total) => `共 ${total} 条`,
                    hideOnSinglePage: false,
                    onChange: (page, pageSize) => {
                      setTowerPagination({ current: page, pageSize });
                    },
                  }}
                  scroll={{ x: 1520 }}
                />
              </div>
            </Space>
          </>
        )}
      </div>
      <Modal
        title={editingLine ? "编辑线路" : "新建线路"}
        open={lineModalOpen}
        okText={editingLine ? "保存" : "创建"}
        confirmLoading={saveLineMutation.isPending}
        onCancel={() => {
          if (saveLineMutation.isPending) return;
          setLineModalOpen(false);
        }}
        onOk={async () => {
          const values = await lineForm.validateFields();
          saveLineMutation.mutate(values);
        }}
      >
        <Form<LineFormValues> form={lineForm} layout="vertical" initialValues={EMPTY_LINE_FORM}>
          {editingLine ? (
            <Form.Item label="线路编码">
              <Input value={editingLine.code} disabled />
            </Form.Item>
          ) : null}
          <Form.Item
            name="name"
            label="线路名称"
            rules={[{ required: true, message: "请输入线路名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="voltage_level"
            label="电压等级"
            rules={[{ required: true, message: "请选择电压等级" }]}
          >
            <Select
              showSearch
              placeholder="请选择电压等级"
              options={[...LINE_VOLTAGE_OPTIONS].map((item) => ({ value: item.value, label: item.label }))}
              filterOption={(input, option) =>
                String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={editingTower ? "编辑杆塔" : "新建杆塔"}
        open={towerModalOpen}
        width={860}
        okText={editingTower ? "保存" : "创建"}
        confirmLoading={saveTowerMutation.isPending}
        onCancel={() => {
          if (saveTowerMutation.isPending) return;
          setTowerModalOpen(false);
        }}
        onOk={async () => {
          const values = await towerForm.validateFields();
          saveTowerMutation.mutate(values);
        }}
      >
        <Form<TowerFormValues> form={towerForm} layout="vertical" initialValues={EMPTY_TOWER_FORM}>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="seq_no" label="序号" rules={[{ required: true, message: "请输入序号" }]}>
              <InputNumber min={1} max={1000000} className="w-full" />
            </Form.Item>
            <Form.Item name="tower_no" label="塔号" rules={[{ required: true, message: "请输入塔号" }]}>
              <Input />
            </Form.Item>
            <Form.Item name="tower_model" label="杆塔模型">
              <Select
                showSearch
                allowClear
                loading={towerModelOptionsQuery.isFetching}
                options={towerModelOptions}
                placeholder="请选择杆塔模型"
                onChange={(value) => {
                  applyTowerModelDefaults(value);
                }}
                filterOption={(input, option) =>
                  String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())}
              />
            </Form.Item>
            <Form.Item name="tower_type" label="塔型">
              <Select
                options={[
                  { value: "", label: "未设置" },
                  { value: "直线", label: "直线" },
                  { value: "耐张", label: "耐张" },
                ]}
              />
            </Form.Item>
            <Form.Item name="longitude" label="经度">
              <InputNumber className="w-full" precision={8} />
            </Form.Item>
            <Form.Item name="latitude" label="纬度">
              <InputNumber className="w-full" precision={8} />
            </Form.Item>
            <Form.Item name="altitude_m" label="海拔(m)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="terrain" label="地形">
              <Input />
            </Form.Item>
            <Form.Item name="ground_resistance_ohm" label="接地电阻(Ω)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="lightning_density" label="地闪密度">
              <InputNumber className="w-full" precision={8} />
            </Form.Item>
            <Form.Item name="span_small_m" label="小号侧档距(m)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="span_large_m" label="大号侧档距(m)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="slope_1" label="地面倾角1">
              <InputNumber className="w-full" precision={8} />
            </Form.Item>
            <Form.Item name="slope_2" label="地面倾角2">
              <InputNumber className="w-full" precision={8} />
            </Form.Item>
            <Form.Item name="risk_level" label="风险等级">
              <Input />
            </Form.Item>
          </div>
        </Form>
      </Modal>
      <Modal
        title={editingTowerProfileTower ? `专业参数 - ${editingTowerProfileTower.tower_no}` : "专业参数"}
        open={towerProfileModalOpen}
        width={920}
        okText="保存"
        confirmLoading={saveTowerProfileMutation.isPending}
        onCancel={() => {
          if (saveTowerProfileMutation.isPending) return;
          setTowerProfileModalOpen(false);
          setEditingTowerProfileTower(null);
        }}
        onOk={async () => {
          const values = await towerProfileForm.validateFields();
          saveTowerProfileMutation.mutate(values);
        }}
      >
        <Form<TowerProfileFormValues> form={towerProfileForm} layout="vertical" initialValues={EMPTY_TOWER_PROFILE_FORM}>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <Form.Item name="structure_kind" label="直线/耐张">
              <Input placeholder="如：直线、耐张、直线杆塔" />
            </Form.Item>
            <Form.Item name="stroke_mode" label="绕击/反击模式">
              <Input placeholder="如：绕击、反击" />
            </Form.Item>
            {towerProfileTopologySpec.phaseSequenceFields.map((circuitIndex) => (
              <Form.Item
                key={`phase-sequence-${circuitIndex}`}
                name={`phase_sequence_${circuitIndex}` as "phase_sequence_1" | "phase_sequence_2" | "phase_sequence_3" | "phase_sequence_4"}
                label={`${["I", "II", "III", "IV"][circuitIndex - 1]}回相序`}
                rules={towerProfileGeometryEditorMode === "structured"
                  ? [{ required: true, message: `请输入${["I", "II", "III", "IV"][circuitIndex - 1]}回相序` }]
                  : undefined}
              >
                <Input placeholder="如：ABC、BAC" />
              </Form.Item>
            ))}
            {towerProfileTopologySpec.arresterFields.map((item) => (
              <Form.Item key={item.field} name={item.field} label={item.label}>
                <Select allowClear options={ARRESTER_INSTALL_OPTIONS} />
              </Form.Item>
            ))}
            <Form.Item name="protection_angle_left_deg" label="左保护角">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="protection_angle_right_deg" label="右保护角">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item
              name="shield_wire_height_m"
              label="避雷线高度(m)"
              rules={towerProfileGeometryEditorMode === "structured"
                ? [{ required: true, message: "请输入避雷线高度(m)" }]
                : undefined}
            >
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item
              name="insulator_length_m"
              label="绝缘子串长度(mm)"
              rules={towerProfileGeometryEditorMode === "structured"
                ? [{ required: true, message: "请输入绝缘子串长度(mm)" }]
                : undefined}
            >
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item
              name="call_height_m"
              label="杆塔呼高(m)"
              rules={towerProfileGeometryEditorMode === "structured"
                ? [{ required: true, message: "请输入杆塔呼高(m)" }]
                : undefined}
            >
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="angle_deg" label="电角度">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="current_a" label="雷电流幅值 a">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="current_b" label="雷电流幅值 b">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="current_type" label="雷电流波形">
              <Input placeholder="如：Heidler、双指数" />
            </Form.Item>
            <Form.Item name="current_head_time_us" label="波头时间(us)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
            <Form.Item name="current_tail_time_us" label="波尾时间(us)">
              <InputNumber className="w-full" precision={4} />
            </Form.Item>
          </div>
          <div className="space-y-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div className="space-y-2">
                <Typography.Text strong>专用编辑器类型</Typography.Text>
                <Segmented<TowerTopologyKind>
                  block
                  options={towerTopologyKindOptions}
                  value={towerProfileTopology}
                  onChange={(value) => {
                    handleTowerProfileTopologyChange(value);
                  }}
                />
              </div>
              <div className="space-y-2 xl:min-w-[240px]">
                <Typography.Text strong>录入模式</Typography.Text>
                <Segmented<TowerProfileGeometryEditorMode>
                  block
                  options={TOWER_PROFILE_EDITOR_MODE_OPTIONS}
                  value={towerProfileGeometryEditorMode}
                  onChange={(value) => {
                    setTowerProfileGeometryEditorMode(value);
                  }}
                />
              </div>
            </div>
            <Alert
              showIcon
              type="info"
              message={`当前使用 ${towerProfileTopologySpec.label}`}
              description={towerProfileTopologySpec.description}
            />
            {towerProfileGeometryEditorMode === "structured" ? (
              <>
                {towerProfileGeometryParseResult.error ? (
                  <Alert
                    showIcon
                    type="warning"
                    message="当前几何 JSON 无法解析"
                    description={`${towerProfileGeometryParseResult.error}。继续编辑将以当前拓扑的空白结构重新生成几何。`}
                  />
                ) : null}
                <Typography.Text type="secondary">
                  相序用于标识上/中/下层导线对应的 A/B/C 顺序；直流模式会把左极/右极映射到 I 回几何。
                </Typography.Text>
                <div className="grid gap-3 xl:grid-cols-2">
                  {towerProfileTopologySpec.circuitKeys.map((circuitKey) => (
                    <div key={circuitKey} className="rounded-lg border border-slate-200 p-4">
                      <Typography.Text strong>
                        {towerProfileTopology === "dc" ? "直流极导线几何" : `${circuitKey}回导线几何`}
                      </Typography.Text>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {towerProfileTopologySpec.phaseKeys.map((phaseKey) => (
                          <Form.Item
                            key={`${circuitKey}-${phaseKey}-spacing`}
                            label={`${towerProfileTopologySpec.phaseLabels[phaseKey]}导线中距(m)`}
                          >
                            <InputNumber
                              className="w-full"
                              precision={4}
                              value={getCircuitGeometryMetric(
                                towerProfileGeometryParseResult.geometry,
                                circuitKey,
                                "phase_spacing_m",
                                phaseKey,
                              )}
                              onChange={(value) => {
                                updateTowerProfileGeometryText((currentGeometry) => setCircuitGeometryMetric(
                                  currentGeometry,
                                  towerProfileTopology,
                                  circuitKey,
                                  "phase_spacing_m",
                                  phaseKey,
                                  value,
                                ));
                              }}
                            />
                          </Form.Item>
                        ))}
                        {towerProfileTopologySpec.phaseKeys.map((phaseKey) => (
                          <Form.Item
                            key={`${circuitKey}-${phaseKey}-height`}
                            label={`${towerProfileTopologySpec.phaseLabels[phaseKey]}导线高度(m)`}
                          >
                            <InputNumber
                              className="w-full"
                              precision={4}
                              value={getCircuitGeometryMetric(
                                towerProfileGeometryParseResult.geometry,
                                circuitKey,
                                "phase_height_m",
                                phaseKey,
                              )}
                              onChange={(value) => {
                                updateTowerProfileGeometryText((currentGeometry) => setCircuitGeometryMetric(
                                  currentGeometry,
                                  towerProfileTopology,
                                  circuitKey,
                                  "phase_height_m",
                                  phaseKey,
                                  value,
                                ));
                              }}
                            />
                          </Form.Item>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <Form.Item label="左避雷中距(m)">
                    <InputNumber
                      className="w-full"
                      precision={4}
                      value={getLightningWireMetric(towerProfileGeometryParseResult.geometry, "left_mid_distance_m")}
                      onChange={(value) => {
                        updateTowerProfileGeometryText((currentGeometry) => setLightningWireMetric(
                          currentGeometry,
                          towerProfileTopology,
                          "left_mid_distance_m",
                          value,
                        ));
                      }}
                    />
                  </Form.Item>
                  <Form.Item label="右避雷中距(m)">
                    <InputNumber
                      className="w-full"
                      precision={4}
                      value={getLightningWireMetric(towerProfileGeometryParseResult.geometry, "right_mid_distance_m")}
                      onChange={(value) => {
                        updateTowerProfileGeometryText((currentGeometry) => setLightningWireMetric(
                          currentGeometry,
                          towerProfileTopology,
                          "right_mid_distance_m",
                          value,
                        ));
                      }}
                    />
                  </Form.Item>
                  <Form.Item label="几何拓扑标记">
                    <Input value={towerProfileTopology} disabled />
                  </Form.Item>
                </div>
              </>
            ) : null}
          </div>
          <div className="grid gap-3 xl:grid-cols-2">
            <Form.Item
              name="geometry_layers_json"
              label={towerProfileGeometryEditorMode === "structured" ? "回路几何 JSON（自动生成）" : "回路几何 JSON"}
              rules={[{
                validator: async (_, value) => {
                  const parsed = parseJsonObjectText(String(value ?? "{}"), "回路几何 JSON");
                  if (towerProfileGeometryEditorMode === "structured") {
                    const errorMessage = validateStructuredGeometry(parsed, towerProfileTopology);
                    if (errorMessage) {
                      throw new Error(errorMessage);
                    }
                  }
                },
              }]}
            >
              <Input.TextArea rows={12} spellCheck={false} readOnly={towerProfileGeometryEditorMode === "structured"} />
            </Form.Item>
            <Form.Item
              name="cause_analysis"
              label="原因分析"
            >
              <Input.TextArea rows={4} spellCheck={false} placeholder="如：接地电阻偏高、保护角裕度不足" />
            </Form.Item>
            <Form.Item
              name="mitigation_recommendation"
              label="措施推荐"
            >
              <Input.TextArea rows={4} spellCheck={false} placeholder="如：建议补充关键相避雷器并复核安装位置" />
            </Form.Item>
            <Form.Item
              name="extra_profile_json"
              label="额外字段 JSON"
              rules={[{
                validator: async (_, value) => {
                  if (!value || !String(value).trim()) {
                    return;
                  }
                  parseJsonObjectText(String(value), "额外字段 JSON");
                },
                message: "请输入合法 JSON 对象",
              }]}
            >
              <Input.TextArea rows={12} spellCheck={false} />
            </Form.Item>
          </div>
        </Form>
      </Modal>
      <Modal
        title={selectedLine ? `线路参数准备 - ${selectedLine.name}` : "线路参数准备"}
        open={lineParamModalOpen}
        onCancel={() => {
          setLineParamModalOpen(false);
          setPrepareDensityRadiusKm(3);
          setPrepareDensityYears(null);
          setElevationBackfillFileId(null);
          setElevationBackfillMode("fill_null_only");
          setSelectedCurrentEventId(null);
        }}
        footer={null}
        width={800}
        destroyOnHidden
      >
        <ParamPrepErrorBoundary>
          {selectedLine ? (
          <Space direction="vertical" size={16} className="w-full">
            <Alert
              type={selectedLinePreparation.all_ready ? "success" : "warning"}
              showIcon
              message={selectedLinePreparation.all_ready ? "当前线路参数已齐备" : `缺少：${selectedLinePreparation.missing_items.join("、")}`}
            />
            <Space direction="vertical" size={12} className="w-full">
              <Typography.Text strong>准备项列表</Typography.Text>
              <Space direction="vertical" size={8} className="w-full">
                <div className="flex items-center justify-between rounded border border-slate-200 p-3">
                  <Space>
                    <Tag color={selectedLinePreparation.lightning_current.ready ? "green" : "red"}>
                      {selectedLinePreparation.lightning_current.ready ? "已就绪" : "未就绪"}
                    </Tag>
                    <Typography.Text>雷电流幅值</Typography.Text>
                    {selectedLinePreparation.lightning_current.ready && (
                      <Typography.Text type="secondary">
                        (a={String(selectedLinePreparation.lightning_current.values.current_a ?? "-")}, b={String(selectedLinePreparation.lightning_current.values.current_b ?? "-")})
                      </Typography.Text>
                    )}
                    <Typography.Text type="secondary">
                      {selectedLinePreparation.lightning_current.tower_ready_count}/{selectedLinePreparation.lightning_current.tower_total_count}
                    </Typography.Text>
                    {selectedCurrentEventId && (
                      <Tag color="blue">已选择事件</Tag>
                    )}
                  </Space>
                  <Button
                    type="primary"
                    size="small"
                    onClick={() => setCurrentEventPickerOpen(true)}
                    loading={prepareCurrentMutation.isPending}
                    disabled={!canTowerManage || !selectedLine}
                  >
                    回填雷电流幅值
                  </Button>
                </div>
                <div className="flex items-center justify-between rounded border border-slate-200 p-3">
                  <Space>
                    <Tag color={selectedLinePreparation.lightning_density.ready ? "green" : "red"}>
                      {selectedLinePreparation.lightning_density.ready ? "已就绪" : "未就绪"}
                    </Tag>
                    <Typography.Text>地闪密度</Typography.Text>
                    {selectedLinePreparation.lightning_density.ready && (
                      <Typography.Text type="secondary">
                        (Ng={String(selectedLinePreparation.lightning_density.values.ng ?? "-")})
                      </Typography.Text>
                    )}
                    <Typography.Text type="secondary">
                      {selectedLinePreparation.lightning_density.tower_ready_count}/{selectedLinePreparation.lightning_density.tower_total_count}
                    </Typography.Text>
                  </Space>
                  <Button
                    type="primary"
                    size="small"
                    onClick={() => {
                      Modal.confirm({
                        title: "回填地闪密度",
                        content: (
                          <Space direction="vertical" size={12} className="w-full pt-4">
                            <div>
                              <Typography.Text>半径(km):</Typography.Text>
                              <InputNumber
                                min={0.05}
                                max={50}
                                step={0.5}
                                value={prepareDensityRadiusKm}
                                onChange={(value) => setPrepareDensityRadiusKm(typeof value === "number" ? value : 3)}
                                className="ml-2 w-32"
                              />
                            </div>
                            <div>
                              <Typography.Text>年限(可选):</Typography.Text>
                              <InputNumber
                                min={0.1}
                                max={100}
                                step={0.5}
                                value={prepareDensityYears}
                                onChange={(value) => setPrepareDensityYears(typeof value === "number" ? value : null)}
                                className="ml-2 w-32"
                              />
                            </div>
                          </Space>
                        ),
                        okText: "确定回填",
                        cancelText: "取消",
                        onOk: () => {
                          prepareDensityMutation.mutate();
                        },
                      });
                    }}
                    loading={prepareDensityMutation.isPending}
                    disabled={!canTowerManage || !selectedLine}
                  >
                    回填地闪密度
                  </Button>
                </div>
                <div className="flex items-center justify-between rounded border border-slate-200 p-3">
                  <Space>
                    <Tag color={selectedLinePreparation.ground_slope.ready ? "green" : "red"}>
                      {selectedLinePreparation.ground_slope.ready ? "已就绪" : "未就绪"}
                    </Tag>
                    <Typography.Text>地面倾角</Typography.Text>
                    <Typography.Text type="secondary">
                      {selectedLinePreparation.ground_slope.tower_ready_count}/{selectedLinePreparation.ground_slope.tower_total_count}
                    </Typography.Text>
                    <Typography.Text type="secondary">(数据来源：地形分析)</Typography.Text>
                  </Space>
                </div>
                <div className="rounded border border-slate-200 p-3">
                  <Space direction="vertical" size={8} className="w-full">
                    <div className="flex items-center justify-between">
                      <Space>
                        <Tag color="orange">未就绪</Tag>
                        <Typography.Text strong>高程回填</Typography.Text>
                      </Space>
                      <Button
                        type="primary"
                        size="small"
                        onClick={() => elevationBackfillMutation.mutate()}
                        loading={elevationBackfillMutation.isPending}
                        disabled={!canTowerManage || !selectedLine || !elevationBackfillFileId}
                      >
                        高程回填
                      </Button>
                    </div>
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        选择线路后，根据各杆塔经纬度范围自动匹配覆盖该范围的高程文件。
                      </Typography.Text>
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                      <div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>选择高程文件</Typography.Text>
                        <Select
                          className="w-full"
                          size="small"
                          placeholder={lineBbox ? "选择高程文件" : "请先选择线路并加载杆塔"}
                          loading={elevationFileRecordsQuery.isFetching}
                          value={elevationBackfillFileId}
                          notFoundContent={
                            elevationFileRecords.length === 0
                              ? "暂无高程文件"
                              : matchedElevationRecords.length === 0
                                ? "该线路范围内未找到匹配的高程文件"
                                : undefined
                          }
                          onChange={(value) => setElevationBackfillFileId(value)}
                          options={elevationFileRecords.map((file) => {
                            const matched = matchedElevationRecords.some((f) => f.id === file.id);
                            const label = `${file.file_name} (${file.resolution_m ? `${file.resolution_m.toFixed(1)}m` : "-"})`;
                            return {
                              label: matched ? label : `${label} ⚠️ 不匹配线路范围`,
                              value: file.id,
                              disabled: !matched,
                            };
                          })}
                        />
                      </div>
                      <div>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>回填模式</Typography.Text>
                        <Select
                          className="w-full"
                          size="small"
                          value={elevationBackfillMode}
                          onChange={(value) => setElevationBackfillMode(value)}
                          options={[
                            { label: "仅填空", value: "fill_null_only" },
                            { label: "全部覆盖", value: "overwrite_all" },
                          ]}
                        />
                      </div>
                    </div>
                  </Space>
                </div>
              </Space>
            </Space>
          </Space>
        ) : (
          <Empty description="请先选择线路" />
        )}
        </ParamPrepErrorBoundary>
      </Modal>
      <Modal
        title="选择雷电流事件"
        open={currentEventPickerOpen}
        onCancel={() => {
          setCurrentEventPickerOpen(false);
        }}
        onOk={() => {
          if (selectedCurrentEventId) {
            setCurrentEventPickerOpen(false);
            prepareCurrentMutation.mutate();
          }
        }}
        okText="确定回填"
        confirmLoading={prepareCurrentMutation.isPending}
        okButtonProps={{ disabled: !selectedCurrentEventId }}
        width={700}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} className="w-full">
          <Typography.Text type="secondary">
            将读取该线路关联的全部已完成雷电流幅值记录的 MinIO 源文件进行拟合计算。可先查看已有记录。
          </Typography.Text>
          <Select
            className="w-full"
            placeholder="搜索并查看雷电流幅值记录..."
            showSearch
            loading={lightningEventsQuery.isFetching}
            notFoundContent={lightningEventsQuery.isFetching ? "加载中..." : "暂无雷电流幅值记录"}
            value={selectedCurrentEventId}
            onChange={(value) => setSelectedCurrentEventId(value)}
            filterOption={(input, option) =>
              (option?.label as string ?? "").toLowerCase().includes(input.toLowerCase())
            }
            options={(lightningEventsQuery.data?.items ?? []).map((event) => ({
              label: `${event.location_tag || event.city || event.source_file_name || event.event_id} (${event.event_time ? new Date(event.event_time).toLocaleDateString("zh-CN") : "时间未知"}, ${event.longitude != null ? event.longitude.toFixed(4) : "-"}, ${event.latitude != null ? event.latitude.toFixed(4) : "-"})`,
              value: event.id,
            }))}
          />
          {selectedCurrentEventId && lightningEventsQuery.data?.items ? (() => {
            const ev = lightningEventsQuery.data.items.find((e) => e.id === selectedCurrentEventId);
            if (!ev) return null;
            return (
              <div className="rounded border border-slate-200 p-3 w-full">
                <Space direction="vertical" size={4}>
                  <Typography.Text strong>{ev.location_tag || ev.source_file_name || ev.event_id}</Typography.Text>
                  <Typography.Text type="secondary">
                    事件编号: {ev.event_id} | 地点: {ev.location_tag || "-"}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    经度: {ev.longitude != null ? ev.longitude.toFixed(4) : "-"} | 纬度: {ev.latitude != null ? ev.latitude.toFixed(4) : "-"}
                  </Typography.Text>
                  <Typography.Text type="secondary">
                    发生时间: {formatDateTime(ev.event_time)} | 峰值电流: {ev.peak_current_ka != null ? `${ev.peak_current_ka} kA` : "-"}
                  </Typography.Text>
                </Space>
              </div>
            );
          })() : null}
        </Space>
      </Modal>
    </>
  );
}
