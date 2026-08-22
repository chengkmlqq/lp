"use client";

import { Alert, Button, Form, Input, InputNumber, Select, Space, Tag } from "antd";
import type { FormInstance } from "antd";

import { readLinePreparation } from "@/lib/line-preparation";
import type {
  AtpAssetSummary,
  AtpEngineStatusResponse,
  LineSummary,
} from "@/types/auth";

import {
  CREATE_JOB_DEFAULTS,
  formatDateTime,
  formatJobType,
  preparationColor,
  readObject,
  readOptionalNumber,
  readOptionalString,
  type CreateJobFormValues,
} from "./types";
import { useFlDimensionOptions, type FlDimensionOption } from "./use-fl-dimensions";

// 硬编码回退选项（维度管理 API 加载失败时兜底，避免页面功能中断）
// 与 migrations/seed_fl_analysis_dimensions.sql 中维度值 code/name 对齐
const JOB_TYPE_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "normal", label: "普通计算" },
  { value: "tongtiao", label: "同跳计算" },
  { value: "risk", label: "风险评估" },
];
const CURRENT_WAVEFORM_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "heidler", label: "Heidler" },
  { value: "double_slope", label: "双斜角" },
  { value: "double_exponential", label: "双指数" },
];
const FLASHOVER_METHOD_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "guideline", label: "规程法" },
  { value: "intersection", label: "相交法" },
  { value: "leader_development", label: "先导发展法" },
];
const ALTITUDE_CORRECTION_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "none", label: "无" },
  { value: "formula1", label: "推荐公式1" },
  { value: "formula2", label: "推荐公式2" },
];

type CreateJobFormProps = {
  form: FormInstance<CreateJobFormValues>;
  lines: LineSummary[];
  linesLoading: boolean;
  selectedLine: LineSummary | null;
  selectedJobType: CreateJobFormValues["job_type"];
  atpModels: AtpAssetSummary[];
  atpModelsLoading: boolean;
  atpModelsError: unknown;
  selectedAtpModel: AtpAssetSummary | null;
  engineQueryData: AtpEngineStatusResponse | undefined;
  onSubmit: (values: CreateJobFormValues) => void;
};

