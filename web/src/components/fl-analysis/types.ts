import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";
import type { ReactNode } from "react";

/**
 * 动态详情选项卡项（LP-274）。
 * key 用杆塔唯一标识去重，label 含塔号 + 风险等级 Tag，closable 允许关闭，
 * 与地闪密度统计页的 detailTabs 模式保持一致。
 */
export type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

export type CreateJobFormValues = {
  job_name: string;
  line_id: string;
  job_type: "normal" | "tongtiao" | "risk";
  current_waveform: "heidler" | "double_slope" | "double_exponential";
  flashover_method: "guideline" | "intersection" | "leader_development";
  altitude_correction: "none" | "formula1" | "formula2";
  induced_voltage_formula: "formula1" | "formula2";
  head_time_min_us: number;
  head_time_max_us: number;
  head_time_step_us: number;
  tail_time_min_us: number;
  tail_time_max_us: number;
  tail_time_step_us: number;
  fanji_naleishuiping_method: "guicheng" | "atp";
  raoji_naleishuiping_method: "guicheng" | "atp";
  fanji_tzl_method: "none" | "guicheng" | "egm";
  raoji_tzl_method: "none" | "guicheng" | "egm";
  include_tower_ids: string[];
  /** 普通/同跳计算勾选的杆塔 ID 列表（空=全部杆塔） */
  selected_tower_ids: string[];
};

export type MitigationFormValues = {
  job_name: string;
  non_construction: boolean;
};

export type ScenarioFormValues = {
  job_name: string;
  base_job_id: string;
};

export type ReportFormValues = {
  job_name: string;
};

export type ReasonDetail = {
  code: string;
  label: string;
  value?: unknown;
  standard_value?: unknown;
  grade?: number | null;
  triggered?: boolean;
};

export type MitigationAction = {
  code: string;
  label: string;
  summary: string;
  current_value?: unknown;
  target_value?: unknown;
  unit?: string;
  phases?: string[];
};

export type WorkflowRange = {
  min?: number | null;
  max?: number | null;
  step?: number | null;
};

export type WorkflowSummary = {
  current_waveform?: string;
  flashover_method?: string;
  altitude_correction?: string;
  induced_voltage_formula?: string;
  head_time_range_us?: WorkflowRange;
  tail_time_range_us?: WorkflowRange;
  scan_point_count?: number;
};

export type ScanPoint = {
  head_time_us?: number | null;
  tail_time_us?: number | null;
  risk_level?: string | null;
  score?: number | null;
  counterstrike_withstand_ka?: number | null;
  counterstrike_trip_rate?: number | null;
  shielding_withstand_ka?: number | null;
  shielding_trip_rate?: number | null;
  flashover_phase?: string | null;
  dominant_phase_set?: string | null;
};

export type SelectedCase = {
  head_time_us?: number | null;
  tail_time_us?: number | null;
  risk_level?: string | null;
  score?: number | null;
  flashover_phase?: string | null;
  dominant_phase_set?: string | null;
};

export type PhaseResult = {
  phase: string;
  circuit?: string | null;
  shielding_withstand_ka?: number | null;
  shielding_trip_rate?: number | null;
  counterstrike_withstand_ka?: number | null;
  counterstrike_trip_rate?: number | null;
};

export type MultiPhaseResult = {
  phase_count: number;
  label: string;
  flashover_phase?: string | null;
  counterstrike_withstand_ka?: number | null;
  trip_rate?: number | null;
};

export const CREATE_JOB_DEFAULTS: CreateJobFormValues = {
  job_name: "",
  line_id: "",
  job_type: "normal",
  current_waveform: "heidler",
  flashover_method: "intersection",
  altitude_correction: "none",
  induced_voltage_formula: "formula1",
  head_time_min_us: 2.6,
  head_time_max_us: 2.6,
  head_time_step_us: 0.1,
  tail_time_min_us: 50,
  tail_time_max_us: 50,
  tail_time_step_us: 1,
  fanji_naleishuiping_method: "guicheng",
  raoji_naleishuiping_method: "guicheng",
  fanji_tzl_method: "none",
  raoji_tzl_method: "none",
  include_tower_ids: [],
  selected_tower_ids: [],
};

export function formatRiskLevel(value: string | null | undefined): string {
  if (value === "high") return "高风险";
  if (value === "medium") return "中风险";
  if (value === "low") return "低风险";
  return value || "-";
}

export function formatJobType(jobType: string, nonConstruction = false): string {
  if (jobType === "risk") return "风险评估";
  if (jobType === "mitigation") return nonConstruction ? "措施推荐(非建线)" : "措施推荐";
  if (jobType === "normal") return "普通计算";
  if (jobType === "tongtiao") return "同跳计算";
  if (jobType === "report") return "报告";
  if (jobType === "scenario") return "加装避雷器复算";
  return jobType || "-";
}

export function formatCurrentWaveform(value: string | null | undefined): string {
  if (value === "heidler") return "Heidler";
  if (value === "double_slope") return "双斜角";
  if (value === "double_exponential") return "双指数";
  return value || "-";
}

export function formatFlashoverMethod(value: string | null | undefined): string {
  if (value === "guideline") return "规程法";
  if (value === "intersection") return "相交法";
  if (value === "leader_development") return "先导发展法";
  return value || "-";
}

export function formatAltitudeCorrection(value: string | null | undefined): string {
  if (value === "none") return "无";
  if (value === "formula1") return "推荐公式1";
  if (value === "formula2") return "推荐公式2";
  return value || "-";
}

