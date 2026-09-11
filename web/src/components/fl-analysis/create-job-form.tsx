"use client";

import { useState } from "react";
import { Alert, Button, Collapse, Form, Input, InputNumber, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { FormInstance } from "antd";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import { readLinePreparation } from "@/lib/line-preparation";
import type {
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

// 新建表单任务类型仅提供 普通计算 / 同跳计算（风险评估暂不在新建入口提供）。
const JOB_TYPE_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "normal", label: "普通计算" },
  { value: "tongtiao", label: "同跳计算" },
];
/** 新建表单隐藏「风险评估」任务类型（维度管理 DB / 兜底列表两边都过滤，防漏网）。 */
const HIDDEN_JOB_TYPES = new Set(["risk"]);
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
// 反击跳闸率：不含 EGM（2026-09-12 需求，后端维度项 fanji_tzl_method 已同步停用）
const FANJI_TZL_METHOD_FALLBACK_OPTIONS: FlDimensionOption[] = [
  { value: "none", label: "无" },
  { value: "guicheng", label: "规程" },
];
const RAOJI_TZL_METHOD_FALLBACK_OPTIONS: FlDimensionOption[] = [
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
  open: boolean;
  /** 每次「新建任务」打开时自增；用于关闭后再次打开时强制向导回到第一步。 */
  openEpoch?: number;
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
  open,
  openEpoch = 0,
  submitting,
  onCancel,
  onSubmit,
}: CreateJobFormProps) {
  const { user, fetchWithAuth } = useAuth();
  const [prevOpen, setPrevOpen] = useState(open);
  const [prevEpoch, setPrevEpoch] = useState(openEpoch);
  const [prevJobType, setPrevJobType] = useState(selectedJobType);
  const selectedLineId = Form.useWatch("line_id", form) ?? "";
  const selectedTowerIds = Form.useWatch("selected_tower_ids", form) ?? [];
  const { optionMap, isLoading: dimensionsLoading } = useFlDimensionOptions();

  const jobTypeOptions = useSelectOptions(optionMap.job_type, JOB_TYPE_FALLBACK_OPTIONS).filter(
    (option) => !HIDDEN_JOB_TYPES.has(option.value),
  );
  const currentWaveformOptions = useSelectOptions(optionMap.current_waveform, CURRENT_WAVEFORM_FALLBACK_OPTIONS);
  const flashoverMethodOptions = useSelectOptions(optionMap.flashover_method, FLASHOVER_METHOD_FALLBACK_OPTIONS);
  const altitudeCorrectionOptions = useSelectOptions(optionMap.altitude_correction, ALTITUDE_CORRECTION_FALLBACK_OPTIONS);
  const fanjiNaleishuipingMethodOptions = useSelectOptions(optionMap.fanji_naleishuiping_method, NALEISHUIPING_METHOD_FALLBACK_OPTIONS);
  const raojiNaleishuipingMethodOptions = useSelectOptions(optionMap.raoji_naleishuiping_method, NALEISHUIPING_METHOD_FALLBACK_OPTIONS);
  const fanjiTzlMethodOptions = useSelectOptions(optionMap.fanji_tzl_method, FANJI_TZL_METHOD_FALLBACK_OPTIONS);
  const raojiTzlMethodOptions = useSelectOptions(optionMap.raoji_tzl_method, RAOJI_TZL_METHOD_FALLBACK_OPTIONS);

  const isNormal = selectedJobType === "normal";
  const isTongtiao = selectedJobType === "tongtiao";
  const showWaveformBlock = isNormal || isTongtiao;
  const showNormalBlock = isNormal;
  const showTongtiaoBlock = isTongtiao;
  // 新建表单已不提供「风险评估」，但保留单步分支防御（历史任务 / 兼容 flow 仍可能带 risk 类型）。

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
      /* 打开即恢复默认（高级参数折叠） */
    }
  }
  // antd Modal 关闭后隐藏 DOM 不重渲染，子组件收不到 open=false（prevOpen 恒为 true），
  // 因此「关闭后再点新建任务」无法靠 open 切换重置步骤；改为由父级每次打开自增的
  // openEpoch 驱动：epoch 变化即代表一次全新的「新建任务」会话，向导回到第一步。
  if (openEpoch !== prevEpoch) {
    setPrevEpoch(openEpoch);
  }
  if (selectedJobType !== prevJobType) {
    setPrevJobType(selectedJobType);
  }

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

  return (
    <Form<CreateJobFormValues>
      form={form}
      layout="vertical"
      initialValues={CREATE_JOB_DEFAULTS}
      onFinish={() => onSubmit(form.getFieldsValue(true) as CreateJobFormValues)}
    >
      {/* 单页面表单：基础信息 + 计算方法 双列；高级参数默认折叠 */}
      <div className="fl-create-form-scroll">
        <div className="fl-create-form-block">
          <div className="fl-create-form-block-title">任务信息</div>
          <div className="fl-create-form-grid">
            <Form.Item name="job_name" label="任务名" rules={[{ required: true, message: "请输入任务名" }]}>
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


          </div>
        </div>

        <div className="fl-create-form-block">
          <div className="fl-create-form-block-title">计算方法</div>
          <div className="fl-create-form-grid">
        {showWaveformBlock ? (
          <>
            {showNormalBlock ? (
              <>
              <Form.Item name="fanji_naleishuiping_method" label="反击耐雷水平计算方法" rules={[{ required: true, message: "请选择反击耐雷水平计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={fanjiNaleishuipingMethodOptions}
                />
              </Form.Item>
              <Form.Item name="raoji_naleishuiping_method" label="绕击耐雷水平计算方法" rules={[{ required: true, message: "请选择绕击耐雷水平计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={raojiNaleishuipingMethodOptions}
                />
              </Form.Item>
              <Form.Item name="fanji_tzl_method" label="反击跳闸率计算方法" rules={[{ required: true, message: "请选择反击跳闸率计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={fanjiTzlMethodOptions}
                />
              </Form.Item>
              <Form.Item name="raoji_tzl_method" label="绕击跳闸率计算方法" rules={[{ required: true, message: "请选择绕击跳闸率计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={raojiTzlMethodOptions}
                />
              </Form.Item>
              </>
            ) : null}

          {showTongtiaoBlock ? (
            <>
              <Form.Item name="fanji_tzl_method" label="反击跳闸率计算方法" rules={[{ required: true, message: "请选择反击跳闸率计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={fanjiTzlMethodOptions}
                />
              </Form.Item>
              <Form.Item name="raoji_tzl_method" label="绕击跳闸率计算方法" rules={[{ required: true, message: "请选择绕击跳闸率计算方法" }]}>
                <Select
                  loading={dimensionsLoading}
                  options={raojiTzlMethodOptions}
                />
              </Form.Item>
              <Form.Item name="include_tower_ids" label="包含杆塔ID">
                <Select
                  mode="tags"
                  tokenSeparators={[","]}
                  placeholder="输入杆塔ID后回车，支持多个"
                  options={[]}
                />
              </Form.Item>
            </>
          ) : null}
          </>
        ) : null}
          </div>
        </div>

        <Collapse
          ghost
          className="fl-create-form-advanced fl-create-form-block"
          items={[
            {
              key: "advanced",
              label: "高级参数",
              forceRender: true,
              children: (
                <div className="fl-create-form-grid">
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
          {/* 波头时间：Min/Max/步长 一行（对齐 C# 高级设置 Form_GJSZ_PuTongJiSuan） */}
          <Form.Item label="波头时间(μs)">
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-sm whitespace-nowrap">最小</span>
              <Form.Item name="head_time_min_us" noStyle>
                <InputNumber min={0.1} step={0.1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">最大</span>
              <Form.Item name="head_time_max_us" noStyle>
                <InputNumber min={0.1} step={0.1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">步长</span>
              <Form.Item name="head_time_step_us" noStyle>
                <InputNumber min={0.05} step={0.05} precision={2} className="w-24" />
              </Form.Item>
            </div>
          </Form.Item>
          {/* 波尾时间：Min/Max/步长 一行（对齐 C# 高级设置） */}
          <Form.Item label="波尾时间(μs)">
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-sm whitespace-nowrap">最小</span>
              <Form.Item name="tail_time_min_us" noStyle>
                <InputNumber min={1} step={1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">最大</span>
              <Form.Item name="tail_time_max_us" noStyle>
                <InputNumber min={1} step={1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">步长</span>
              <Form.Item name="tail_time_step_us" noStyle>
                <InputNumber min={0.5} step={0.5} precision={2} className="w-24" />
              </Form.Item>
            </div>
          </Form.Item>
                </div>
              ),
            },
          ]}
        />
        <div className="fl-create-form-block">
          <div className="fl-create-form-block-title">计算线路</div>
          <div className="fl-create-form-grid">
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
          </div>
          {selectedLineId ? (
            <>
              {/* 注册 selected_tower_ids 字段（受控 rowSelection 的 form 存储） */}
              <Form.Item name="selected_tower_ids" hidden>
                <Input />
              </Form.Item>
              <Form.Item>
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
                    pagination={false}
                    scroll={{ x: 760, y: 320 }}
                    rowSelection={{
                      selectedRowKeys: selectedTowerIds,
                      onChange: (selectedRowKeys) => form.setFieldValue("selected_tower_ids", selectedRowKeys),
                    }}
                  />
                )}
              </Form.Item>
            </>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button onClick={onCancel} disabled={submitting}>
          取消
        </Button>
        <Button type="primary" loading={submitting} onClick={() => form.submit()}>
          创建并启动任务
        </Button>
      </div>
    </Form>
  );
}