export function CreateJobForm({
  form,
  lines,
  linesLoading,
  selectedLine,
  selectedJobType,
  atpModels,
  atpModelsLoading,
  atpModelsError,
  selectedAtpModel,
  engineQueryData,
  onSubmit,
}: CreateJobFormProps) {
  const selectedLinePreparation = readLinePreparation(selectedLine);
  const { optionMap, isLoading: dimensionsLoading } = useFlDimensionOptions();
  // 维度管理 API 返回启用项；加载失败时回退到静态选项
  const jobTypeOptions = optionMap.job_type.length > 0 ? optionMap.job_type : JOB_TYPE_FALLBACK_OPTIONS;
  const currentWaveformOptions = optionMap.current_waveform.length > 0
    ? optionMap.current_waveform
    : CURRENT_WAVEFORM_FALLBACK_OPTIONS;
  const flashoverMethodOptions = optionMap.flashover_method.length > 0
    ? optionMap.flashover_method
    : FLASHOVER_METHOD_FALLBACK_OPTIONS;
  const altitudeCorrectionOptions = optionMap.altitude_correction.length > 0
    ? optionMap.altitude_correction
    : ALTITUDE_CORRECTION_FALLBACK_OPTIONS;

  return (
    <Form<CreateJobFormValues>
      form={form}
      layout="vertical"
      initialValues={CREATE_JOB_DEFAULTS}
      onFinish={onSubmit}
    >
      <Form.Item name="job_name" label="任务名">
        <Input
          placeholder={selectedLine
            ? `${selectedLine.name || selectedLine.code}-${formatJobType(selectedJobType)}`
            : `${formatJobType(selectedJobType)}任务`}
        />
      </Form.Item>

      <Form.Item name="job_type" label="任务类型" rules={[{ required: true, message: "请选择任务类型" }]}>
        <Select
          loading={dimensionsLoading}
          options={jobTypeOptions}
        />
      </Form.Item>

      <Form.Item
        name="line_id"
        label="线路"
        rules={[{ required: true, message: "请选择线路" }]}
      >
        <Select
          showSearch
          optionFilterProp="label"
          placeholder="选择线路"
          loading={linesLoading}
          options={lines.map((item) => ({
            value: item.id,
            label: `${item.name || item.code} / ${item.code}`,
          }))}
        />
      </Form.Item>

      {selectedLine ? (
        <Alert
          type={selectedLinePreparation.all_ready ? "success" : "warning"}
          showIcon
          message={selectedLinePreparation.all_ready ? "参数准备已完成" : `当前线路缺少：${selectedLinePreparation.missing_items.join("、")}`}
          description={
            <Space size={[8, 8]} wrap>
              {[
                selectedLinePreparation.lightning_current,
                selectedLinePreparation.lightning_density,
                selectedLinePreparation.ground_slope,
              ].map((item) => {
                const source = readObject(item.source);
                const preparedAt = readOptionalString(source, "prepared_at");
                const currentA = readOptionalNumber(readObject(item.values), "current_a");
                const currentB = readOptionalNumber(readObject(item.values), "current_b");
                const suffix = item.key === "lightning_current" && currentA !== null && currentB !== null
                  ? ` (${currentA.toFixed(3)} / ${currentB.toFixed(3)})`
                  : "";
                return (
                  <Tag key={item.key} color={preparationColor(item.ready)}>
                    {`${item.label}${suffix} ${item.tower_ready_count}/${item.tower_total_count}${preparedAt ? ` @ ${formatDateTime(preparedAt)}` : ""}`}
                  </Tag>
                );
              })}
            </Space>
          }
        />
      ) : null}

      {selectedJobType === "normal" || selectedJobType === "tongtiao" ? (
        <>
          <Alert
            type="info"
            showIcon
            message="默认通过 Wine / ATP 链路执行外部 ATP 模型计算。"
          />
          {atpModelsError ? (
            <Alert
              type="error"
              showIcon
              message={atpModelsError instanceof Error ? atpModelsError.message : "ATP 模型列表加载失败"}
            />
          ) : null}
          <>
            <Form.Item
              name="atp_model_id"
              label="ATP模型"
              rules={[{ required: false, message: "请选择 ATP 模型" }]}
            >
              <Select
                showSearch
                optionFilterProp="label"
                loading={atpModelsLoading}
                placeholder="选择 ATP 模型（可选，不选则走规则近似计算）"
                options={atpModels.map((item) => ({
                  value: item.id,
                  label: `${item.name} / ${item.code}`,
                }))}
              />
            </Form.Item>
            {selectedAtpModel ? (
              <Alert
                type="info"
                showIcon
                message={`执行模式：Wine / ATP`}
                description={`当前模型：${selectedAtpModel.name} / ${selectedAtpModel.code}。执行时默认使用该模型的当前模板。`}
              />
            ) : null}
          </>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="current_waveform" label="雷电流波形">
              <Select
                loading={dimensionsLoading}
                options={currentWaveformOptions}
              />
            </Form.Item>
            <Form.Item name="flashover_method" label="闪络判据">
              <Select
                loading={dimensionsLoading}
                options={flashoverMethodOptions}
              />
            </Form.Item>
            <Form.Item name="altitude_correction" label="海拔修正">
              <Select
                loading={dimensionsLoading}
                options={altitudeCorrectionOptions}
              />
            </Form.Item>
            <Form.Item name="induced_voltage_formula" label="感应电压公式">
              <Select
                options={[
                  { value: "formula1", label: "公式1" },
                  { value: "formula2", label: "公式2" },
                ]}
              />
            </Form.Item>
            <Form.Item name="head_time_min_us" label="波头时间最小(μs)">
              <InputNumber min={0.1} step={0.1} precision={2} className="w-full" />
            </Form.Item>
            <Form.Item name="head_time_max_us" label="波头时间最大(μs)">
              <InputNumber min={0.1} step={0.1} precision={2} className="w-full" />
            </Form.Item>
            <Form.Item name="head_time_step_us" label="波头步长(μs)">
              <InputNumber min={0.05} step={0.05} precision={2} className="w-full" />
            </Form.Item>
            <Form.Item name="tail_time_min_us" label="波尾时间最小(μs)">
              <InputNumber min={1} step={1} precision={2} className="w-full" />
            </Form.Item>
            <Form.Item name="tail_time_max_us" label="波尾时间最大(μs)">
              <InputNumber min={1} step={1} precision={2} className="w-full" />
            </Form.Item>
            <Form.Item name="tail_time_step_us" label="波尾步长(μs)">
              <InputNumber min={0.5} step={0.5} precision={2} className="w-full" />
            </Form.Item>
          </div>
          <div className="mb-2 flex flex-col gap-1">
            <Form.Item name="binary_search" label="二分迭代" valuePropName="checked" className="mb-0">
              <Select
                options={[
                  { value: true, label: "开启" },
                  { value: false, label: "关闭" },
                ]}
              />
            </Form.Item>
            {selectedAtpModel ? (
              <Alert
                type="info"
                showIcon
                message="开启后以雷电流为变量进行折半搜索逼近临界耐雷水平（每塔约 15~30 次 ATP 调用）。"
              />
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <Form.Item name="binary_search_low_ka" label="二分下限(kA)">
              <InputNumber min={0.1} step={0.1} precision={2} className="w-full" disabled={!selectedAtpModel} />
            </Form.Item>
            <Form.Item name="binary_search_high_ka" label="二分上限(kA)">
              <InputNumber min={0.1} step={0.1} precision={2} className="w-full" disabled={!selectedAtpModel} />
            </Form.Item>
            <Form.Item name="binary_search_tolerance_ka" label="精度阈值(kA)">
              <InputNumber min={0.01} step={0.01} precision={2} className="w-full" disabled={!selectedAtpModel} />
            </Form.Item>
          </div>
        </>
      ) : null}
    </Form>
  );
}
