/** 风电场计算（LP-35 独立模块）类型定义。 */

export type WindFarmCalcStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

export type WindFarmCalcPrepBatchOption = {
  id: string;
  name: string;
  wind_farm_name: string | null;
  turbine_count: number;
  grid_nx: number;
  grid_ny: number;
  risk_base_s: number;
  files_ready: number;
  create_date: string | null;
};

export type WindFarmCalcPrepBatchOptions = {
  items: WindFarmCalcPrepBatchOption[];
};

export type WindFarmCalcCreateResponse = {
  job_id: string;
  task_id: string | null;
  status: string;
};

export type WindFarmCalcJobSummary = {
  id: string;
  name: string;
  prep_batch_id: string;
  status: WindFarmCalcStatus | string;
  stage: string;
  progress: number;
  task_id: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  turbine_count: number;
  risk_I_count: number;
  risk_II_count: number;
  risk_III_count: number;
  risk_IV_count: number;
  shutdown_count: number;
  circuit_shutdown_count: number;
  farm_shutdown_count: number;
  risk_mismatch_count: number;
  create_user: string | null;
  create_date: string | null;
};

export type WindFarmCalcJobListResponse = {
  total: number;
  items: WindFarmCalcJobSummary[];
};

export type WindFarmCalcJobDetail = WindFarmCalcJobSummary & {
  engine_path: string | null;
  engine_md5: string | null;
  stdout_object_key: string | null;
  output_object_key: string | null;
  preflight_json: {
    ok?: boolean;
    params?: { n: number; s: number; nx: number; ny: number } | null;
    checks?: { code: string; label: string; passed: boolean; message: string }[];
    errors?: string[];
    grid_rows?: number;
  } | null;
  update_date: string | null;
};

export type WindFarmCalcResultRow = {
  seq: number;
  turbine_no: string | null;
  lon: number;
  lat: number;
  value_v: number;
  risk_level: number;
  suggestion_code: number;
  suggestion_text: string;
  circuit_no: number | null;
  raw_line: string | null;
};

export type WindFarmCalcResultListResponse = {
  total: number;
  items: WindFarmCalcResultRow[];
};

export type WindFarmCalcEngineInfo = {
  configured: string;
  resolved: string | null;
  exists: boolean;
  size: number | null;
  modified_at: string | null;
  md5: string | null;
  wine_binary: string;
  wine_available: boolean;
  wine_version: string | null;
  wine_error: string | null;
  message: string | null;
};

export type WindFarmCalcLogInfo = {
  job_id: string;
  task_id: string | null;
  sse_url: string | null;
  raw_url: string | null;
};

export const RISK_LABELS: Record<number, string> = { 1: "I", 2: "II", 3: "III", 4: "IV" };
export const RISK_COLORS: Record<number, string> = {
  1: "green",
  2: "blue",
  3: "orange",
  4: "red",
};
