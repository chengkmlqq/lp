/** 单风机计算（LP-36 独立模块）类型定义。 */

export type WindTurbineCalcStatus = "pending" | "processing" | "completed" | "failed" | "cancelled";

export type WindTurbineCalcCreateRequest = {
  name: string;
  hub_height: number;
  receptor_radii: number[];
  blade_length: number | null;
  start_current: number;
  angle_list: number[];
};

export type WindTurbineCalcCreateResponse = {
  job_id: string;
  task_id: string | null;
  status: string;
};

export type WindTurbineCalcJobSummary = {
  id: string;
  name: string;
  hub_height: number;
  receptor_radii: number[];
  blade_length: number;
  start_current: number;
  angle_list: number[];
  angle_count: number;
  engine_module: string;
  engine_version_hash: string | null;
  engine_version_tag: string | null;
  runtime_version: string | null;
  status: WindTurbineCalcStatus | string;
  stage: string;
  progress: number;
  task_id: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  mean_failure_rate: number | null;
  min_failure_rate: number | null;
  max_failure_rate: number | null;
  create_user: string | null;
  create_date: string | null;
  // 型号追溯字段为后端可选项，缺失时按数值展示即可。
  turbine_model_name?: string | null;
  blade_model_name?: string | null;
};

export type WindTurbineCalcJobListResponse = {
  total: number;
  items: WindTurbineCalcJobSummary[];
};

export type WindTurbineCalcJobDetail = WindTurbineCalcJobSummary & {
  min_failure_rate_theta: number | null;
  max_failure_rate_theta: number | null;
  chart_object_key: string | null;
  csv_object_key: string | null;
  update_date: string | null;
};

export type WindTurbineCalcResultRow = {
  theta_deg: number;
  failure_rate: number;
  failure_rate_pct: number;
};

export type WindTurbineCalcResultListResponse = {
  total: number;
  items: WindTurbineCalcResultRow[];
  summary: {
    mean_failure_rate: number | null;
    min_failure_rate: number | null;
    max_failure_rate: number | null;
    min_failure_rate_theta: number | null;
    max_failure_rate_theta: number | null;
    angle_count: number;
  };
};

export type WindTurbineCalcEngineInfo = {
  module_slug: string;
  configured_dir: string;
  compiled_dir_exists: boolean;
  exe_name: string;
  exe_exists: boolean;
  launch_script: string;
  launch_script_exists: boolean;
  runtime_version: string | null;
  active_version_hash: string | null;
  active_version_tag: string | null;
  message: string | null;
};

export const DEFAULT_RADII = [53.6, 63.6, 73.6, 78.6, 82.6];
export const DEFAULT_ANGLES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110];
