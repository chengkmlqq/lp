"use client";

import { useDimensionOptions, type DimensionOption } from "@/hooks/use-dimension-options";

// FL分析创建表单字段 → 维度管理类型 code 的映射
// 与 migrations/seed_fl_analysis_dimensions.sql 中的 dimension_type.code 对齐
export const FL_DIMENSION_FIELD_TO_TYPE_CODE = {
  job_type: "fl_analysis_job_type",
  current_waveform: "current_waveform",
  flashover_method: "flashover_method",
  altitude_correction: "altitude_correction",
} as const;

export type FlDimensionField = keyof typeof FL_DIMENSION_FIELD_TO_TYPE_CODE;
export type FlDimensionOption = DimensionOption;

export type FlDimensionLabelMap = Record<FlDimensionField, Map<string, string>>;
export type FlDimensionOptionMap = Record<FlDimensionField, FlDimensionOption[]>;

/**
 * 从维度管理 API 拉取 FL分析相关枚举（job_type / current_waveform / flashover_method / altitude_correction）。
 * 返回每个字段的 optionMap（label/value，供下拉选）与 labelMap（code→name，供展示格式化）。
 * 维度管理不可用（查询失败 / 类型未 seed）时返回空集合，由调用方回退到静态硬编码选项。
 */
export function useFlDimensionOptions() {
  const result = useDimensionOptions(FL_DIMENSION_FIELD_TO_TYPE_CODE);
  return {
    ...result,
    optionMap: result.optionMap as FlDimensionOptionMap,
    labelMap: result.labelMap as FlDimensionLabelMap,
  };
}
