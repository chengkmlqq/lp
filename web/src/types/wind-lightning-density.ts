/** 风电场地闪密度统计（LP-32 独立模块）类型定义。 */

export type WindLightningDensityStatus = "pending" | "processing" | "completed" | "failed";

export type WindLightningDensityYearsSource = "auto" | "fixed";

export type WindLightningDensityBatchSummary = {
  id: string;
  batch_name: string;
  wind_farm_name: string | null;
  notes: string | null;
  status: WindLightningDensityStatus | string;
  stage: string;
  progress: number;
  task_id: string | null;
  error_message: string | null;
  turbine_count: number;
  total_records: number;
  valid_records: number;
  skipped_records: number;
  data_years: number | null;
  years_source: WindLightningDensityYearsSource | string;
  overall_density: number | null;
  peak_density: number | null;
  area_km2: number | null;
  grid_x_count: number;
  grid_y_count: number;
  has_image: boolean;
  create_date: string | null;
  update_date: string | null;
  create_user: string | null;
};

export type WindLightningDensityCoreGrid = {
  start_lon: number;
  start_lat: number;
  x_count: number;
  y_count: number;
  step_deg: number;
};

export type WindLightningDensityBatchDetail = WindLightningDensityBatchSummary & {
  turbine_source_file_name: string;
  lightning_source_file_name: string;
  grid_step_deg: number;
  margin_deg: number;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  peak_lon: number | null;
  peak_lat: number | null;
  stats_json: Record<string, unknown> | null;
  core_grid: WindLightningDensityCoreGrid | null;
  cell_rows_stored: number;
};

export type WindLightningDensityBatchListResponse = {
  total: number;
  items: WindLightningDensityBatchSummary[];
};

export type WindLightningDensityCellRow = {
  cell_i: number;
  cell_j: number;
  center_lon: number;
  center_lat: number;
  min_lon: number;
  max_lon: number;
  min_lat: number;
  max_lat: number;
  strike_count: number;
  density_per_cell_year: number;
  density_per_km2_year: number;
  turbine_count: number;
};

export type WindLightningDensityCellListResponse = {
  total: number;
  items: WindLightningDensityCellRow[];
};

export type WindLightningDensityTurbineRow = {
  seq: number;
  turbine_no: string | null;
  lon: number;
  lat: number;
  cell_i: number;
  cell_j: number;
  cell_density: number;
};

export type WindLightningDensityTurbineListResponse = {
  total: number;
  items: WindLightningDensityTurbineRow[];
};

export type WindLightningDensityPreviewResponse = {
  turbine_count: number;
  turbine_skipped: number;
  total_records: number;
  valid_records: number;
  skipped_records: number;
  in_range_records: number;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  grid_x_count: number;
  grid_y_count: number;
  area_km2: number | null;
  data_years: number | null;
  years_source: string;
  detected_years: number[];
  warnings: string[];
};

export type WindLightningDensityImportResponse = {
  batch_id: string;
  task_id: string | null;
  status: string;
  /** 后端生成的真实批次名（详情 Tab 标题用此值，不用本地草稿名） */
  batch_name: string;
};

export type WindLightningDensityExportType = "cells" | "turbines" | "all";
