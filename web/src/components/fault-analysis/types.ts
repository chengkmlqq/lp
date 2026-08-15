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
  created_at: string;
  updated_at: string;
  created_by?: string;
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
  // 文件上传（antd Upload fileList）
  wave_data_file?: { originFileObj: File; name?: string }[];
  lightning_data_file?: { originFileObj: File; name?: string }[];
  ledger_data_file?: { originFileObj: File; name?: string }[];
  traveling_wave_file?: { originFileObj: File; name?: string }[];
  optical_data_file?: { originFileObj: File; name?: string }[];
  // 自动识别类别上传（后端按文件名前缀归类）
  auto_classify_files?: { originFileObj: File; name?: string }[];
}
