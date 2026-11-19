/** 风电场数据准备（LP-33 独立模块）类型定义。 */

export type WindDataPrepStatus = "pending" | "processing" | "completed" | "failed";
export type WindDataPrepTerrainMode = "zero" | "tif";

export type WindDataPrepReportCheck = {
  code: string;
  label: string;
  level: string;
  passed: boolean;
  message: string;
};

export type WindDataPrepReport = {
  status: "pass" | "blocked" | string;
  checks: WindDataPrepReportCheck[];
  summary: Record<string, unknown>;
};

export type WindDataPrepBatchSummary = {
  id: string;
  name: string;
  wind_farm_name: string | null;
  remark: string | null;
  start_lon: number;
  start_lat: number;
  grid_nx: number;
  grid_ny: number;
  grid_step_deg: number;
  risk_base_s: number;
  data_years: number;
  terrain_mode: WindDataPrepTerrainMode | string;
  turbine_count: number;
  lightning_total: number;
  lightning_valid: number;
  lightning_in_scope: number;
  status: WindDataPrepStatus | string;
  stage: string;
  progress: number;
  task_id: string | null;
  error_message: string | null;
  files_ready: number;
  has_report: boolean;
  create_date: string | null;
  update_date: string | null;
  create_user: string | null;
};

export type WindDataPrepBatchDetail = WindDataPrepBatchSummary & {
  turbine_file_name: string;
  lightning_file_name: string;
  terrain_file_name: string | null;
  nonzero_cell_count: number;
  zero_nl_turbine_count: number;
  nl_max: number | null;
  nl_min: number | null;
  nl_avg: number | null;
  report_json: WindDataPrepReport | null;
  stats_json: Record<string, unknown> | null;
  p0abc_header: Record<string, number> & { row_order?: string };
};

export type WindDataPrepBatchListResponse = {
  total: number;
  items: WindDataPrepBatchSummary[];
};

export type WindDataPrepTurbineRow = {
  seq: number;
  turbine_no: string | null;
  lon: number;
  lat: number;
  cell_i: number;
  cell_j: number;
  grid_id: number;
  flash_count: number;
  flash_count_east: number;
  nl: number;
  density_per_km2_year: number | null;
  height: number | null;
  blade: number | null;
  motion: number | null;
  circuit: number | null;
};

export type WindDataPrepTurbineListResponse = {
  total: number;
  items: WindDataPrepTurbineRow[];
};

export type WindDataPrepPreviewResponse = {
  turbine_count: number;
  lightning_total: number;
  lightning_valid: number;
  lightning_in_scope: number;
  nonzero_cell_count: number;
  nl_max: number | null;
  nl_min: number | null;
  nl_avg: number | null;
  time_span: string;
  type_distribution: Record<string, number>;
  report: WindDataPrepReport;
  warnings: string[];
  p0abc_header: Record<string, number> & { row_order?: string };
  file_lines: Record<string, number>;
  file_sizes: Record<string, number>;
};

export type WindDataPrepImportResponse = {
  batch_id: string;
  task_id: string | null;
  status: string;
};
