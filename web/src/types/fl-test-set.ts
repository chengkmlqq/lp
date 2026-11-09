/**
 * 防雷测试集类型（对应后端 /api/v1/fl-test-sets 系列接口）。
 *
 * 集合级分类 category：
 * - fl_calc  防雷计算用例（normal/tongtiao，单塔样例 + 评估标准）
 * - retrofit 防雷改造用例（建线/非建线 + 前置任务 + 参考评估方案）
 */

export type FlTestSetCategory = "fl_calc" | "retrofit";
export type FlTestCalcKind = "normal" | "tongtiao";
export type FlTestRetrofitMode = "jianxian" | "feijianxian";
export type FlTestSetStatus = "enabled" | "disabled";
export type FlTestRunStatus = "pending" | "running" | "success" | "partial" | "failed" | "cancelled";
export type FlTestRunCaseStatus = "pending" | "running" | "success" | "failed" | "skipped" | "cancelled";
export type FlTestVerdict = "auto_pass" | "auto_fail" | "pending_manual" | "manual_pass" | "manual_fail";

export interface FlTestMetric {
  key: string;
  label?: string;
  min?: number | null;
  max?: number | null;
  expect?: string | null;
  scope?: string | null;
}

export interface FlTestSetSummary {
  id: string;
  category: FlTestSetCategory;
  name: string;
  description: string;
  status: FlTestSetStatus;
  tags_json: string[];
  case_count: number;
  enabled_case_count: number;
  last_run: { id: string; status: string; total_cases: number; create_date: string | null } | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
}

export interface FlTestSetListResponse {
  items: FlTestSetSummary[];
  total: number;
}

export interface FlTestCaseSummary {
  id: string;
  set_id: string;
  name: string;
  description: string;
  calc_kind: FlTestCalcKind | null;
  line_id: string | null;
  line_code: string | null;
  line_name: string | null;
  tower_id: string | null;
  tower_no: string | null;
  params_json: Record<string, unknown>;
  mode: FlTestRetrofitMode | null;
  non_construction: boolean;
  source_job_id: string | null;
  source_job_name: string | null;
  source_job_status: string | null;
  selected_tower_ids: string[];
  expected_json: { metrics?: FlTestMetric[]; plan?: Record<string, unknown>; abnormal_signals?: string[] } & Record<string, unknown>;
  enabled: boolean;
  sort_order: number;
  create_date: string;
  update_date: string;
}

export interface FlTestCaseListResponse {
  items: FlTestCaseSummary[];
  total: number;
}

export interface FlTestRunCaseSummary {
  id: string;
  run_id: string;
  case_id: string;
  case_name: string;
  job_id: string | null;
  job_name: string | null;
  job_type: string | null;
  job_status: string | null;
  status: FlTestRunCaseStatus;
  verdict: FlTestVerdict | null;
  eval_json: { checks?: Array<{ key: string; label?: string; expect?: unknown; actual?: unknown; pass?: boolean | null }>; comment?: string; manual_comment?: string } & Record<string, unknown>;
  error_message: string | null;
  create_date: string;
  update_date: string;
}

export interface FlTestRunSummary {
  id: string;
  set_id: string;
  status: FlTestRunStatus;
  total_cases: number;
  finished_cases: number;
  passed_cases: number;
  failed_cases: number;
  pending_manual_cases: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  result_summary_json: Record<string, unknown>;
  create_date: string;
  create_user: string | null;
  cases?: FlTestRunCaseSummary[];
}

export interface FlTestRunListResponse {
  items: FlTestRunSummary[];
  total: number;
}
