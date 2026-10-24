"use client";

import { useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { FormInstance } from "antd";
import { useQuery } from "@tanstack/react-query";

import { useI18n } from "@/lib/i18n";
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
  const { t } = useI18n();
  const { user, fetchWithAuth } = useAuth();
  const [prevOpen, setPrevOpen] = useState(open);
  const [advancedOpen, setAdvancedOpen] = useState(false);
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
    if (selectedJobType === "tongtiao") {
      // 对齐 C# Form_TongTiaoJiSuan.cs:226-229：同跳任务的跳闸率计算方法固定为
      // 反击=规程(guicheng)、绕击=EGM(egm)，界面上不提供选择（仍需随请求提交，供 ATP 模板 CAL_MODE 使用）。
      form.setFieldsValue({ fanji_tzl_method: "guicheng", raoji_tzl_method: "egm" });
    }
  }

  /** 复合列取值：与 C# 一致用固定分隔符拼接（地理坐标 经度|纬度，其余 前者,后者）。 */
  function joinPair(first: number | null | undefined, second: number | null | undefined, sep: string): string {
    if (first === null && second === null) return "-";
    if (first === null || second === null) return `${first ?? ""}${sep}${second ?? ""}`;
    return `${first}${sep}${second}`;
  }

  // 杆塔列表列：与 C# 端「新建计算任务」（Form_PuTongJiSuan / Form_TongTiaoJiSuan）
  // 的 11 列严格对齐（列名、列序、复合值分隔符）。
  const towerColumns: ColumnsType<LineTowerSummary> = [
    {
      title: t("塔号"),
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: t("杆塔模型"), dataIndex: "tower_model", width: 150, render: (value: string | null) => value || "-" },
    {
      title: t("地理坐标°"),
      key: "geo",
      // 经纬度拼成「经度|纬度」较长，加宽并禁止换行（避免两行显示）
      width: 210,
      onCell: () => ({ style: { whiteSpace: "nowrap" } }),
      render: (_: unknown, row: LineTowerSummary) => joinPair(row.longitude, row.latitude, "|"),
    },
    {
      title: t("档距"),
      key: "span",
      width: 130,
      render: (_: unknown, row: LineTowerSummary) => joinPair(row.span_small_m, row.span_large_m, ","),
    },
    {
      title: t("海拔高度m"),
      dataIndex: "altitude_m",
      width: 110,
      render: (value: number | null) => value ?? "-",
    },
    { title: t("地形"), dataIndex: "terrain", width: 90, render: (value: string | null) => value || "-" },
    {
      title: t("接地电阻Ω"),
      dataIndex: "ground_resistance_ohm",
      width: 110,
      render: (value: number | null) => value ?? "-",
    },
    {
      title: t("地闪密度 次/(km^2*年)"),
      dataIndex: "lightning_density",
      width: 170,
      render: (value: number | null) => value ?? "-",
    },
    {
      title: t("雷电流"),
      key: "current",
      width: 120,
      render: (_: unknown, row: LineTowerSummary) => joinPair(row.current_a, row.current_b, ","),
    },
    {
      title: t("倾角"),
      key: "slope",
      width: 110,
      render: (_: unknown, row: LineTowerSummary) => joinPair(row.slope_1, row.slope_2, ","),
    },
    { title: t("塔型"), dataIndex: "tower_type", width: 110, render: (value: string | null) => value || "-" },
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
          <div className="fl-create-form-block-title">{t("任务信息")}</div>
          <div className="fl-create-form-grid">
            <Form.Item className="fl-span-2" name="job_name" label={t("任务名")} rules={[{ required: true, message: t("请输入任务名") }]}>
            <Input
              placeholder={selectedLine
                ? `${selectedLine.name || selectedLine.code}-${formatJobType(selectedJobType)}`
                : `${formatJobType(selectedJobType)}任务`}
            />
          </Form.Item>

          <Form.Item name="job_type" label={t("任务类型")} rules={[{ required: true, message: t("请选择任务类型") }]}>
            <Select
              loading={dimensionsLoading}
              options={jobTypeOptions}
            />
          </Form.Item>

          <Form.Item
            name="line_id"
            label={t("线路")}
            rules={[{ required: true, message: t("请选择线路") }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              placeholder={t("选择线路")}
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
        </div>

        {/* 「计算方法」分区仅普通计算需要：同跳计算的跳闸率方法由 C# 固定、
            「包含杆塔」由杆塔列表勾选体现，因此同跳下整栏不渲染（避免空标题）。 */}
        {showNormalBlock ? (
          <div className="fl-create-form-block">
            <div className="fl-create-form-block-title">{t("计算方法")}</div>
            <div className="fl-create-form-grid">
              <Form.Item name="fanji_naleishuiping_method" label={t("反击耐雷水平计算方法")} rules={[{ required: true, message: t("请选择反击耐雷水平计算方法") }]}>
                <Select
                  loading={dimensionsLoading}
                  options={fanjiNaleishuipingMethodOptions}
                />
              </Form.Item>
              <Form.Item name="raoji_naleishuiping_method" label={t("绕击耐雷水平计算方法")} rules={[{ required: true, message: t("请选择绕击耐雷水平计算方法") }]}>
                <Select
                  loading={dimensionsLoading}
                  options={raojiNaleishuipingMethodOptions}
                />
              </Form.Item>
              <Form.Item name="fanji_tzl_method" label={t("反击跳闸率计算方法")} rules={[{ required: true, message: t("请选择反击跳闸率计算方法") }]}>
                <Select
                  loading={dimensionsLoading}
                  options={fanjiTzlMethodOptions}
                />
              </Form.Item>
              <Form.Item name="raoji_tzl_method" label={t("绕击跳闸率计算方法")} rules={[{ required: true, message: t("请选择绕击跳闸率计算方法") }]}>
                <Select
                  loading={dimensionsLoading}
                  options={raojiTzlMethodOptions}
                />
              </Form.Item>
            </div>
          </div>
        ) : null}

        {showTongtiaoBlock ? (
          <>
            {/* 同跳计算：反击/绕击跳闸率计算方法由 C# 固定（Form_TongTiaoJiSuan.cs:226-229
                反击=规程、绕击=EGM），不暴露给用户配置；「包含杆塔」在 C# 里是杆塔列表的勾选列，
                本页由列表行勾选（selected_tower_ids）实现，故也不再提供手输杆塔 ID 的入口。
                这里仅保留 hidden 字段，保证这两个值随请求提交（供 ATP 模板 CAL_MODE 使用）。 */}
            <Form.Item name="fanji_tzl_method" hidden>
              <Input />
            </Form.Item>
            <Form.Item name="raoji_tzl_method" hidden>
              <Input />
            </Form.Item>
            <Form.Item name="include_tower_ids" hidden>
              <Input />
            </Form.Item>
          </>
        ) : null}

        <div className="fl-create-form-block">
          <div className="fl-create-form-block-title">{t("杆塔列表")}</div>
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
                    message={t("杆塔列表加载失败")}
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
                    scroll={{ x: 1440, y: 320 }}
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

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button onClick={() => setAdvancedOpen(true)}>{t("高级参数")}</Button>
        <div className="flex items-center gap-2">
          <Button onClick={onCancel} disabled={submitting}>
            取消
          </Button>
          <Button type="primary" loading={submitting} onClick={() => form.submit()}>
            {t("创建并启动任务")}
          </Button>
        </div>
      </div>

      {/* 高级参数：独立弹窗展示（不在新建表单中平铺） */}
      <Modal
        title={t("高级参数")}
        open={advancedOpen}
        onCancel={() => setAdvancedOpen(false)}
        width={720}
        forceRender
        destroyOnHidden={false}
        footer={
          <Button type="primary" onClick={() => setAdvancedOpen(false)}>
            确定
          </Button>
        }
      >
        <div className="fl-create-form-grid">
          {/* 是否海拔修正 / 感应电压公式：按需求提到高级参数弹窗最上方展示 */}
          <Form.Item name="altitude_correction" label={t("是否海拔修正")}>
            <Select
              loading={dimensionsLoading}
              options={altitudeCorrectionOptions}
            />
          </Form.Item>
          <Form.Item name="induced_voltage_formula" label={t("感应电压公式")}>
            <Select
              options={[
                { value: "formula1", label: t("公式1") },
                { value: "formula2", label: t("公式2") },
              ]}
            />
          </Form.Item>
          <Form.Item name="current_waveform" label={t("雷电流波形")}>
            <Select
              loading={dimensionsLoading}
              options={currentWaveformOptions}
            />
          </Form.Item>
          <Form.Item name="flashover_method" label={t("绝缘子闪络判据")}>
            <Select
              loading={dimensionsLoading}
              options={flashoverMethodOptions}
            />
          </Form.Item>
          {/* 波头时间：Min/Max/步长 一行（对齐 C# 高级设置 Form_GJSZ_PuTongJiSuan） */}
          <Form.Item label={t("波头时间(μs)")}>
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-sm whitespace-nowrap">{t("最小")}</span>
              <Form.Item name="head_time_min_us" noStyle>
                <InputNumber min={0.1} step={0.1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">{t("最大")}</span>
              <Form.Item name="head_time_max_us" noStyle>
                <InputNumber min={0.1} step={0.1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">{t("步长")}</span>
              <Form.Item name="head_time_step_us" noStyle>
                <InputNumber min={0.05} step={0.05} precision={2} className="w-24" />
              </Form.Item>
            </div>
          </Form.Item>
          {/* 波尾时间：Min/Max/步长 一行（对齐 C# 高级设置） */}
          <Form.Item label={t("波尾时间(μs)")}>
            <div className="flex items-center gap-2">
              <span className="text-gray-500 text-sm whitespace-nowrap">{t("最小")}</span>
              <Form.Item name="tail_time_min_us" noStyle>
                <InputNumber min={1} step={1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">{t("最大")}</span>
              <Form.Item name="tail_time_max_us" noStyle>
                <InputNumber min={1} step={1} precision={2} className="w-24" />
              </Form.Item>
              <span className="text-gray-500 text-sm whitespace-nowrap ml-2">{t("步长")}</span>
              <Form.Item name="tail_time_step_us" noStyle>
                <InputNumber min={0.5} step={0.5} precision={2} className="w-24" />
              </Form.Item>
            </div>
          </Form.Item>
        </div>
      </Modal>
    </Form>
  );
}
