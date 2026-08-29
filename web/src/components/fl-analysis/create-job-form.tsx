"use client";

import { Alert, Button, Form, Input, InputNumber, Select, Space, Tag, Card } from "antd";
import type { FormInstance } from "antd";

import { readLinePreparation } from "@/lib/line-preparation";
import type {
  AtpAssetSummary,
  AtpEngineStatusResponse,
  LinePreparationSummary,
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
const NALEISHUIPING_METHOD_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "guicheng", label: "规程" },
  { value: "atp", label: "ATP" },
];
const TZL_METHOD_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "none", label: "无" },
  { value: "guicheng", label: "规程" },
  { value: "egm", label: "EGM" },
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

function useSelectOptions(
  dimensionOptions: FlDimensionOption[],
  fallbackOptions: FlDimensionOption[],
): FlDimensionOption[] {
  return dimensionOptions.length > 0 ? dimensionOptions : fallbackOptions;
}

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

  const jobTypeOptions = useSelectOptions(optionMap.job_type, JOB_TYPE_FALLBACK_OPTIONS);
  const currentWaveformOptions = useSelectOptions(optionMap.current_waveform, CURRENT_WAVEFORM_FALLBACK_OPTIONS);
  const flashoverMethodOptions = useSelectOptions(optionMap.flashover_method, FLASHOVER_METHOD_FALLBACK_OPTIONS);
  const altitudeCorrectionOptions = useSelectOptions(optionMap.altitude_correction, ALTITUDE_CORRECTION_FALLBACK_OPTIONS);
  const fanjiNaleishuipingMethodOptions = useSelectOptions(optionMap.fanji_naleishuiping_method, NALEISHUIPING_METHOD_FALLBACK_OPTIONS);
  const raojiNaleishuipingMethodOptions = useSelectOptions(optionMap.raoji_naleishuiping_method, NALEISHUIPING_METHOD_FALLBACK_OPTIONS);
  const fanjiTzlMethodOptions = useSelectOptions(optionMap.fanji_tzl_method, TZL_METHOD_FALLBACK_OPTIONS);
  const raojiTzlMethodOptions = useSelectOptions(optionMap.raoji_tzl_method, TZL_METHOD_FALLBACK_OPTIONS);

  const isNormal = selectedJobType === "normal";
  const isTongtiao = selectedJobType === "tongtiao";
  const showWaveformBlock = isNormal || isTongtiao;
  const showNormalBlock = isNormal;
  const showTongtiaoBlock = isTongtiao;
  const showAdvancedBlock = isNormal || isTongtiao;

  return (
    <Form<CreateJobFormValues>
      form={form}
      layout="vertical"
      initialValues={CREATE_JOB_DEFAULTS}
      onFinish={onSubmit}
    >
      <Card size="small" className="fl-form-section">
        <div className="fl-form-section-title">基础信息</div>
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
            options={lines.map((item) => {
              const preparation = readLinePreparation(item);
              const statuses = [
                preparation.lightning_current,
                preparation.lightning_density,
                preparation.ground_slope,
              ];
              return {
                value: item.id,
                label: item.name || item.code,
                disabled: !preparation.all_ready,
                optionRender: ({ value: optionValue }: { value: string }) => {
                  const line = lines.find((current) => current.id === optionValue);
                  const currentPreparation = line ? readLinePreparation(line) : preparation;
                  const currentStatuses = [
                    currentPreparation.lightning_current,
                    currentPreparation.lightning_density,
                    currentPreparation.ground_slope,
                  ];
                  return (
                    <div className="flex flex-col gap-1">
                      <span>{line ? line.name || line.code : item.name || item.code}</span>
                      <Space size={[4, 4]} wrap>
                        {currentStatuses.map((status) => (
                          <Tag key={status.key} color={preparationColor(status.ready)}>
                            {status.label}
                          </Tag>
                        ))}
                      </Space>
                    </div>
                  );
                },
              };
            })}
          />
        </Form.Item>
      </Card>

      {showNormalBlock ? (
        <Card size="small" className="fl-form-section">
          <div className="fl-form-section-title">计算方法</div>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="fanji_naleishuiping_method" label="反击耐雷水平" rules={[{ required: true, message: "请选择反击耐雷水平方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={fanjiNaleishuipingMethodOptions}
              />
            </Form.Item>
            <Form.Item name="raoji_naleishuiping_method" label="绕击耐雷水平" rules={[{ required: true, message: "请选择绕击耐雷水平方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={raojiNaleishuipingMethodOptions}
              />
            </Form.Item>
            <Form.Item name="fanji_tzl_method" label="反击跳闸率" rules={[{ required: true, message: "请选择反击跳闸率方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={fanjiTzlMethodOptions}
              />
            </Form.Item>
            <Form.Item name="raoji_tzl_method" label="绕击跳闸率" rules={[{ required: true, message: "请选择绕击跳闸率方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={raojiTzlMethodOptions}
              />
            </Form.Item>
          </div>
        </Card>
      ) : null}

      {showTongtiaoBlock ? (
        <Card size="small" className="fl-form-section">
          <div className="fl-form-section-title">计算方法</div>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="fanji_tzl_method" label="反击跳闸率" rules={[{ required: true, message: "请选择反击跳闸率方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={fanjiTzlMethodOptions}
              />
            </Form.Item>
            <Form.Item name="raoji_tzl_method" label="绕击跳闸率" rules={[{ required: true, message: "请选择绕击跳闸率方法" }]}>
              <Select
                loading={dimensionsLoading}
                options={raojiTzlMethodOptions}
              />
            </Form.Item>
            <Form.Item name="include_tower_ids" label="包含杆塔ID" className="md:col-span-2">
              <Select
                mode="tags"
                tokenSeparators={[","]}
                placeholder="输入杆塔ID后回车，支持多个"
                options={[]}
              />
            </Form.Item>
          </div>
        </Card>
      ) : null}

      {showWaveformBlock ? (
        <Card size="small" className="fl-form-section">
          <div className="fl-form-section-title">ATP模型</div>
          {atpModelsError ? (
            <Alert
              type="error"
              showIcon
              message={atpModelsError instanceof Error ? atpModelsError.message : "ATP 模型列表加载失败"}
            />
          ) : null}
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
        </Card>
      ) : null}

      {showWaveformBlock ? (
        <Card size="small" className="fl-form-section">
          <div className="fl-form-section-title">高级参数</div>
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
          <div className="mt-4 flex flex-col gap-1">
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
        </Card>
      ) : null}
    </Form>
  );
}
