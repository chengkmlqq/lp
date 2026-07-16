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
  // 文件上传
  wave_data_file?: any;
  lightning_data_file?: any;
  traveling_wave_file?: any;
  optical_data_file?: any;
}
