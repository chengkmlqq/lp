import type { ReactNode } from "react";

export interface FaultAnalysis {
  id: string;
  title: string;
  description: string;
  status: "pending" | "processing" | "completed" | "failed";
  risk_level: "low" | "medium" | "high" | "critical";
  tower_count: number;
  line_name: string;
  fault_time: string;
  fault_type: string;
  confidence: number;
  progress: number;
  created_at: string;
  updated_at: string;
  created_by?: string;
}

/** 故障分析临时上传文件条目（LP-369：选择文件后先传到临时目录，提交时携带 temp_file_id）。 */
export interface FaultAnalysisTempFile {
  uid: string;
  name: string;
  status: "uploading" | "done" | "error";
  percent: number;
  temp_file_id?: string;
  error?: string;
}
/** 故障分析详情动态选项卡项（LP-275：多开详情 Tab 支持） */
export interface DetailTabItem {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
}

export interface FaultAnalysisDetail extends FaultAnalysis {
  line_id: string;
  analysis_type: string;
  parameters?: Record<string, unknown>;
  results?: Record<string, unknown>;
}

export interface CreateFaultAnalysisFormValues {
  title?: string;
  description?: string;
  line_id: string;
  analysis_type?: string;
  parameters?: Record<string, unknown>;
  // 故障信息
  station_name?: string;
  fault_time?: string;
  fault_line_name?: string;
  fault_phase?: string;
  fault_duration?: number;
  reclosure_status?: string;
  fault_voltage?: number;
  fault_current?: number;
  max_zero_current?: number;
  zero_compensation?: number;
  fault_resistance?: number;
  line_length?: number;
  line_angle?: number;
  line_impedance?: number;
  lightning_current?: string;
  lightning_longitude?: number;
  lightning_latitude?: number;
  wave_distance?: number;
  traveling_wave_distance?: number;
  optical_position?: string;
  optical_device_location?: string;
  // 临时文件上传（LP-369：选择文件后立即上传到临时目录，携带 temp_file_id）
  wave_data_file?: FaultAnalysisTempFile[];
  lightning_data_file?: FaultAnalysisTempFile[];
  ledger_data_file?: FaultAnalysisTempFile[];
  traveling_wave_file?: FaultAnalysisTempFile[];
  optical_data_file?: FaultAnalysisTempFile[];
  auto_classify_files?: FaultAnalysisTempFile[];
}
