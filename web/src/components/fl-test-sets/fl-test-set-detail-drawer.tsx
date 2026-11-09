"use client";

/**
 * 防雷测试集详情抽屉：用例管理 + 批量执行 + 执行历史。
 *
 * 表单按集合类别切换：
 * - fl_calc  Tabs 分页：基本信息 / 杆塔参数（照搬「编辑杆塔」表单）/ 计算参数
 *            （照搬「防雷计算 → 新建任务」表单）/ 评估标准。用例自包含，
 *            不再选择测试线路与测试塔，后端按快照托管一基计算塔；
 * - retrofit 改造口径（建线/非建线）+ 前置防雷计算任务 + 目标塔 + 参考评估方案。
 * 发起执行：勾选用例（默认全选启用用例）→ POST /fl-test-sets/{id}/runs。
 */
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Col,
  Collapse,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { DeleteOutlined, EditOutlined, PlayCircleOutlined, PlusOutlined, RedoOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type {
  FlTestCaseSummary,
  FlTestMetric,
  FlTestRunListResponse,
  FlTestRunSummary,
  FlTestSetSummary,
} from "@/types/fl-test-set";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";
import { FlTestRunStatusTag } from "@/components/fl-test-sets/fl-test-set-tab";
import { FlTestRunDrawer } from "@/components/fl-test-sets/fl-test-run-drawer";

interface JobOption {
  id: string;
  job_name: string | null;
  job_type: string;
  status: string;
  line_name?: string | null;
}

/** 「编辑杆塔」表单字段（线路管理 → 线路详情 → 编辑杆塔），原样照搬。 */
const TOWER_FORM_FIELDS = [
  "tower_no", "tower_type", "tower_model", "risk_level", "longitude", "latitude", "altitude_m",
  "ground_resistance_ohm", "lightning_density", "span_small_m", "span_large_m", "slope_1", "slope_2",
] as const;

/** 仿真必需、但编辑杆塔表单没有的字段：留空时由塔模型默认值 / 系统兜底补齐。 */
const SIM_OVERRIDE_FIELDS = [
  "voltage_kv", "insulator_length_m", "shield_wire_height_m", "call_height_m",
  "lightning_wire_left_mid_distance_m", "lightning_wire_right_mid_distance_m",
  "protection_angle_left_deg", "protection_angle_right_deg",
  "height_upper_m", "height_middle_m", "height_lower_m",
  "spacing_upper_m", "spacing_middle_m", "spacing_lower_m",
  "current_a", "current_b", "arrester_a", "arrester_b", "arrester_c",
] as const;

/** 「防雷计算 → 新建任务」表单的计算方法 + 高级参数字段，原样照搬。 */
const EXEC_OPTION_FIELDS = [
  "fanji_naleishuiping_method", "raoji_naleishuiping_method",
  "fanji_tzl_method", "raoji_tzl_method",
  "current_waveform", "flashover_method", "altitude_correction", "induced_voltage_formula",
  "head_time_min_us", "head_time_max_us", "head_time_step_us",
  "tail_time_min_us", "tail_time_max_us", "tail_time_step_us",
  "binary_search",
] as const;

/** 与 fl-analysis/types.ts 的 CREATE_JOB_DEFAULTS 对齐。 */
const EXEC_DEFAULTS: Record<string, unknown> = {
  fanji_naleishuiping_method: "atp",
  raoji_naleishuiping_method: "atp",
  fanji_tzl_method: "guicheng",
  raoji_tzl_method: "egm",
  current_waveform: "heidler",
  flashover_method: "intersection",
  altitude_correction: "none",
  induced_voltage_formula: "formula1",
  head_time_min_us: 2.6,
  head_time_max_us: 2.6,
  head_time_step_us: 0.1,
  tail_time_min_us: 50,
  tail_time_max_us: 50,
  tail_time_step_us: 1,
  binary_search: true,
};

const TOWER_FORM_DEFAULTS: Record<string, unknown> = {
  tower_no: "1",
  tower_type: "",
  tower_model: "",
};

/** 「仿真参数（可选覆盖）」区：留空按塔模型编码带默认值。 */
const SIM_NUMBER_LABELS: Array<[string, string]> = [
  ["voltage_kv", "电压等级"],
  ["insulator_length_m", "绝缘子串长度(mm)"],
  ["shield_wire_height_m", "避雷线高度(m)"],
  ["call_height_m", "杆塔呼高(m)"],
  ["lightning_wire_left_mid_distance_m", "左避雷线中距(m)"],
  ["lightning_wire_right_mid_distance_m", "右避雷线中距(m)"],
  ["protection_angle_left_deg", "左保护角(°)"],
  ["protection_angle_right_deg", "右保护角(°)"],
  ["height_upper_m", "上相高度(m)"],
  ["height_middle_m", "中相高度(m)"],
  ["height_lower_m", "下相高度(m)"],
  ["spacing_upper_m", "上相中距(m)"],
  ["spacing_middle_m", "中相中距(m)"],
  ["spacing_lower_m", "下相中距(m)"],
  ["current_a", "雷电流幅值 a"],
  ["current_b", "雷电流幅值 b"],
];

/** 与「编辑杆塔」表单一致的数字输入；留空表示交给塔模型 / 系统默认。 */
function TowerNumberField({ name, label }: { name: string; label: string }) {
  const { t } = useI18n();
  return (
    <Form.Item name={name} label={t(label)}>
      <InputNumber style={{ width: "100%" }} placeholder={t("自动")} />
    </Form.Item>
  );
}

function pickFilled(values: Record<string, unknown>, fields: readonly string[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of fields) {
    const value = values[key];
    if (value !== undefined && value !== null && value !== "") result[key] = value;
  }
  return result;
}

const METRIC_PRESET_115: FlTestMetric[] = [
  { key: "counterstrike_withstand_ka", label: "反击耐雷水平", min: 60, max: 100, scope: "fanji" },
  { key: "shielding_withstand_ka", label: "绕击耐雷水平", min: 30, max: 2000, scope: "raoji1" },
  { key: "counterstrike_trip_rate", label: "反击跳闸率", min: 0.01, max: 1 },
  { key: "shielding_trip_rate", label: "绕击跳闸率", min: 0.001, max: 1 },
];

const METRIC_PRESET_230: FlTestMetric[] = [
  { key: "counterstrike_withstand_ka", label: "反击耐雷水平", min: 100, max: 160, scope: "fanji" },
  { key: "shielding_withstand_ka", label: "绕击耐雷水平", min: 50, max: 2000, scope: "raoji1" },
  { key: "counterstrike_trip_rate", label: "反击跳闸率", min: 0.005, max: 0.5 },
  { key: "shielding_trip_rate", label: "绕击跳闸率", min: 0.001, max: 0.5 },
];

const MEASURE_OPTIONS = ["加长绝缘子串", "降接地电阻", "调整保护角", "装设避雷器", "调整避雷线间距"];

export function FlTestSetDetailDrawer({
  testSet,
  open,
  onClose,
}: {
  testSet: FlTestSetSummary | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { user, hasPermission } = useAuth();
  const { modal: modalApi } = App.useApp();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState("cases");
  const [caseModalOpen, setCaseModalOpen] = useState(false);
  const [editingCase, setEditingCase] = useState<FlTestCaseSummary | null>(null);
  const [runDrawerId, setRunDrawerId] = useState<string | null>(null);
  const [launchOpen, setLaunchOpen] = useState(false);
  const [launchSelection, setLaunchSelection] = useState<string[]>([]);

  const canRead =
    hasPermission("line.read") || hasPermission("line.manage") || hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("fl.create") || hasPermission("line.manage") || hasPermission("atp.manage");
  const canRun = hasPermission("fl.start") || hasPermission("fl.create") || hasPermission("line.manage") || hasPermission("atp.manage");
  const canDelete = hasPermission("fl.delete") || hasPermission("line.manage") || hasPermission("atp.manage");

  const setId = testSet?.id ?? "";
  const casesQuery = useQuery({
    queryKey: ["/api/v1/fl-test-sets/cases", setId],
    enabled: open && !!setId && !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/${setId}/cases`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as { items: FlTestCaseSummary[]; total: number };
    },
  });

  const runsQuery = useQuery({
    queryKey: ["/api/v1/fl-test-sets/runs", setId],
    enabled: open && !!setId && !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/${setId}/runs?limit=20`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as FlTestRunListResponse;
    },
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/fl-test-sets/cases", setId] });
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/fl-test-sets/runs", setId] });
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/fl-test-sets"] });
  };

  const deleteCaseMutation = useMutation({
    mutationFn: async (caseId: string) => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/cases/${caseId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => invalidate(),
    onError: (error: Error) => modalApi.error({ title: t("删除用例失败"), content: error.message }),
  });

  const startRunMutation = useMutation({
    mutationFn: async (caseIds: string[]) => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/${setId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_ids: caseIds }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as FlTestRunSummary;
    },
    onSuccess: (run) => {
      setLaunchOpen(false);
      invalidate();
      setRunDrawerId(run.id);
    },
    onError: (error: Error) => modalApi.error({ title: t("发起执行失败"), content: error.message }),
  });

  const cases = casesQuery.data?.items ?? [];
  const enabledCases = cases.filter((c) => c.enabled);

  useEffect(() => {
    if (launchOpen) setLaunchSelection(enabledCases.map((c) => c.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [launchOpen, casesQuery.data]);

  const caseColumns = useMemo<ColumnsType<FlTestCaseSummary>>(
    () => [
      {
        title: t("用例"),
        dataIndex: "name",
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space size={6}>
            <Typography.Text strong>{value || "-"}</Typography.Text>
            {!row.enabled ? <Tag>{t("停用")}</Tag> : null}
          </Space>
        ),
      },
      testSet?.category === "retrofit"
        ? {
            title: t("口径 / 前置任务"),
            render: (_: unknown, row) => (
              <Space size={6} wrap>
                {row.mode === "feijianxian" ? <Tag color="orange">{t("非建线")}</Tag> : <Tag color="blue">{t("建线")}</Tag>}
                <Typography.Text type="secondary">{row.source_job_name || row.source_job_id || "-"}</Typography.Text>
              </Space>
            ),
          }
        : {
            title: t("计算方式 / 杆塔样例"),
            render: (_: unknown, row) => {
              const tower = (row.params_json?.tower ?? {}) as Record<string, unknown>;
              const label = tower.tower_no || row.tower_no || tower.tower_type || row.line_code || row.line_name || "-";
              return (
                <Space size={6} wrap>
                  {row.calc_kind === "tongtiao" ? <Tag color="purple">{t("同跳计算")}</Tag> : <Tag color="blue">{t("普通计算")}</Tag>}
                  <Typography.Text type="secondary">
                    {String(label)}
                    {tower.tower_model ? ` · ${String(tower.tower_model)}` : ""}
                  </Typography.Text>
                </Space>
              );
            },
          },
      {
        title: t("评估标准"),
        width: 180,
        render: (_: unknown, row) => {
          const metrics = row.expected_json?.metrics;
          const plan = row.expected_json?.plan;
          const summary = metrics?.length
            ? `${t("指标")} × ${metrics.length}`
            : plan
              ? t("参考方案")
              : t("未配置（人工判定）");
          return <Typography.Text type="secondary">{summary}</Typography.Text>;
        },
      },
      {
        title: t("操作"),
        key: "actions",
        width: 140,
        render: (_: unknown, row) => (
          <Space size={4}>
            {canManage ? (
              <Button
                size="small"
                type="link"
                icon={<EditOutlined />}
                onClick={() => {
                  setEditingCase(row);
                  setCaseModalOpen(true);
                }}
              >
                {t("编辑")}
              </Button>
            ) : null}
            {canDelete ? (
              <Popconfirm
                title={t("删除用例")}
                description={t("删除后不可恢复，确认删除？")}
                onConfirm={() => deleteCaseMutation.mutateAsync(row.id)}
              >
                <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                  {t("删除")}
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, testSet?.category, canManage, canDelete],
  );

  const runColumns = useMemo<ColumnsType<FlTestRunSummary>>(
    () => [
      {
        title: t("发起时间"),
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => <Typography.Text>{formatDateTime(value)}</Typography.Text>,
      },
      { title: t("状态"), dataIndex: "status", width: 110, render: (value: string) => <FlTestRunStatusTag status={value} /> },
      {
        title: t("进度"),
        width: 110,
        render: (_: unknown, row) => (
          <Typography.Text>
            {row.finished_cases}/{row.total_cases}
          </Typography.Text>
        ),
      },
      {
        title: t("通过 / 失败 / 待人工"),
        width: 160,
        render: (_: unknown, row) => (
          <Typography.Text type="secondary">
            {row.passed_cases} / {row.failed_cases} / {row.pending_manual_cases}
          </Typography.Text>
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 90,
        render: (_: unknown, row) => (
          <Button size="small" type="link" onClick={() => setRunDrawerId(row.id)}>
            {t("查看")}
          </Button>
        ),
      },
    ],
    [t],
  );

  return (
    <Drawer
      title={
        <Space size={8} wrap>
          <span>{testSet?.name}</span>
          {testSet?.category === "retrofit" ? <Tag color="teal">{t("防雷改造")}</Tag> : <Tag color="blue">{t("防雷计算")}</Tag>}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={960}
      destroyOnClose
    >
      {!testSet ? null : (
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          tabBarExtraContent={
            <Space size={8}>
              <Button icon={<RedoOutlined />} onClick={invalidate}>
                {t("刷新")}
              </Button>
              {activeTab === "cases" && canManage ? (
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    setEditingCase(null);
                    setCaseModalOpen(true);
                  }}
                >
                  {t("新建用例")}
                </Button>
              ) : null}
              {activeTab === "runs" && canRun ? (
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  disabled={enabledCases.length === 0}
                  title={enabledCases.length === 0 ? t("暂无可执行的启用用例") : undefined}
                  onClick={() => setLaunchOpen(true)}
                >
                  {t("发起执行")}
                </Button>
              ) : null}
            </Space>
          }
          items={[
            {
              key: "cases",
              label: `${t("用例")} (${cases.length})`,
              children: (
                <Table<FlTestCaseSummary>
                  rowKey="id"
                  size="small"
                  columns={caseColumns}
                  dataSource={cases}
                  loading={casesQuery.isLoading}
                  pagination={false}
                  scroll={{ y: 480 }}
                  locale={{ emptyText: <Empty description={t("暂无用例，点击右上角「新建用例」录入")} /> }}
                />
              ),
            },
            {
              key: "runs",
              label: `${t("执行历史")} (${runsQuery.data?.total ?? 0})`,
              children: (
                <Table<FlTestRunSummary>
                  rowKey="id"
                  size="small"
                  columns={runColumns}
                  dataSource={runsQuery.data?.items ?? []}
                  loading={runsQuery.isLoading}
                  pagination={false}
                  scroll={{ y: 480 }}
                  locale={{ emptyText: <Empty description={t("暂无执行记录")} /> }}
                />
              ),
            },
          ]}
        />
      )}

      <FlTestCaseModal
        testSet={testSet}
        open={caseModalOpen}
        editingCase={editingCase}
        onClose={() => {
          setCaseModalOpen(false);
          setEditingCase(null);
        }}
        onSaved={() => {
          setCaseModalOpen(false);
          setEditingCase(null);
          invalidate();
        }}
      />

      <Modal
        title={t("发起执行")}
        open={launchOpen}
        onCancel={() => setLaunchOpen(false)}
        confirmLoading={startRunMutation.isPending}
        okText={t("批量发起")}
        onOk={() => startRunMutation.mutateAsync(launchSelection)}
      >
        <Typography.Paragraph type="secondary">
          {t("将为勾选用例逐个创建并启动防雷计算任务（wine 队列串行执行），任务在测试集页内查看，不出现在防雷计算页面。")}
        </Typography.Paragraph>
        <div style={{ maxHeight: 320, overflowY: "auto", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 8, padding: "8px 12px" }}>
          {enabledCases.map((c) => (
            <div key={c.id} style={{ padding: "4px 0" }}>
              <Checkbox
                checked={launchSelection.includes(c.id)}
                onChange={(event) =>
                  setLaunchSelection((prev) => (event.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id)))
                }
              >
                {c.name || c.id}
                <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                  {testSet?.category === "retrofit"
                    ? c.mode === "feijianxian"
                      ? t("非建线")
                      : t("建线")
                    : c.calc_kind === "tongtiao"
                      ? t("同跳计算")
                      : t("普通计算")}
                </Typography.Text>
              </Checkbox>
            </div>
          ))}
          {enabledCases.length === 0 ? <Empty description={t("暂无可执行的启用用例")} /> : null}
        </div>
      </Modal>

      <FlTestRunDrawer runId={runDrawerId} open={!!runDrawerId} onClose={() => setRunDrawerId(null)} />
    </Drawer>
  );
}

// ─────────────────────────── 用例编辑弹窗 ───────────────────────────


function FlTestCaseModal({
  testSet,
  open,
  editingCase,
  onClose,
  onSaved,
}: {
  testSet: FlTestSetSummary | null;
  open: boolean;
  editingCase: FlTestCaseSummary | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const { modal: modalApi } = App.useApp();
  const [form] = Form.useForm();
  const [formKey, setFormKey] = useState("");
  const [sourceJobId, setSourceJobId] = useState<string | undefined>(undefined);
  const [metrics, setMetrics] = useState<FlTestMetric[]>([]);
  const [planMeasures, setPlanMeasures] = useState<string[]>([]);
  const [planAvoids, setPlanAvoids] = useState<string[]>([]);

  const category = testSet?.category ?? "fl_calc";
  const isTongtiao = (Form.useWatch("calc_kind", form) ?? "normal") === "tongtiao";
  // 由历史任务转换的回归用例绑定真实线路（非 FLTC- 托管线路），杆塔快照仅供展示
  const boundRealLine =
    !!editingCase?.line_code && !editingCase.line_code.startsWith("FLTC-");

  useEffect(() => {
    if (!open) return;
    setFormKey(editingCase?.id ?? "new");
    setSourceJobId(editingCase?.source_job_id ?? undefined);
    const expected = editingCase?.expected_json ?? {};
    setMetrics(Array.isArray(expected.metrics) ? expected.metrics : []);
    const plan = (expected.plan ?? {}) as Record<string, unknown>;
    setPlanMeasures(Array.isArray(plan.expected_measures) ? (plan.expected_measures as string[]) : []);
    setPlanAvoids(Array.isArray(plan.unexpected_measures) ? (plan.unexpected_measures as string[]) : []);

    const params = (editingCase?.params_json ?? {}) as Record<string, unknown>;
    const tower = (params.tower ?? {}) as Record<string, unknown>;
    const exec = (params.execution_options_json ?? {}) as Record<string, unknown>;
    const initial: Record<string, unknown> = {
      name: editingCase?.name ?? "",
      description: editingCase?.description ?? "",
      enabled: editingCase?.enabled ?? true,
      calc_kind: editingCase?.calc_kind ?? "normal",
      mode: editingCase?.mode ?? "jianxian",
      source_job_id: editingCase?.source_job_id ?? undefined,
      selected_tower_ids: editingCase?.selected_tower_ids ?? [],
      expected_terminal: (plan.expected_terminal as string) ?? undefined,
      external_adapter: (params.external_adapter as string) ?? "wine",
      ...TOWER_FORM_DEFAULTS,
      ...EXEC_DEFAULTS,
    };
    // 用例里已保存的快照值优先；兼容旧用例（参数直接平铺在 execution_options_json）
    for (const key of [...TOWER_FORM_FIELDS, ...SIM_OVERRIDE_FIELDS]) {
      if (tower[key] !== undefined && tower[key] !== null) initial[key] = tower[key];
    }
    for (const key of EXEC_OPTION_FIELDS) {
      if (exec[key] !== undefined && exec[key] !== null) initial[key] = exec[key];
    }
    form.setFieldsValue(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editingCase]);

  const sourceJobsQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs", "source-options"],
    enabled: open && category === "retrofit",
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?job_types=normal,tongtiao&status=success&limit=200");
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as { items: JobOption[] };
    },
  });

  const sourceTowersQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/source-towers", sourceJobId],
    enabled: open && category === "retrofit" && !!sourceJobId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${sourceJobId}/results?limit=200`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as { items: Array<{ tower_id: string; tower_no: string }> };
    },
  });

  const saveMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      // 编辑时先继承用例已有的快照，避免把导入用例专有的 adapter_config_json、
      // selected_tower_ids、expected_json.baseline 等键覆盖丢失。
      const prevParams = (editingCase?.params_json ?? {}) as Record<string, unknown>;
      const prevExec = (prevParams.execution_options_json ?? {}) as Record<string, unknown>;
      const params: Record<string, unknown> = {
        ...prevParams,
        external_adapter: values.external_adapter ?? prevParams.external_adapter ?? "wine",
        // 绑定真实线路的用例：杆塔参数只读，保存时原样保留快照，不按表单值覆盖
        tower: boundRealLine
          ? (prevParams.tower ?? {})
          : pickFilled(values, [...TOWER_FORM_FIELDS, ...SIM_OVERRIDE_FIELDS]),
        execution_options_json: {
          ...(editingCase ? {} : EXEC_DEFAULTS),
          ...prevExec,
          ...pickFilled(values, EXEC_OPTION_FIELDS),
        },
      };
      const expected: Record<string, unknown> = { ...(editingCase?.expected_json ?? {}) };
      if (category === "fl_calc") {
        expected.metrics = metrics;
        if (!Array.isArray(expected.abnormal_signals)) expected.abnormal_signals = [];
      } else {
        expected.plan = {
          expected_terminal: values.expected_terminal ?? null,
          expected_measures: planMeasures,
          unexpected_measures: planAvoids,
        };
      }
      const body = {
        name: values.name ?? "",
        description: values.description ?? "",
        enabled: values.enabled ?? true,
        ...(category === "fl_calc"
          ? {
              calc_kind: values.calc_kind,
              params_json: params,
            }
          : {
              mode: values.mode,
              source_job_id: values.source_job_id,
              selected_tower_ids: (values.selected_tower_ids as string[]) ?? [],
            }),
        expected_json: expected,
      };
      const url = editingCase
        ? `/api/v1/fl-test-sets/cases/${editingCase.id}`
        : `/api/v1/fl-test-sets/${testSet?.id}/cases`;
      const response = await fetchWithAuth(url, {
        method: editingCase ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: onSaved,
    onError: (error: Error) => modalApi.error({ title: t("保存用例失败"), content: error.message }),
  });

  const jobOptions = sourceJobsQuery.data?.items ?? [];
  const sourceTowerOptions = sourceTowersQuery.data?.items ?? [];

  return (
    <Modal
      title={editingCase ? t("编辑用例") : t("新建用例")}
      open={open}
      onCancel={onClose}
      width={760}
      confirmLoading={saveMutation.isPending}
      okText={t("保存")}
      onOk={() => form.submit()}
    >
      <Form form={form} layout="vertical" key={formKey} onFinish={(values) => saveMutation.mutate(values)}>
        <Row gutter={12}>
          <Col span={14}>
            <Form.Item name="name" label={t("用例名称")} rules={[{ required: true, message: t("请输入用例名称") }]}>
              <Input maxLength={255} placeholder={t("例如：115-ganzi-双避雷线-M123-普通计算")} />
            </Form.Item>
          </Col>
          <Col span={10}>
            <Form.Item name="enabled" label={t("启用")} valuePropName="checked">
              <Switch />
            </Form.Item>
          </Col>
        </Row>

        {category === "fl_calc" ? (
          <Tabs
            size="small"
            items={[
              {
                key: "basic",
                forceRender: true,
                label: t("基本信息"),
                children: (
                  <>
                    <Row gutter={12}>
                      <Col span={12}>
                        <Form.Item name="calc_kind" label={t("计算方式")} required>
                          <Select
                            options={[
                              { value: "normal", label: t("普通计算") },
                              { value: "tongtiao", label: t("同跳计算") },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="external_adapter" label={t("适配器")}>
                          <Select
                            options={[
                              { value: "atp", label: "atp" },
                              { value: "wine", label: "wine" },
                              { value: "placeholder", label: "placeholder" },
                            ]}
                          />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      {boundRealLine
                        ? `此用例由历史任务转换，绑定真实线路 ${editingCase?.line_code ?? ""}；杆塔参数取自该线路，仅供查看，保存不会改变计算载体。`
                        : t("用例自带杆塔参数与计算参数，无需再准备测试线路和测试塔；保存后系统按表单快照托管一基计算塔。")}
                    </Typography.Paragraph>
                  </>
                ),
              },
              {
                key: "tower",
                forceRender: true,
                label: t("杆塔参数"),
                children: (
                  <>
                    {boundRealLine && (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginBottom: 12 }}
                        message={t("杆塔参数为绑定线路的只读展示")}
                        description={t("该用例由历史任务转换，绑定真实线路与杆塔；此处修改不会改变计算载体，回归仍按原线路执行。")}
                      />
                    )}
                    <Typography.Text strong>{t("基本信息")}</Typography.Text>
                    <Row gutter={12} className="mt-2">
                      <Col span={12}>
                        <Form.Item name="tower_no" label={t("塔号")} required>
                          <Input />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="tower_type" label={t("塔型")}>
                          <Input placeholder={t("塔型编码（如 d500shangzi/s500guxing）")} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="tower_model" label={t("模型")}>
                          <Input placeholder={t("塔模型编码，用于带出几何/绝缘默认值")} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="risk_level" label={t("风险等级")}>
                          <Select allowClear options={[{ value: "1", label: "1" }, { value: "2", label: "2" }, { value: "3", label: "3" }]} />
                        </Form.Item>
                      </Col>
                      {([
                        ["longitude", "经度"],
                        ["latitude", "纬度"],
                        ["altitude_m", "海拔(m)"],
                        ["ground_resistance_ohm", "接地电阻(Ω)"],
                        ["lightning_density", "地闪密度"],
                        ["span_small_m", "小号侧档距(m)"],
                        ["span_large_m", "大号侧档距(m)"],
                        ["slope_1", "地面倾角1"],
                        ["slope_2", "地面倾角2"],
                      ] as Array<[string, string]>).map(([name, label]) => (
                        <Col span={12} key={name}>
                          <TowerNumberField name={name} label={label} />
                        </Col>
                      ))}
                    </Row>
                    <Collapse
                      size="small"
                      style={{ marginTop: 12 }}
                      items={[
                        {
                          key: "sim",
                          forceRender: true,
                          label: t("仿真参数（可选覆盖）"),
                          children: (
                            <>
                              <Typography.Paragraph type="secondary">
                                {t("留空时按「模型」编码从塔模型库带出默认值；模型不存在或字段缺失时用系统默认。")}
                              </Typography.Paragraph>
                              <Row gutter={12}>
                                {SIM_NUMBER_LABELS.map(([name, label]) => (
                                  <Col span={8} key={name}>
                                    <TowerNumberField name={name} label={label} />
                                  </Col>
                                ))}
                                {(["a", "b", "c"] as const).map((phase) => (
                                  <Col span={8} key={phase}>
                                    <Form.Item
                                      name={`arrester_${phase}`}
                                      label={t(`${phase.toUpperCase()}相避雷器`)}
                                      valuePropName="checked"
                                      normalize={(value: boolean) => (value ? "是" : "否")}
                                      getValueProps={(value: unknown) => ({ checked: value === "是" })}
                                    >
                                      <Switch />
                                    </Form.Item>
                                  </Col>
                                ))}
                              </Row>
                            </>
                          ),
                        },
                      ]}
                    />
                  </>
                ),
              },
              {
                key: "calc",
                forceRender: true,
                label: t("计算参数"),
                children: (
                  <>
                    {isTongtiao ? (
                      <Typography.Paragraph type="secondary">
                        {t("同跳计算的耐雷水平固定为 ATP、反击跳闸率=规程、绕击跳闸率=EGM，无需选择计算方法。")}
                      </Typography.Paragraph>
                    ) : (
                      <>
                        <Typography.Text strong>{t("计算方法")}</Typography.Text>
                        <Row gutter={12} className="mt-2">
                          <Col span={12}>
                            <Form.Item name="fanji_naleishuiping_method" label={t("反击耐雷水平计算方法")}>
                              <Select options={[{ value: "guicheng", label: t("规程") }, { value: "atp", label: "ATP" }]} />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item name="raoji_naleishuiping_method" label={t("绕击耐雷水平计算方法")}>
                              <Select options={[{ value: "guicheng", label: t("规程") }, { value: "atp", label: "ATP" }]} />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item name="fanji_tzl_method" label={t("反击跳闸率计算方法")}>
                              <Select options={[{ value: "none", label: t("无") }, { value: "guicheng", label: t("规程") }]} />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item name="raoji_tzl_method" label={t("绕击跳闸率计算方法")}>
                              <Select options={[{ value: "none", label: t("无") }, { value: "guicheng", label: t("规程") }, { value: "egm", label: "EGM" }]} />
                            </Form.Item>
                          </Col>
                        </Row>
                      </>
                    )}
                    <Typography.Text strong>{t("高级参数")}</Typography.Text>
                    <Row gutter={12} className="mt-2">
                      <Col span={12}>
                        <Form.Item name="altitude_correction" label={t("是否海拔修正")}>
                          <Select options={[{ value: "none", label: t("无") }, { value: "formula1", label: t("推荐公式1") }, { value: "formula2", label: t("推荐公式2") }]} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="induced_voltage_formula" label={t("感应电压公式")}>
                          <Select options={[{ value: "formula1", label: t("公式1") }, { value: "formula2", label: t("公式2") }]} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="current_waveform" label={t("雷电流波形")}>
                          <Select options={[{ value: "heidler", label: "Heidler" }, { value: "double_slope", label: t("双斜角") }, { value: "double_exponential", label: t("双指数") }]} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="flashover_method" label={t("绝缘子闪络判据")}>
                          <Select options={[{ value: "guideline", label: t("规程法") }, { value: "intersection", label: t("相交法") }, { value: "leader_development", label: t("先导发展法") }]} />
                        </Form.Item>
                      </Col>
                      <Col span={24}>
                        <Form.Item label={t("波头时间(μs)")}>
                          <Space size={8} wrap>
                            <span>{t("最小")}</span>
                            <Form.Item name="head_time_min_us" noStyle><InputNumber min={0.1} step={0.1} precision={2} style={{ width: 110 }} /></Form.Item>
                            <span>{t("最大")}</span>
                            <Form.Item name="head_time_max_us" noStyle><InputNumber min={0.1} step={0.1} precision={2} style={{ width: 110 }} /></Form.Item>
                            <span>{t("步长")}</span>
                            <Form.Item name="head_time_step_us" noStyle><InputNumber min={0.05} step={0.05} precision={2} style={{ width: 110 }} /></Form.Item>
                          </Space>
                        </Form.Item>
                      </Col>
                      <Col span={24}>
                        <Form.Item label={t("波尾时间(μs)")}>
                          <Space size={8} wrap>
                            <span>{t("最小")}</span>
                            <Form.Item name="tail_time_min_us" noStyle><InputNumber min={1} step={1} precision={2} style={{ width: 110 }} /></Form.Item>
                            <span>{t("最大")}</span>
                            <Form.Item name="tail_time_max_us" noStyle><InputNumber min={1} step={1} precision={2} style={{ width: 110 }} /></Form.Item>
                            <span>{t("步长")}</span>
                            <Form.Item name="tail_time_step_us" noStyle><InputNumber min={0.5} step={0.5} precision={2} style={{ width: 110 }} /></Form.Item>
                          </Space>
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item name="binary_search" label={t("二分求耐雷")} valuePropName="checked">
                          <Switch />
                        </Form.Item>
                      </Col>
                    </Row>
                  </>
                ),
              },
              {
                key: "expected",
                forceRender: true,
                label: t("评估标准"),
                children: (
            <div style={{ marginTop: 12 }}>
              <Space size={8} style={{ marginBottom: 8 }}>
                <Typography.Text strong>{t("结果评估标准")}</Typography.Text>
                <Button size="small" onClick={() => setMetrics(METRIC_PRESET_115)}>
                  {t("填入 115kV 模板")}
                </Button>
                <Button size="small" onClick={() => setMetrics(METRIC_PRESET_230)}>
                  {t("填入 230kV 模板")}
                </Button>
                <Button size="small" icon={<PlusOutlined />} onClick={() => setMetrics((prev) => [...prev, { key: "", label: "", min: null, max: null }])}>
                  {t("加一条")}
                </Button>
              </Space>
              {metrics.length === 0 ? (
                <Typography.Paragraph type="secondary">{t("未配置指标时执行结果将标记为「待人工判定」。")}</Typography.Paragraph>
              ) : (
                <Table
                  rowKey={(_, index) => String(index)}
                  size="small"
                  pagination={false}
                  dataSource={metrics}
                  columns={[
                    {
                      title: t("指标键"),
                      width: 220,
                      render: (_: unknown, record: FlTestMetric, index: number) => (
                        <Input
                          size="small"
                          value={record.key}
                          placeholder="counterstrike_withstand_ka"
                          onChange={(event) =>
                            setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, key: event.target.value } : m)))
                          }
                        />
                      ),
                    },
                    {
                      title: t("名称"),
                      width: 140,
                      render: (_: unknown, record: FlTestMetric, index: number) => (
                        <Input
                          size="small"
                          value={record.label}
                          onChange={(event) =>
                            setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, label: event.target.value } : m)))
                          }
                        />
                      ),
                    },
                    {
                      title: t("下限"),
                      width: 100,
                      render: (_: unknown, record: FlTestMetric, index: number) => (
                        <InputNumber
                          size="small"
                          style={{ width: "100%" }}
                          value={record.min ?? undefined}
                          onChange={(value) => setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, min: value } : m)))}
                        />
                      ),
                    },
                    {
                      title: t("上限"),
                      width: 100,
                      render: (_: unknown, record: FlTestMetric, index: number) => (
                        <InputNumber
                          size="small"
                          style={{ width: "100%" }}
                          value={record.max ?? undefined}
                          onChange={(value) => setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, max: value } : m)))}
                        />
                      ),
                    },
                    {
                      title: t("场景"),
                      width: 110,
                      render: (_: unknown, record: FlTestMetric, index: number) => (
                        <Select
                          size="small"
                          allowClear
                          style={{ width: "100%" }}
                          value={record.scope ?? undefined}
                          placeholder={t("全部")}
                          onChange={(value) => setMetrics((prev) => prev.map((m, i) => (i === index ? { ...m, scope: value ?? null } : m)))}
                          options={[
                            { value: "fanji", label: t("反击") },
                            { value: "raoji1", label: `${t("绕击")} A` },
                            { value: "raoji2", label: `${t("绕击")} B` },
                            { value: "raoji3", label: `${t("绕击")} C` },
                          ]}
                        />
                      ),
                    },
                    {
                      title: "",
                      width: 40,
                      render: (_: unknown, _record: FlTestMetric, index: number) => (
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => setMetrics((prev) => prev.filter((_, i) => i !== index))}
                        />
                      ),
                    },
                  ]}
                />
              )}
            </div>
                ),
              },
            ]}
          />
        ) : (
          <>
            <Row gutter={12}>
              <Col span={10}>
                <Form.Item name="mode" label={t("改造口径")} required>
                  <Select
                    options={[
                      { value: "jianxian", label: t("建线") },
                      { value: "feijianxian", label: t("非建线") },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={14}>
                <Form.Item name="source_job_id" label={t("前置防雷计算任务")} required>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    onChange={(value: string) => {
                      setSourceJobId(value);
                      form.setFieldValue("selected_tower_ids", []);
                    }}
                    options={jobOptions.map((j) => ({
                      value: j.id,
                      label: `${j.job_name || j.id}（${j.job_type}）`,
                    }))}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="selected_tower_ids" label={t("改造目标塔（留空默认取前置任务风险杆塔）")}>
              <Select
                mode="multiple"
                allowClear
                maxTagCount={6}
                disabled={!sourceJobId}
                options={sourceTowerOptions.map((tw) => ({ value: tw.tower_id, label: tw.tower_no }))}
              />
            </Form.Item>
            <Row gutter={12}>
              <Col span={10}>
                <Form.Item name="expected_terminal" label={t("期望终态")}>
                  <Select
                    allowClear
                    options={[
                      { value: "S5", label: t("S5 已建线终态") },
                      { value: "S8", label: t("S8 非建线终态") },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={14}>
                <Form.Item label={t("期望措施")}>
                  <Select mode="multiple" allowClear value={planMeasures} onChange={setPlanMeasures} options={MEASURE_OPTIONS.map((m) => ({ value: m, label: m }))} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label={t("不应出现的措施")}>
              <Select mode="multiple" allowClear value={planAvoids} onChange={setPlanAvoids} options={MEASURE_OPTIONS.map((m) => ({ value: m, label: m }))} />
            </Form.Item>
          </>
        )}

        <Form.Item name="description" label={t("说明")}>
          <Input.TextArea rows={2} maxLength={2000} placeholder={t("用例目的、前置条件等")} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