/**
 * 优先用维度管理 labelMap 显示 code → name，未命中时回退到静态格式化。
 * 维度数据加载失败 / 值未维护时返回原始 code（同现有 fallback 行为）。
 */
export function formatDimensionValue(
  value: string | null | undefined,
  labelMap: Map<string, string> | undefined,
  fallback: (v: string | null | undefined) => string,
): string {
  if (!value) {
    return "-";
  }
  const mapped = labelMap?.get(value);
  if (mapped) {
    return mapped;
  }
  return fallback(value);
}

export function formatInducedVoltageFormula(value: string | null | undefined): string {
  if (value === "formula1") return "公式1";
  if (value === "formula2") return "公式2";
  return value || "-";
}

export function formatExternalAdapter(value: string | null | undefined): string {
  if (value === "wine") return "Wine / ATP";
  if (value === "atp") return "原生 ATP";
  if (value === "placeholder") return "规则近似";
  if (value === "custom") return "自定义";
  return value || "-";
}

export function riskColor(value: string | null | undefined): string {
  if (value === "high") return "red";
  if (value === "medium") return "orange";
  if (value === "low") return "green";
  return "default";
}

export function statusColor(value: string | null | undefined): string {
  if (value === "success") return "green";
  if (value === "failed" || value === "blocked") return "red";
  if (value === "running") return "blue";
  if (value === "queued") return "cyan";
  return "default";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
}

export function stringifyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export function readObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

export function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "-";
}

export function readOptionalString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return null;
}

export function readOptionalNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" ? value : null;
}

export function preparationColor(ready: boolean): string {
  return ready ? "green" : "red";
}

export function readDownloadFilename(headerValue: string | null, fallback: string): string {
  if (!headerValue) {
    return fallback;
  }
  const utf8Matched = /filename\*=UTF-8''([^;]+)/i.exec(headerValue);
  if (utf8Matched?.[1]) {
    try {
      return decodeURIComponent(utf8Matched[1]);
    } catch {
      return utf8Matched[1];
    }
  }
  const matched = /filename="?([^"]+)"?/i.exec(headerValue);
  return matched?.[1] ?? fallback;
}

export function readArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function readReasonDetails(row: FlAnalysisTowerResultSummary | null): ReasonDetail[] {
  const value = row ? readObject(row.result_json).reason_details : null;
  return readArray<ReasonDetail>(value);
}

export function readMitigationActions(row: FlAnalysisTowerResultSummary | null): MitigationAction[] {
  const value = row ? readObject(row.result_json).mitigation_actions : null;
  return readArray<MitigationAction>(value);
}

export function readWorkflow(row: FlAnalysisTowerResultSummary | null): WorkflowSummary {
  return readObject(row ? readObject(row.result_json).workflow : null) as WorkflowSummary;
}

export function readSelectedCase(row: FlAnalysisTowerResultSummary | null): SelectedCase {
  return readObject(row ? readObject(row.result_json).selected_case : null) as SelectedCase;
}

export function readScanPoints(row: FlAnalysisTowerResultSummary | null): ScanPoint[] {
  return readArray<ScanPoint>(row ? readObject(row.result_json).scan_points : null);
}

export function readPhaseResults(row: FlAnalysisTowerResultSummary | null): PhaseResult[] {
  return readArray<PhaseResult>(row ? readObject(row.result_json).phase_results : null);
}

export function readMultiPhaseResults(row: FlAnalysisTowerResultSummary | null): MultiPhaseResult[] {
  return readArray<MultiPhaseResult>(row ? readObject(row.result_json).multi_phase_results : null);
}

export function readCurrentRisk(row: FlAnalysisTowerResultSummary): string | null {
  const value = readObject(row.result_json).current_risk_level;
  return typeof value === "string" ? value : null;
}

export function readCurrentScore(row: FlAnalysisTowerResultSummary): number | null {
  const value = readObject(row.result_json).current_score;
  return typeof value === "number" ? value : null;
}

export function mitigationMode(job: FlAnalysisJobDetail | FlAnalysisJobSummary | null): boolean {
  if (!job) {
    return false;
  }
  const options = readObject(job.execution_options_json);
  return Boolean(options.non_construction);
}

// LP-561: readMitigationMode 为 mitigationMode 的兼容别名（lightning-retrofit/high-risk-reason 仍在引用）
export const readMitigationMode = mitigationMode;

export function waveformJobType(job: FlAnalysisJobDetail | FlAnalysisJobSummary | null): "normal" | "tongtiao" | null {
  if (!job) {
    return null;
  }
  if (job.job_type === "normal" || job.job_type === "tongtiao") {
    return job.job_type;
  }
  if (job.job_type === "scenario") {
    const baseJobType = readOptionalString(readObject(job.execution_options_json), "base_job_type");
    return baseJobType === "tongtiao" ? "tongtiao" : "normal";
  }
  return null;
}

export function selectedTowerCount(job: FlAnalysisJobDetail | null): number {
  if (!job) {
    return 0;
  }
  const value = readObject(job.execution_options_json).selected_tower_ids;
  return Array.isArray(value) ? value.length : 0;
}

export function formatRangeSummary(range: WorkflowRange | undefined): string {
  if (!range) {
    return "-";
  }
  const min = typeof range.min === "number" ? range.min : null;
  const max = typeof range.max === "number" ? range.max : null;
  const step = typeof range.step === "number" ? range.step : null;
  if (min === null || max === null || step === null) {
    return "-";
  }
  return `${min} ~ ${max} / 步长 ${step}`;
}
