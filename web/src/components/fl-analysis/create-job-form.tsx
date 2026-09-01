"use client";

import { useState } from "react";
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Steps, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { FormInstance } from "antd";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import { readLinePreparation } from "@/lib/line-preparation";
import type {
  AtpAssetSummary,
  AtpEngineStatusResponse,
  LineSummary,
  LineTowerListResponse,
  LineTowerSummary,
} from "@/types/auth";

import {
  CREATE_JOB_DEFAULTS,
  formatJobType,
  preparationColor,
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
  open: boolean;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (values: CreateJobFormValues) => void;
};

function useSelectOptions(
  dimensionOptions: FlDimensionOption[],
  fallbackOptions: FlDimensionOption[],
): FlDimensionOption[] {
  return dimensionOptions.length > 0 ? dimensionOptions : fallbackOptions;
}

function towerRiskTag(value: string | null | undefined): React.ReactNode {
  if (!value) {
    return "-";
  }
  const level = value.trim();
  let color = "default";
  if (level === "1") {
    color = "green";
  } else if (level === "2") {
    color = "orange";
  } else if (level === "3") {
    color = "red";
  }
  return <Tag color={color}>{value}</Tag>;
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
  open,
  submitting,
  onCancel,
  onSubmit,
}: CreateJobFormProps) {
  const { user, fetchWithAuth } = useAuth();
  const [currentStep, setCurrentStep] = useState(0);
  const [prevOpen, setPrevOpen] = useState(open);
  const [prevJobType, setPrevJobType] = useState(selectedJobType);
  const selectedLineId = Form.useWatch("line_id", form) ?? "";
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
  // 风险评估没有计算方法 / 高级参数步骤，仅保留基础信息一步。
  const stepCount = isNormal || isTongtiao ? 3 : 1;
  const lastStepIndex = stepCount - 1;

  const towersQuery = useQuery({
    queryKey: ["/api/v1/lines", selectedLineId, "towers"],
    enabled: !!user && !!selectedLineId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${selectedLineId}/towers?limit=1000&offset=0`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  // 弹窗重新打开 / 任务类型切换时回到第一步（在渲染期调整状态，避免 effect 内 setState）
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setCurrentStep(0);
    }
  }
  if (selectedJobType !== prevJobType) {
    setPrevJobType(selectedJobType);
    setCurrentStep(0);
  }

  const goNext = async () => {
    const fields =
      currentStep === 0
        ? ["job_name", "job_type", "line_id"]
        : currentStep === 1
          ? isTongtiao
            ? ["fanji_tzl_method", "raoji_tzl_method"]
            : ["fanji_naleishuiping_method", "raoji_naleishuiping_method", "fanji_tzl_method", "raoji_tzl_method"]
          : [];
    try {
      await form.validateFields(fields);
      setCurrentStep((step) => step + 1);
    } catch {
      // 校验失败信息由 Form.Item 展示，停留在当前步骤
    }
  };

  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: "序号", dataIndex: "seq_no", width: 70 },
    {
      title: "塔号",
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: "模型", dataIndex: "tower_model", width: 160, render: (value: string | null) => value || "-" },
    { title: "塔型", dataIndex: "tower_type", width: 90, render: (value: string | null) => value || "-" },
    {
      title: "接地电阻(Ω)",
      dataIndex: "ground_resistance_ohm",
      width: 110,
      render: (value: number | null) => value ?? "-",
    },
    {
      title: "地闪密度",
      dataIndex: "lightning_density",
      width: 100,
      render: (value: number | null) => value ?? "-",
    },
    { title: "风险等级", dataIndex: "risk_level", width: 90, render: towerRiskTag },
  ];

  const stepItems = (isNormal || isTongtiao
    ? [
        { title: "基础信息" },
        { title: "计算方法" },
        { title: "高级参数" },
      ]
    : [{ title: "基础信息" }]
  ).map((item, index) => ({ ...item, key: index }));

  return (
    <Form<CreateJobFormValues>
      form={form}
      layout="vertical"
      initialValues={CREATE_JOB_DEFAULTS}
      onFinish={onSubmit}
    >
      <Steps current={currentStep} items={stepItems} className="mb-4" size="small" />

      {/* 步骤内容区固定高度 520px，不随表单项目数量自动伸缩；超高时内部滚动 */}
      <div style={{ height: 520, overflowY: "auto", overflowX: "hidden" }}>
      {currentStep === 0 ? (
        <>
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

          {selectedLineId ? (
            <Card size="small" className="fl-form-section mt-3">
              <div className="fl-form-section-title">
                线路杆塔
                <Typography.Text type="secondary" className="ml-2">
                  {selectedLine ? `${selectedLine.name || selectedLine.code} · ` : ""}
                  {towersQuery.data ? `共 ${towersQuery.data.total} 基` : ""}
                </Typography.Text>
              </div>
              {towersQuery.isError ? (
                <Alert
                  type="error"
                  showIcon
                  message="杆塔列表加载失败"
                  description={towersQuery.error instanceof Error ? towersQuery.error.message : "未知错误"}
                />
              ) : (
                <Table<LineTowerSummary>
                  rowKey={(row) => row.id}
                  columns={towerColumns}
                  dataSource={towersQuery.data?.items ?? []}
                  loading={towersQuery.isFetching}
                  size="small"
                  pagination={{ pageSize: 8, showSizeChanger: false, hideOnSinglePage: true }}
                  scroll={{ x: 760, y: 260 }}
                />
              )}
            </Card>
          ) : null}
        </>
      ) : null}

      {currentStep === 1 && showWaveformBlock ? (
        <>
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
            <Card size="small" className="fl-form-section mt-3">
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
        </>
      ) : null}

      {currentStep === 2 && showWaveformBlock ? (
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

      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button onClick={onCancel} disabled={submitting}>
          取消
        </Button>
        {currentStep > 0 ? (
          <Button onClick={() => setCurrentStep((step) => step - 1)} disabled={submitting}>
            上一步
          </Button>
        ) : null}
        {currentStep < lastStepIndex ? (
          <Button type="primary" onClick={goNext}>
            下一步
          </Button>
        ) : (
          <Button type="primary" loading={submitting} onClick={() => form.submit()}>
            创建并启动任务
          </Button>
        )}
      </div>
    </Form>
  );
}
