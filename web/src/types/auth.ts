export type UserPublic = {
  id: string;
  email: string;
  username: string;
  status: string;
  role_codes: string[];
  permission_codes: string[];
  created_at: string;
  last_login_at: string | null;
  avatar_url: string | null;
};

export type AuthTokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserPublic;
};

export type UserListResponse = {
  items: UserPublic[];
  total: number;
};

export type PermissionItem = {
  id: number;
  code: string;
  name: string;
};

export type RoleItem = {
  id: string;
  code: string;
  name: string;
  permission_codes: string[];
  menu_ids: string[];
};

export type RoleListResponse = {
  items: RoleItem[];
  total: number;
};

export type MenuItem = {
  id: string;
  code: string;
  name: string;
  path: string | null;
  icon: string | null;
  parent_id: string | null;
  type: string;
  sort_order: number;
  status: string;
  visible: boolean;
  cacheable: boolean;
  component: string | null;
  permission_code: string | null;
};

export type MenuTreeItem = MenuItem & {
  children: MenuTreeItem[];
};

export type MenuListResponse = {
  items: MenuItem[];
  total: number;
};

export type AuditLogItem = {
  id: number;
  user_id: string | null;
  username: string | null;
  action: string;
  detail: string | null;
  output: string | null;
  created_at: string;
};

export type AuditLogListResponse = {
  items: AuditLogItem[];
  total: number;
  limit: number;
  offset: number;
};

export type SystemParamStatus = "enabled" | "disabled";

export type ParamCategoryTreeItem = {
  id: number;
  name: string;
  parent_id: number | null;
  sort_order: number;
  children: ParamCategoryTreeItem[];
};

export type SystemParamSummary = {
  id: number;
  param_key: string;
  param_name: string;
  param_value: string;
  description: string | null;
  status: SystemParamStatus;
  category_id: number | null;
  created_by_user_id: string | null;
  updated_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  created_by: UserPublic | null;
  updated_by: UserPublic | null;
};

export type SystemParamListResponse = {
  items: SystemParamSummary[];
  total: number;
};

export type SystemMessageType = "info" | "warning" | "error" | "success";

export type SystemMessageSummary = {
  id: string;
  title: string;
  content: string;
  message_type: SystemMessageType;
  target_user_id: string | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
};

export type SystemMessageListResponse = {
  items: SystemMessageSummary[];
  total: number;
  unread_count: number;
};

export type ScheduledTaskStatus = "idle" | "queued" | "running" | "success" | "failed" | "disabled";
export type ScheduledTaskType = "syslog_cleanup";

export type ScheduledTaskSummary = {
  id: number;
  task_key: string;
  name: string;
  task_type: ScheduledTaskType;
  description: string | null;
  cron_expression: string;
  timezone: string;
  retain_days: number;
  enabled: boolean;
  status: ScheduledTaskStatus;
  last_run_at: string | null;
  next_run_at: string | null;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  last_result_json: Record<string, unknown>;
  run_count: number;
  create_user: string | null;
  update_user: string | null;
  create_date: string;
  update_date: string;
  creator: UserPublic | null;
  updater: UserPublic | null;
};

export type ScheduledTaskListResponse = {
  items: ScheduledTaskSummary[];
  total: number;
};

export type ScheduledTaskRunResponse = {
  success: boolean;
  task: ScheduledTaskSummary;
  celery_task_id: string | null;
};

export type FileStorageDriverType = "VFS" | "S3";

export type FileStorageBackendSummary = {
  id: number;
  code: string;
  name: string;
  driver_type: FileStorageDriverType;
  status: string;
  is_default: boolean;
  config_summary: Record<string, unknown>;
};

export type FileStorageMount = {
  id: number;
  code: string;
  name: string;
  mount_path: string;
  root_path: string;
  is_enabled: boolean;
  backend: FileStorageBackendSummary;
};

export type FileBreadcrumbItem = {
  name: string;
  path: string;
};

export type FileEntryItem = {
  id: number;
  path: string;
  parent_path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mime_type: string | null;
  etag: string | null;
  storage_key: string | null;
  modified_at: string | null;
  synced_at: string;
};

export type FileListResponse = {
  mounts: FileStorageMount[];
  current_mount: FileStorageMount;
  current_path: string;
  breadcrumbs: FileBreadcrumbItem[];
  items: FileEntryItem[];
  total: number;
  synced_at: string;
};

export type FileOperationResponse = {
  success: boolean;
  mount_code: string;
  path: string;
  action: string | null;
  target_path: string | null;
};

export type ElevationDatasetStatus = "active" | "disabled";
export type ElevationDatasetUsageStatus = "idle" | "in_use";
export type ElevationDatasetTerrainStatus = "pending" | "processing" | "ready" | "failed" | "not_supported";
export type ElevationApplyMode = "fill_null_only" | "overwrite_all";
export type ElevationApplyJobStatus = "pending" | "running" | "success" | "failed";
export type ElevationDataImportJobStatus = "pending" | "running" | "success" | "failed";

export type ElevationTerrainBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type ElevationDatasetSummary = {
  id: string;
  code: string;
  name: string;
  source: string | null;
  file_format: string;
  mount_code: string;
  dataset_dir: string;
  file_path: string;
  resolution_m: number | null;
  status: ElevationDatasetStatus;
  usage_status: ElevationDatasetUsageStatus;
  sample_count: number;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  analysis_task_id: string | null;
  analysis_status: string;
  analysis_error_message: string | null;
  analysis_started_at: string | null;
  analysis_finished_at: string | null;
  terrain_status: ElevationDatasetTerrainStatus;
  terrain_task_id: string | null;
  terrain_error_message: string | null;
  terrain_root_path: string | null;
  terrain_url_template: string | null;
  terrain_min_zoom: number | null;
  terrain_max_zoom: number | null;
  terrain_bounds: ElevationTerrainBounds | null;
  terrain_metadata: Record<string, unknown> | null;
  notes: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type ElevationFileRecordSummary = {
  id: string;
  file_name: string;
  file_path: string;
  file_format: string;
  file_size: number;
  source: string | null;
  mount_code: string;
  resolution_m: number | null;
  status: ElevationDatasetStatus;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  sample_count: number;
  analysis_task_id: string | null;
  analysis_status: string;
  analysis_error_message: string | null;
  analysis_started_at: string | null;
  analysis_finished_at: string | null;
  terrain_status: ElevationDatasetTerrainStatus;
  terrain_task_id: string | null;
  terrain_error_message: string | null;
  terrain_root_path: string | null;
  terrain_url_template: string | null;
  terrain_min_zoom: number | null;
  terrain_max_zoom: number | null;
  terrain_bounds: ElevationTerrainBounds | null;
  terrain_metadata: Record<string, unknown> | null;
  notes: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type ElevationFileRecordListResponse = {
  items: ElevationFileRecordSummary[];
  total: number;
};

export type ElevationFileRecordPreviewResponse = {
  record: ElevationFileRecordSummary;
  preview_mode: "point_cloud";
  total_points: number;
  sampled_points: number;
  points: ElevationDatasetPreviewPoint[];
  cells: ElevationDatasetPreviewCell[];
  diagnostics: ElevationDatasetPreviewDiagnostics | null;
  warnings: string[];
};

export type ElevationFileRecordTaskResponse = {
  record: ElevationFileRecordSummary;
  task_id: string | null;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

export type ElevationDatasetListResponse = {
  items: ElevationDatasetSummary[];
  total: number;
};

export type ElevationDatasetAnalyzeResponse = {
  dataset: ElevationDatasetSummary;
  task_id: string | null;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

export type ElevationDatasetTerrainBuildResponse = {
  dataset: ElevationDatasetSummary;
  task_id: string | null;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

export type TowerModelSummary = {
  id: string;
  code: string;
  name: string;
  tower_type: string | null;
  description: string | null;
  image_mount_code: string | null;
  image_path: string | null;
  source_tag: string | null;
  is_enabled: boolean;
  sort_order: number;
  default_altitude_m: number | null;
  default_terrain: string | null;
  default_ground_resistance_ohm: number | null;
  default_lightning_density: number | null;
  default_span_small_m: number | null;
  default_span_large_m: number | null;
  default_slope_1: number | null;
  default_slope_2: number | null;
  default_risk_level: string | null;
  default_raw_json: Record<string, unknown>;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type TowerModelListResponse = {
  items: TowerModelSummary[];
  total: number;
};

export type TowerModelImageUploadResponse = {
  model: TowerModelSummary;
  mount_code: string;
  image_path: string;
};

export type TowerModelSeedResponse = {
  total_models: number;
  imported_models: number;
  updated_models: number;
  skipped_models: number;
  copied_images: number;
  warnings: string[];
};

export type ElevationDatasetBatchImportResponse = {
  imported_count: number;
  analyzed_count: number;
  skipped_count: number;
  warning_count: number;
  warnings: string[];
  items: ElevationDatasetSummary[];
};

export type ElevationDatasetDataImportResponse = {
  job: ElevationDataImportJobSummary;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

export type ElevationDatasetFileItem = {
  path: string;
  name: string;
  size: number;
  modified_at: string | null;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  mime_type: string | null;
};

export type ElevationDatasetFileListResponse = {
  dataset_id: string;
  dataset_code: string;
  dataset_dir: string;
  mount_code: string;
  items: ElevationDatasetFileItem[];
  total: number;
};

export type ElevationDatasetAnalysisTaskStatus =
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "unknown"
  | "not_found";

export type ElevationDatasetAnalysisTaskStatusResponse = {
  dataset_id: string;
  dataset_code: string;
  task_id: string | null;
  status: ElevationDatasetAnalysisTaskStatus;
  detail: string | null;
  started_at: string | null;
  finished_at: string | null;
  update_date: string | null;
};

export type ElevationDatasetTerrainTaskStatusResponse = {
  dataset_id: string;
  dataset_code: string;
  task_id: string | null;
  status: ElevationDatasetAnalysisTaskStatus;
  detail: string | null;
  terrain_url_template: string | null;
  terrain_min_zoom: number | null;
  terrain_max_zoom: number | null;
  update_date: string | null;
};

export type ElevationDatasetPreviewPoint = {
  longitude: number;
  latitude: number;
  altitude_m: number;
};

export type ElevationDatasetPreviewCell = {
  min_longitude: number;
  max_longitude: number;
  min_latitude: number;
  max_latitude: number;
  altitude_m: number;
};

export type ElevationDatasetPreviewDiagnostics = {
  source_crs: string | null;
  source_bounds_min_x: number | null;
  source_bounds_max_x: number | null;
  source_bounds_min_y: number | null;
  source_bounds_max_y: number | null;
  wgs84_bounds_min_lon: number | null;
  wgs84_bounds_max_lon: number | null;
  wgs84_bounds_min_lat: number | null;
  wgs84_bounds_max_lat: number | null;
  raster_width: number | null;
  raster_height: number | null;
  target_samples: number | null;
  sampling_step: number | null;
  scanned_candidates: number | null;
  valid_preview_count: number | null;
  skip_read_error: number;
  skip_masked: number;
  skip_nodata: number;
  skip_nonfinite: number;
  skip_sample_transform_error: number;
  sample_tx_first_error: string | null;
  skip_sample_out_of_range: number;
  skip_cell_transform_error: number;
  skip_cell_out_of_range: number;
};

export type ElevationDatasetPreviewResponse = {
  dataset: ElevationDatasetSummary;
  preview_mode: "point_cloud";
  total_points: number;
  sampled_points: number;
  points: ElevationDatasetPreviewPoint[];
  cells: ElevationDatasetPreviewCell[];
  diagnostics: ElevationDatasetPreviewDiagnostics | null;
  warnings: string[];
};

export type ElevationApplyJobSummary = {
  id: string;
  line_id: string;
  line_code: string | null;
  line_name: string | null;
  file_record_id: string | null;
  file_record_name: string | null;
  dataset_id: string | null;
  dataset_code: string | null;
  dataset_name: string | null;
  mode: ElevationApplyMode;
  status: ElevationApplyJobStatus;
  task_id: string | null;
  total_tower_count: number;
  updated_tower_count: number;
  skipped_tower_count: number;
  missing_geo_count: number;
  unmatched_count: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type ElevationApplyJobListResponse = {
  items: ElevationApplyJobSummary[];
  total: number;
};

export type ElevationApplyJobCreateResponse = {
  job: ElevationApplyJobSummary;
  queued: boolean;
};

export type ElevationDataImportJobSummary = {
  id: string;
  dataset_id: string;
  dataset_code: string | null;
  dataset_name: string | null;
  status: ElevationDataImportJobStatus;
  task_id: string | null;
  progress_percent: number;
  current_stage: string | null;
  detail_message: string | null;
  trigger_analysis: boolean;
  analysis_task_queued: boolean;
  analysis_task_id: string | null;
  uploaded_file_count: number;
  extracted_file_count: number;
  imported_file_count: number;
  warning_count: number;
  warnings: string[];
  imported_files: string[];
  started_at: string | null;
  finished_at: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type ElevationDataImportJobListResponse = {
  items: ElevationDataImportJobSummary[];
  total: number;
};

export type LineSummary = {
  id: string;
  code: string;
  name: string;
  voltage_kv: number | null;
  phase_sequence_json: Record<string, unknown>;
  arrester_install_json: Record<string, unknown>;
  lightning_param_json: Record<string, unknown>;
  preparation_json: Record<string, unknown>;
  tower_count: number;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type LineListResponse = {
  items: LineSummary[];
  total: number;
};

export type LineTowerSummary = {
  id: string;
  line_id: string;
  seq_no: number;
  tower_no: string;
  tower_model: string | null;
  tower_type: string | null;
  longitude: number | null;
  latitude: number | null;
  altitude_m: number | null;
  terrain: string | null;
  ground_resistance_ohm: number | null;
  lightning_density: number | null;
  span_small_m: number | null;
  span_large_m: number | null;
  slope_1: number | null;
  slope_2: number | null;
  risk_level: string | null;
  circuit_geometry_json: Record<string, unknown>;
  lightning_result_json: Record<string, unknown>;
  raw_extra_json: Record<string, unknown>;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type LineTowerListResponse = {
  items: LineTowerSummary[];
  total: number;
};

export type LineTowerImportResponse = {
  line: LineSummary;
  imported_count: number;
  updated_count: number;
  skipped_count: number;
  warning_count: number;
  warnings: string[];
};

export type TowerProfileDetail = {
  id: string | null;
  tower_id: string;
  line_id: string;
  tower_no: string;
  seq_no: number;
  tower_model: string | null;
  tower_type: string | null;
  profile_exists: boolean;
  phase_sequence_1: string | null;
  phase_sequence_2: string | null;
  phase_sequence_3: string | null;
  phase_sequence_4: string | null;
  arrester_a: string | null;
  arrester_b: string | null;
  arrester_c: string | null;
  protection_angle_left_deg: number | null;
  protection_angle_right_deg: number | null;
  shield_wire_height_m: number | null;
  insulator_length_m: number | null;
  call_height_m: number | null;
  angle_deg: number | null;
  current_a: number | null;
  current_b: number | null;
  structure_kind: string | null;
  stroke_mode: string | null;
  current_type: string | null;
  current_head_time_us: number | null;
  current_tail_time_us: number | null;
  geometry_layers_json: Record<string, unknown>;
  extra_profile_json: Record<string, unknown>;
  create_date: string | null;
  create_user: string | null;
  update_date: string | null;
  update_user: string | null;
};

export type FlAnalysisRunSummary = {
  id: string;
  job_id: string;
  status: string;
  runner_kind: string;
  engine_command: string | null;
  working_dir: string | null;
  error_message: string | null;
  snapshot_tower_count: number;
  result_tower_count: number;
  duration_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type FlAnalysisJobSummary = {
  id: string;
  line_id: string;
  line_code: string | null;
  line_name: string | null;
  job_name: string | null;
  job_type: string;
  source_kind: string;
  status: string;
  task_id: string | null;
  latest_run_id: string | null;
  total_tower_count: number;
  snapshotted_tower_count: number;
  result_tower_count: number;
  external_adapter: string;
  adapter_config_json: Record<string, unknown>;
  execution_options_json: Record<string, unknown>;
  result_summary_json: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type FlAnalysisJobDetail = FlAnalysisJobSummary & {
  runs: FlAnalysisRunSummary[];
};

export type FlAnalysisJobListResponse = {
  items: FlAnalysisJobSummary[];
  total: number;
};

export type FlAnalysisTowerResultSummary = {
  id: string;
  job_id: string;
  run_id: string;
  snapshot_id: string;
  tower_id: string;
  seq_no: number;
  tower_no: string;
  tower_model: string | null;
  tower_type: string | null;
  status: string;
  risk_level: string | null;
  summary_text: string | null;
  result_json: Record<string, unknown>;
  create_date: string;
  update_date: string;
};

export type FlAnalysisTowerResultListResponse = {
  items: FlAnalysisTowerResultSummary[];
  total: number;
};

export type FaultAnalysisStatus = "pending" | "processing" | "completed" | "failed";

export type FaultAnalysisSummary = {
  id: string;
  title: string | null;
  description: string | null;
  line_id: string | null;
  line_name: string | null;
  status: FaultAnalysisStatus | string;
  risk_level: string | null;
  fault_time: string | null;
  fault_type: string | null;
  fault_phase: string | null;
  confidence: number | null;
  station: string | null;
  lightning_current_ka: number | null;
  wave_distance_km: number | null;
  traveling_wave_distance_km: number | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type FaultAnalysisDetail = FaultAnalysisSummary & {
  fault_duration_ms: number | null;
  reclosure_status: string | null;
  fault_voltage_v: number | null;
  fault_current_a: number | null;
  max_zero_current_a: number | null;
  zero_compensation: number | null;
  fault_resistance_ohm: number | null;
  line_length_km: number | null;
  line_angle_deg: number | null;
  line_impedance_ohm: number | null;
  lightning_longitude: number | null;
  lightning_latitude: number | null;
  optical_position: string | null;
  optical_device_location: string | null;
  result_json: Record<string, unknown>;
};

export type FaultAnalysisListResponse = {
  items: FaultAnalysisSummary[];
  total: number;
};

export type FaultAnalysisCreateResponse = {
  analysis: FaultAnalysisDetail;
};

export type FaultRecurrenceStrokeMode = "counterstroke" | "shielding";
export type FaultRecurrenceResultStatus = "matched" | "no_need";

export type FaultRecurrenceDataPoint = {
  head_time_us: number;
  tail_time_us: number;
  counterstroke_withstand_ka: number;
  shielding_withstand_ka: number;
};

export type FaultRecurrenceResult = {
  status: FaultRecurrenceResultStatus;
  message: string;
  head_time_us: number | null;
  tail_time_us: number | null;
  probability_density: number | null;
};

export type FaultRecurrenceAnalyzeResponse = {
  curve_no: number;
  curve_label: string;
  stroke_mode: FaultRecurrenceStrokeMode;
  stroke_label: string;
  withstand_level_ka: number;
  source_file_name: string;
  source_mode: string;
  point_count: number;
  reference_counterstroke_ka: number;
  reference_shielding_ka: number;
  reference_point_found: boolean;
  warnings: string[];
  data_points: FaultRecurrenceDataPoint[];
  result: FaultRecurrenceResult;
};

export type AtpModelStatus = "enabled" | "disabled";
export type AtpModelSourceType = "atpdraw" | "atp" | "manual";
export type AtpModelVersionStatus = "draft" | "released" | "archived";
export type AtpSimulationRunStatus = "pending" | "running" | "success" | "failed";
export type AtpEngineMode = "wine" | "native";

export type AtpModelSummary = {
  id: string;
  code: string;
  name: string;
  source_type: AtpModelSourceType;
  description: string;
  status: AtpModelStatus;
  tags_json: string[];
  latest_version_no: number;
  active_version_no: number | null;
  version_count: number;
  run_count: number;
  last_run_status: AtpSimulationRunStatus | null;
  last_run_date: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type AtpModelListResponse = {
  items: AtpModelSummary[];
  total: number;
};

export type AtpModelVersionSummary = {
  id: string;
  model_id: string;
  version_no: number;
  version_tag: string | null;
  status: AtpModelVersionStatus;
  entry_file: string | null;
  change_note: string;
  artifact_manifest_json: Record<string, unknown>;
  content_hash: string;
  atp_text_size: number;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type AtpModelVersionDetail = AtpModelVersionSummary & {
  atp_text: string;
  graph_json: Record<string, unknown>;
};

export type AtpModelVersionListResponse = {
  items: AtpModelVersionSummary[];
  total: number;
};

export type AtpSimulationRunSummary = {
  id: string;
  model_id: string;
  version_id: string | null;
  version_no: number | null;
  task_id: string | null;
  status: AtpSimulationRunStatus;
  engine_mode: AtpEngineMode;
  engine_command: string | null;
  working_dir: string | null;
  timeout_seconds: number;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  stdout_size: number;
  stderr_size: number;
  create_date: string;
  create_user: string | null;
};

export type AtpSimulationRunDetail = AtpSimulationRunSummary & {
  stdout_text: string | null;
  stderr_text: string | null;
};

export type AtpSimulationRunListResponse = {
  items: AtpSimulationRunSummary[];
  total: number;
};

export type AtpEngineStatusResponse = {
  mode: AtpEngineMode;
  available: boolean;
  executable_path: string;
  resolved_executable: string | null;
  storage_root: string;
  workdir: string;
  default_timeout_seconds: number;
  max_timeout_seconds: number;
  error: string | null;
};

export type AtpAssetStatus = "draft" | "enabled" | "disabled" | "archived";
export type AtpAssetReleaseStatus = "draft" | "released" | "archived";
export type AtpAssetRunnerKind = "atp" | "egm" | "hybrid";
export type AtpAssetRunStatus = "pending" | "running" | "success" | "failed";

export type AtpAssetSummary = {
  id: string;
  code: string;
  name: string;
  description: string;
  status: AtpAssetStatus;
  voltage_level: string | null;
  tower_type: string | null;
  scene_type: string | null;
  arrester_config: string | null;
  storage_mount_code: string | null;
  storage_root_path: string | null;
  latest_release_no: number;
  active_release_no: number | null;
  active_release_id: string | null;
  active_release_tag: string | null;
  release_count: number;
  run_count: number;
  last_run_status: AtpAssetRunStatus | null;
  last_run_date: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type AtpAssetListResponse = {
  items: AtpAssetSummary[];
  total: number;
};

export type AtpAssetReleaseSummary = {
  id: string;
  asset_id: string;
  asset_code: string;
  asset_name: string;
  release_no: number;
  release_tag: string | null;
  status: AtpAssetReleaseStatus;
  voltage_level: string;
  tower_type: string;
  scene_type: string;
  scenario_code: string | null;
  runner_kind: AtpAssetRunnerKind;
  storage_mount_code: string;
  storage_root_path: string;
  entry_file: string | null;
  result_file: string | null;
  egm_subdir: string | null;
  egm_result_file: string | null;
  preprocess_script: string | null;
  postprocess_script: string | null;
  content_hash: string;
  is_active: boolean;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type AtpAssetReleaseDetail = AtpAssetReleaseSummary & {
  manifest_json: Record<string, unknown>;
  validation_json: Record<string, unknown>;
};

export type AtpAssetReleaseListResponse = {
  items: AtpAssetReleaseSummary[];
  total: number;
};

export type AtpAssetFileEntry = {
  relative_path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mime_type: string | null;
  file_role: string | null;
};

export type AtpAssetFileListResponse = {
  asset_id: string;
  release_id: string | null;
  storage_mount_code: string;
  storage_root_path: string;
  items: AtpAssetFileEntry[];
  total: number;
};

export type AtpAssetFileUploadResponse = {
  asset_id: string;
  storage_mount_code: string;
  storage_root_path: string;
  uploaded_count: number;
  success: boolean;
};

export type AtpAssetRunSummary = {
  id: string;
  asset_id: string;
  asset_code: string;
  asset_name: string;
  release_id: string;
  release_no: number;
  release_tag: string | null;
  status: AtpAssetRunStatus;
  engine_mode: AtpEngineMode;
  runner_kind: AtpAssetRunnerKind;
  task_id: string | null;
  storage_mount_code: string | null;
  storage_root_path: string | null;
  materialized_root_path: string | null;
  engine_command: string | null;
  working_dir: string | null;
  timeout_seconds: number;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  stdout_size: number;
  stderr_size: number;
  create_date: string;
  create_user: string | null;
};

export type AtpAssetRunDetail = AtpAssetRunSummary & {
  stdout_text: string | null;
  stderr_text: string | null;
  output_manifest_json: Record<string, unknown>;
  result_summary_json: Record<string, unknown>;
};

export type AtpAssetRunListResponse = {
  items: AtpAssetRunSummary[];
  total: number;
};

export type LightningPolarity = "positive" | "negative" | "mixed" | "unknown";

export type LightningCurrentEventSummary = {
  id: string;
  event_id: string;
  source_file_name: string | null;
  event_time: string | null;
  sample_count: number;
  sample_interval_us: number | null;
  sampling_frequency_hz: number | null;
  peak_current_ka: number | null;
  peak_abs_current_ka: number | null;
  wavefront_time_t1_us: number | null;
  half_value_time_t2_us: number | null;
  steepness_ka_per_us: number | null;
  action_integral_j_ohm: number | null;
  wave_shape: string | null;
  polarity: LightningPolarity;
  stroke_count: number;
  stroke_peaks_json: Array<Record<string, unknown>>;
  region_id: string | null;
  location_tag: string | null;
  city: string | null;
  longitude: number | null;
  latitude: number | null;
  altitude_m: number | null;
  sensor_model: string | null;
  install_position: string | null;
  weather_level: string | null;
  pressure_hpa: number | null;
  humidity_percent: number | null;
  is_synthetic: boolean;
  feature_json: Record<string, unknown>;
  notes: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

export type LightningCurrentEventListResponse = {
  items: LightningCurrentEventSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type LightningCurrentImportResponse = {
  imported_count: number;
  skipped_count: number;
  warning_count: number;
  warnings: string[];
  task_id: string | null;
};

export type LightningCurrentPreparationResponse = {
  line: LineSummary;
  current_a: number;
  current_b: number;
  sampled_event_count: number;
  updated_tower_count: number;
  created_profile_count: number;
  warning_count: number;
  warnings: string[];
};

export type LightningDensityPreparationResponse = {
  line: LineSummary;
  updated_tower_count: number;
  missing_geo_count: number;
  radius_km: number;
  data_years: number;
  avg_density: number | null;
  min_density: number | null;
  max_density: number | null;
  warning_count: number;
  warnings: string[];
};

export type LightningCurrentSampleItem = {
  id: number;
  event_ref_id: string;
  seq_no: number;
  time_us: number;
  current_ka: number;
};

export type LightningCurrentSampleListResponse = {
  items: LightningCurrentSampleItem[];
  total: number;
  limit: number;
  offset: number;
};

export type LightningCurrentExceedancePoint = {
  threshold_ka: number;
  exceedance_probability: number;
  exceedance_count: number;
};

export type LightningCurrentExceedanceResponse = {
  total_events: number;
  thresholds: LightningCurrentExceedancePoint[];
};

export type LightningDistributionRecordSummary = {
  id: string;
  file_name: string | null;
  city: string | null;
  longitude: number | null;
  latitude: number | null;
  year: number | null;
  region_id: string | null;
  notes: string | null;
  is_synthetic: boolean;
  total_points: number;
  create_date: string;
  create_user: string | null;
};

export type LightningDistributionImportResponse = {
  record: LightningDistributionRecordSummary;
  imported_count: number;
  skipped_count: number;
  warning_count: number;
  warnings: string[];
  line_id: string | null;
  task_id: string | null;
};

export type LightningDistributionSummary = {
  total_records: number;
  area_km2: number;
  data_years: number;
  grid_size_km: number;
  overall_ng_per_km2_year: number;
  max_abs_current_ka: number | null;
  avg_abs_current_ka: number | null;
};

export type LightningPolarityStats = {
  positive_count: number;
  negative_count: number;
  mixed_count: number;
  unknown_count: number;
  positive_ratio: number;
  negative_ratio: number;
};

export type LightningSourceStats = {
  measured_count: number;
  synthetic_count: number;
};

export type LightningDistributionGridCell = {
  grid_x: number;
  grid_y: number;
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
  center_lat: number;
  center_lon: number;
  strike_count: number;
  ng_per_km2_year: number;
  i_max_ka: number | null;
  i_avg_ka: number | null;
  positive_ratio: number;
};

export type LightningDistributionScatterPoint = {
  id: string;
  event_id: string;
  longitude: number;
  latitude: number;
  current_ka: number | null;
  abs_current_ka: number | null;
  polarity: LightningPolarity;
  region_id: string | null;
  city: string | null;
  location_tag: string | null;
  event_time: string | null;
};

export type LightningDistributionStatsResponse = {
  summary: LightningDistributionSummary;
  polarity: LightningPolarityStats;
  sources: LightningSourceStats;
  grid_cells: LightningDistributionGridCell[];
  scatter_points: LightningDistributionScatterPoint[];
  p_curve: LightningCurrentExceedancePoint[];
};

export type LightningImportBatchSummary = {
  batch_id: string;
  source_file_name: string | null;
  import_time: string;
  event_count: number;
  region_id: string | null;
  location_tag: string | null;
  city: string | null;
  event_year: number | null;
  is_synthetic: boolean;
  notes: string | null;
  line_id: string | null;
  line_name: string | null;
  status: string | null;
  task_id: string | null;
  max_abs_current_ka: number | null;
  avg_abs_current_ka: number | null;
  positive_count: number;
  negative_count: number;
  create_user: string | null;
};

export type LightningImportBatchListResponse = {
  items: LightningImportBatchSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type LightningImportBatchEventItem = {
  id: string;
  event_id: string;
  longitude: number | null;
  latitude: number | null;
  current_ka: number | null;
  abs_current_ka: number | null;
  polarity: LightningPolarity;
  event_time: string | null;
};

export type LightningImportBatchEventsResponse = {
  batch_id: string;
  source_file_name: string | null;
  import_time: string;
  events: LightningImportBatchEventItem[];
  total: number;
};

export type LightningTowerBufferEventItem = {
  id: string;
  event_id: string;
  longitude: number | null;
  latitude: number | null;
  current_ka: number | null;
  abs_current_ka: number | null;
  polarity: LightningPolarity;
  event_time: string | null;
  location_tag: string | null;
  city: string | null;
  distance_km: number;
};

export type LightningTowerTerrainMetrics = {
  slope_deg: number | null;
  aspect_deg: number | null;
  slope_mean_deg: number | null;
  slope_p95_deg: number | null;
  slope_max_deg: number | null;
  slope_along_line_deg: number | null;
  slope_cross_line_deg: number | null;
  relief_m_50: number | null;
  dem_source: string | null;
  dem_resolution_m: number | null;
  quality_score: number | null;
  quality_level: string | null;
  terrain_exposure_index: number | null;
  windward_factor: number | null;
  algorithm_version: string | null;
  computed_at: string | null;
  land_cover_type: string | null;
};

export type LightningTowerBufferStatsResponse = {
  tower_id: string | null;
  tower_no: string | null;
  line_id: string | null;
  center_longitude: number;
  center_latitude: number;
  radius_km: number;
  design_current_ka: number;
  strike_count: number;
  exceed_design_count: number;
  max_abs_current_ka: number | null;
  avg_abs_current_ka: number | null;
  ng_per_km2_year: number;
  positive_ratio: number;
  risk_level: string;
  recommended_action: string;
  events: LightningTowerBufferEventItem[];
  terrain_metrics: LightningTowerTerrainMetrics | null;
};

export type LightningTowerTerrainComputeRequest = {
  tower_id?: string | null;
  longitude?: number | null;
  latitude?: number | null;
  altitude_m?: number | null;
  dem_grid_m: number[][];
  cell_size_m?: number;
  search_radius_m?: number;
  dem_source?: string | null;
  dem_resolution_m?: number | null;
  wind_direction_deg?: number | null;
  land_cover_type?: string | null;
  persist?: boolean;
};

export type LightningTowerTerrainComputeResponse = {
  tower_id: string | null;
  tower_no: string | null;
  line_id: string | null;
  center_longitude: number;
  center_latitude: number;
  method: string;
  persisted: boolean;
  terrain_metrics: LightningTowerTerrainMetrics;
  warnings: string[];
};

export type LightningSyntheticDatasetStats = {
  count: number;
  max_abs_current_ka: number | null;
  avg_abs_current_ka: number | null;
  positive_ratio: number;
  ng_per_km2_year: number;
};

export type LightningSyntheticCompareResponse = {
  grid_size_km: number;
  data_years: number;
  measured: LightningSyntheticDatasetStats;
  synthetic: LightningSyntheticDatasetStats;
  grid_cosine_similarity: number | null;
  note: string | null;
};

export type LightningDistributionEventBrief = {
  id: string;
  event_id: string;
  longitude: number | null;
  latitude: number | null;
  current_ka: number | null;
  abs_current_ka: number | null;
  polarity: LightningPolarity;
  event_time: string | null;
  location_tag: string | null;
  city: string | null;
};

export type LightningDistributionReportResponse = {
  period: "week" | "month";
  start_time: string;
  end_time: string;
  strike_count: number;
  max_abs_current_ka: number | null;
  avg_abs_current_ka: number | null;
  positive_ratio: number;
  ng_per_km2_year: number;
  most_severe_event: LightningDistributionEventBrief | null;
};

export type LightningDensityStatus = "pending" | "running" | "completed" | "failed";

export type ZoneStatsItem = {
  group_id: number;
  lon: number;
  lat: number;
  tower_count?: number;
  strike_count: number;
  area_km2: number;
  density_per_km2: number;
};

export type LightningDensityResultSummary = {
  id: string;
  status: LightningDensityStatus;
  group_size: number;
  radius_km: number;
  total_strikes: number;
  max_density: number | null;
  total_area_km2: number | null;
  error_message: string | null;
  create_date: string;
  update_date: string;
};

export type LightningDensitySubmitResponse = {
  id: string;
  status: LightningDensityStatus;
  task_id: string | null;
  message: string;
};

export type LightningDensityResultDetail = {
  id: string;
  status: LightningDensityStatus;
  group_size: number;
  radius_km: number;
  zone_stats: ZoneStatsItem[];
  image_base64: string | null;
  csv_content: string | null;
  total_strikes: number;
  max_density: number | null;
  total_area_km2: number | null;
  error_message: string | null;
  create_date: string;
  update_date: string;
};

export type LightningDensityListResponse = {
  items: LightningDensityResultSummary[];
  total: number;
};
