"use client";

/**
 * 测试集详情抽屉：用例管理（增/改/删/启禁用/排序）+ 执行（全部/勾选/dry_run）+ 执行历史。
 * 用例参数表单：常用字段（计算类型/雷电流/场景）+ 高级 JSON（params_json / expected_json）。
 */
import { useCallback, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import {
  Button,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
  UpOutlined,
  DownOutlined,
  EyeOutlined,
  DownloadOutlined,
  HolderOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type {
  AtpAssetSummary,
  AtpTestSetCase,
  AtpTestSetCaseListResponse,
  AtpTestSetExecuteResponse,
  AtpTestSetRunListResponse,
  AtpTestSetRunSummary,
  AtpTestSetSummary,
} from "@/types/auth";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";
import { AtpTestSetRunDrawer } from "@/components/atp-models/atp-test-set-run-drawer";

const JOB_KIND_OPTIONS = [
  { value: "normal", label: "普通计算" },
  { value: "tongtiao", label: "同跳计算" },
];

export function AtpTestSetDetailDrawer({
  setData,
  open,
  onClose,
  onChanged,
}: {
  setData: AtpTestSetSummary | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { user, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const set = setData;
  const setLoaded = Boolean(open && set);

  const canManage = hasPermission("atp.manage");
  const canTest = hasPermission("atp.run") || hasPermission("atp.manage");

  // ------- 用例 ---------
  const casesQuery = useQuery<AtpTestSetCaseListResponse>({
    queryKey: ["atp-test-set-cases", set?.id],
    enabled: setLoaded,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/${set!.id}/cases`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpTestSetCaseListResponse;
    },
  });

  // ------- 执行历史 ---------
  const runsQuery = useQuery<AtpTestSetRunListResponse>({
    queryKey: ["atp-test-set-runs", set?.id],
    enabled: setLoaded,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/${set!.id}/runs?limit=50`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpTestSetRunListResponse;
    },
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => item.status === "running" || item.status === "pending")
        ? 3000
        : false;
    },
  });

  // ------- 用例编辑弹窗 ---------
  const [caseModalOpen, setCaseModalOpen] = useState(false);
  const [editingCase, setEditingCase] = useState<AtpTestSetCase | null>(null);
  const [caseForm] = Form.useForm();

  // 资产选择：远程搜索
  const [assetKeyword, setAssetKeyword] = useState("");
  const assetsQuery = useQuery<{ items: AtpAssetSummary[]; total: number }>({
    queryKey: ["atp-assets", "picker", assetKeyword.trim()],
    enabled: Boolean(user && caseModalOpen),
    queryFn: async () => {
      const params = new URLSearchParams({ limit: "200" });
      if (assetKeyword.trim()) params.set("keyword", assetKeyword.trim());
      const response = await fetchWithAuth(`/api/v1/atp/assets?${params.toString()}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as { items: AtpAssetSummary[]; total: number };
    },
  });

  const openCreateCase = useCallback(() => {
    setEditingCase(null);
    caseForm.setFieldsValue({
      job_kind: "normal",
      name: "",
      current_ka: 31,
      scene: "",
      stages: "all",
      params_extra: "",
      expected_extra: "",
    });
    setAssetKeyword("");
    setCaseModalOpen(true);
  }, [caseForm]);

  const openEditCase = useCallback((item: AtpTestSetCase) => {
    setEditingCase(item);
    const params = item.params_json ?? {};
    const { current_ka: editCurrentKa, scene: editScene, stages: editStages, ...restParams } = params;
    caseForm.setFieldsValue({
      asset_id: item.asset_id,
      job_kind: item.job_kind,
      name: item.name,
      current_ka: editCurrentKa ?? 31,
      scene: typeof editScene === "string" ? editScene : "",
      stages: Array.isArray(editStages) ? (editStages as string[]).join(",") : "all",
      // 高级 JSON 只放常用字段之外的部分，避免 stages 数组被重复展开
      params_extra: Object.keys(restParams).length ? JSON.stringify(restParams) : "",
      expected_extra: Object.keys(item.expected_json ?? {}).length
        ? JSON.stringify(item.expected_json)
        : "",
      enabled: item.enabled,
    });
    setAssetKeyword("");
    setCaseModalOpen(true);
  }, [caseForm]);

  const saveCaseMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      const params: Record<string, unknown> = {};
      const currentKa = values.current_ka;
      if (typeof currentKa === "number" && currentKa > 0) params.current_ka = currentKa;
      const scene = (values.scene as string)?.trim();
      if (scene) params.scene = scene;
      const stagesRaw = (values.stages as string)?.trim();
      if (stagesRaw && stagesRaw !== "all") {
        params.stages = stagesRaw.split(",").map((s: string) => s.trim()).filter(Boolean);
      }
      // 高级 JSON 合并（覆盖同名键）
      let paramsExtra: Record<string, unknown> = {};
      try {
        const raw = (values.params_extra as string)?.trim();
        if (raw) paramsExtra = JSON.parse(raw);
      } catch {
        throw new Error(t("测试参数(高级)不是合法 JSON"));
      }
      let expectedExtra: Record<string, unknown> = {};
      try {
        const raw = (values.expected_extra as string)?.trim();
        if (raw) expectedExtra = JSON.parse(raw);
      } catch {
        throw new Error(t("预期结果(高级)不是合法 JSON"));
      }
      const body = {
        asset_id: values.asset_id,
        job_kind: values.job_kind,
        name: (values.name as string) ?? "",
        params_json: { ...params, ...paramsExtra },
        expected_json: expectedExtra,
        enabled: values.enabled !== false,
      };
      if (editingCase) {
        const response = await fetchWithAuth(`/api/v1/atp/test-sets/cases/${editingCase.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return (await response.json()) as AtpTestSetCase;
      }
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/${set!.id}/cases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpTestSetCase;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-set-cases", set?.id] });
      void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
      message.success(editingCase ? t("用例已更新") : "用例已添加");
      setCaseModalOpen(false);
      onChanged();
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : t("保存用例失败"));
    },
  });

  const deleteCaseMutation = useMutation({
    mutationFn: async (caseId: string) => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/cases/${caseId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-set-cases", set?.id] });
      void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
      message.success(t("用例已删除"));
      onChanged();
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : t("删除用例失败"));
    },
  });

  const toggleCaseMutation = useMutation({
    mutationFn: async ({ caseId, enabled }: { caseId: string; enabled: boolean }) => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/cases/${caseId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-set-cases", set?.id] });
    },
  });

  const moveCaseMutation = useMutation({
    mutationFn: async ({ caseId, dir }: { caseId: string; dir: -1 | 1 }) => {
      const items = casesQuery.data?.items ?? [];
      const index = items.findIndex((item) => item.id === caseId);
      if (index < 0) return;
      const target = index + dir;
      if (target < 0 || target >= items.length) return;
      const reordered = items.map((item) => item.id);
      const [moved] = reordered.splice(index, 1);
      reordered.splice(target, 0, moved);
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/${set!.id}/cases/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_ids: reordered }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-set-cases", set?.id] });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : t("调整顺序失败"));
    },
  });

  // ------- 执行 ---------
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const [runOptionsOpen, setRunOptionsOpen] = useState(false);
  const [executeDryRun, setExecuteDryRun] = useState(false);
  const [executing, setExecuting] = useState(false);

  const executeSet = useCallback(
    async (dryRun: boolean) => {
      if (!set) return;
      setExecuting(true);
      try {
        const body: Record<string, unknown> = { dry_run: dryRun };
        if (selectedCaseIds.length > 0) body.case_ids = selectedCaseIds;
        const response = await fetchWithAuth(`/api/v1/atp/test-sets/${set.id}/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        const result = (await response.json()) as AtpTestSetExecuteResponse;
        if (result.launched === 0) {
          message.warning(t("执行未启动（0 个用例派发成功）"));
        } else {
          message.success(`已发起 ${result.launched} 个用例执行（批次 ${result.run_id.slice(0, 12)}…）`);
        }
        void queryClient.invalidateQueries({ queryKey: ["atp-test-set-runs", set.id] });
        void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
        onChanged();
        setSelectedCaseIds([]);
      } catch (error) {
        message.error(error instanceof Error ? error.message : t("发起执行失败"));
      } finally {
        setExecuting(false);
        setRunOptionsOpen(false);
      }
    },
    [set, selectedCaseIds, queryClient, onChanged],
  );

  // ------- 执行历史查看 ---------
  const [viewRunId, setViewRunId] = useState<string | null>(null);

  const downloadRunReport = useCallback(
    async (runId: string) => {
      try {
        const response = await fetchWithAuth(`/api/v1/atp/test-sets/runs/${runId}/report`);
        if (!response.ok) throw new Error(await readApiError(response));
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `atp-test-set-${runId}.zip`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
      } catch (error) {
        message.error(error instanceof Error ? error.message : t("报告下载失败"));
      }
    },
    [],
  );

  const caseColumns = useMemo<ColumnsType<AtpTestSetCase>>(
    () => [
      {
        title: t("顺序"),
        dataIndex: "sort_order",
        width: 90,
        render: (value: number, row) => (
          <Space size={2}>
            <HolderOutlined style={{ color: "#bbb" }} />
            <span style={{ color: "#999", fontSize: 12 }}>{value}</span>
            <Space size={0}>
              <Button
                type="text"
                size="small"
                style={{ padding: 0 }}
                icon={<UpOutlined />}
                disabled={!canManage}
                onClick={() => moveCaseMutation.mutate({ caseId: row.id, dir: -1 })}
              />
              <Button
                type="text"
                size="small"
                style={{ padding: 0 }}
                icon={<DownOutlined />}
                disabled={!canManage}
                onClick={() => moveCaseMutation.mutate({ caseId: row.id, dir: 1 })}
              />
            </Space>
          </Space>
        ),
      },
      {
        title: t("用例"),
        dataIndex: "name",
        width: 150,
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text ellipsis={{ tooltip: value || row.id }} style={{ maxWidth: 140 }}>
              {value || row.id}
            </Typography.Text>
            {!row.enabled ? <Tag>{t("已禁用")}</Tag> : null}
          </Space>
        ),
      },
      {
        title: t("计算类型"),
        dataIndex: "job_kind",
        width: 90,
        render: (value: string) =>
          value === "tongtiao" ? (
            <Tag color="purple">{t("同跳计算")}</Tag>
          ) : (
            <Tag color="blue">{t("普通计算")}</Tag>
          ),
      },
      {
        title: t("模型"),
        dataIndex: "asset_code",
        width: 150,
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text ellipsis={{ tooltip: value }} style={{ maxWidth: 140, fontSize: 12 }}>
              {value}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {[row.voltage_level, row.tower_type, row.scene_type].filter(Boolean).join("/") ||
                "-"}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: t("测试参数"),
        key: "params",
        width: 180,
        render: (_, row) => {
          const params = row.params_json ?? {};
          const parts: string[] = [];
          if (params.current_ka) parts.push(`雷电流 ${params.current_ka}kA`);
          if (params.scene) parts.push(`场景 ${params.scene}`);
          if (Array.isArray(params.stages) && !(params.stages as string[]).includes("all")) {
            parts.push(`阶段 ${(params.stages as string[]).join(",")}`);
          }
          return (
            <Typography.Text style={{ fontSize: 12 }} type="secondary">
              {parts.length ? parts.join(" · ") : t("默认参数")}
            </Typography.Text>
          );
        },
      },
      {
        title: t("预期结果"),
        key: "expected",
        width: 120,
        render: (_, row) => {
          const expected = row.expected_json ?? {};
          return Object.keys(expected).length > 0 ? (
            <Typography.Text style={{ fontSize: 12 }} code>
              {JSON.stringify(expected)}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              -
            </Typography.Text>
          );
        },
      },
      {
        title: t("启用"),
        dataIndex: "enabled",
        width: 70,
        render: (value: boolean, row) => (
          <Switch
            size="small"
            checked={value}
            disabled={!canManage || toggleCaseMutation.isPending}
            onChange={(checked) => toggleCaseMutation.mutate({ caseId: row.id, enabled: checked })}
          />
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 130,
        fixed: "right" as const,
        render: (_, row) => (
          <Space size={4}>
            {canManage ? (
              <>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  icon={<EditOutlined />}
                  onClick={() => openEditCase(row)}
                >
                  编辑
                </Button>
                <Popconfirm
                  title={t("删除该用例？")}
                  okText={t("删除")}
                  cancelText={t("取消")}
                  okButtonProps={{ danger: true }}
                  onConfirm={() => deleteCaseMutation.mutate(row.id)}
                >
                  <Button type="link" size="small" danger style={{ padding: 0 }} icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              </>
            ) : null}
          </Space>
        ),
      },
    ],
    [canManage, moveCaseMutation, deleteCaseMutation, openEditCase, toggleCaseMutation],
  );

  const runHistoryColumns = useMemo<ColumnsType<AtpTestSetRunSummary>>(
    () => [
      {
        title: t("批次"),
        dataIndex: "run_id",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string) => (
          <Typography.Text code ellipsis={{ tooltip: value }} style={{ maxWidth: 190 }}>
            {value.slice(0, 16)}
          </Typography.Text>
        ),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        width: 100,
        render: (value: string) =>
          value === "running" || value === "pending" ? (
            <Tag color="processing">{t("运行中")}</Tag>
          ) : value === "success" ? (
            <Tag color="green">{t("成功")}</Tag>
          ) : (
            <Tag color="red">{t("有失败")}</Tag>
          ),
      },
      {
        title: t("总数"),
        dataIndex: "total_cases",
        width: 70,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("成功/失败"),
        key: "counts",
        width: 110,
        render: (_, row) => (
          <Space size={6}>
            <Typography.Text style={{ color: "#3f8600" }}>{row.counts.success}</Typography.Text>
            <span>/</span>
            <Typography.Text style={{ color: "#cf1322" }}>{row.counts.failed}</Typography.Text>
          </Space>
        ),
      },
      {
        title: t("通过率"),
        key: "pass",
        width: 90,
        render: (_, row) => {
          const done = row.counts.success + row.counts.failed;
          const percent = row.total_cases > 0 ? Math.round((done / row.total_cases) * 100) : 0;
          return (
            <Typography.Text strong>
              {row.status === "running" || row.status === "pending" ? `${percent}%` : `${row.report?.overall_pass_rate ?? percent}%`}
            </Typography.Text>
          );
        },
      },
      {
        title: t("发起时间"),
        dataIndex: "create_date",
        width: 165,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("发起人"),
        dataIndex: "create_user",
        width: 100,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      {
        title: t("操作"),
        key: "actions",
        width: 150,
        fixed: "right" as const,
        render: (_, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<EyeOutlined />}
              onClick={() => setViewRunId(row.run_id)}
            >
              查看
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<DownloadOutlined />}
              onClick={() => void downloadRunReport(row.run_id)}
            >
              报告
            </Button>
          </Space>
        ),
      },
    ],
    [downloadRunReport],
  );

  const jobsOffered = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of casesQuery.data?.items ?? []) {
      counts[item.job_kind] = (counts[item.job_kind] ?? 0) + 1;
    }
    return counts;
  }, [casesQuery.data]);

  return (
    <>
      <Drawer
        title={
          set ? (
            <Space size={8}>
              <span>{set.name}</span>
              <Tag>{set.case_count} {t("用例")}</Tag>
              {set.status === "disabled" ? <Tag>{t("已停用")}</Tag> : null}
            </Space>
          ) : (
            <span>{t("测试集")}</span>
          )
        }
        open={open}
        onClose={onClose}
        width={1120}
        destroyOnHidden
        extra={
          <Space>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              disabled={!canTest || !set || set.case_count === 0}
              loading={executing}
              onClick={() => void executeSet(false)}
            >
              {t("执行测试集")}
            </Button>
          </Space>
        }
      >
        {!set ? null : (
          <Tabs
            items={[
              {
                key: "cases",
                label: `用例管理（${casesQuery.data?.total ?? 0}）`,
                children: (
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    {/* 工具条：新增用例 + 勾选执行提示 */}
                    <div className="admin-filter-bar">
                      <Space size={8}>
                        {canManage ? (
                          <Button
                            type="primary"
                            icon={<PlusOutlined />}
                            onClick={openCreateCase}
                          >
                            新增用例
                          </Button>
                        ) : null}
                        {canTest ? (
                          <Button
                            icon={<ExperimentOutlined />}
                            disabled={casesQuery.data?.total === 0}
                            onClick={() => setRunOptionsOpen((previous) => !previous)}
                          >
                            {selectedCaseIds.length > 0
                              ? `${t("勾选")} ${selectedCaseIds.length} ${t("个执行")}`
                              : t("勾选执行")}
                          </Button>
                        ) : null}
                        <Button
                          icon={<ReloadOutlined />}
                          onClick={() => {
                            void queryClient.invalidateQueries({
                              queryKey: ["atp-test-set-cases", set.id],
                            });
                          }}
                        >
                          刷新
                        </Button>
                      </Space>
                    </div>
                    {runOptionsOpen ? (
                      <div
                        style={{
                          padding: 12,
                          border: "1px solid var(--ant-color-border-secondary)",
                          borderRadius: 8,
                          display: "flex",
                          gap: 16,
                          alignItems: "center",
                          flexWrap: "wrap",
                        }}
                      >
                        <Checkbox
                          checked={selectedCaseIds.length > 0}
                          indeterminate={selectedCaseIds.length > 0 &&
                            selectedCaseIds.length < (casesQuery.data?.items.length ?? 0)}
                          onChange={(event) =>
                            setSelectedCaseIds(
                              event.target.checked
                                ? (casesQuery.data?.items ?? [])
                                    .filter((item) => item.enabled)
                                    .map((item) => item.id) ?? []
                                : [],
                            )
                          }
                        >
                          全选启用的用例
                        </Checkbox>
                        <Radio.Group
                          value={executeDryRun}
                          onChange={(event) => setExecuteDryRun(event.target.value === true)}
                          optionType="button"
                          buttonStyle="solid"
                          options={[
                            { value: false, label: t("真实仿真") },
                            { value: true, label: t("试运行(dry-run)") },
                          ]}
                        />
                        <Button
                          type="primary"
                          size="small"
                          loading={executing}
                          onClick={() => void executeSet(executeDryRun)}
                        >
                          {t("开始执行")}
                        </Button>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {jobsOffered.normal ? `普通 ${jobsOffered.normal} 个 · ` : ""}
                          {jobsOffered.tongtiao ? `同跳 ${jobsOffered.tongtiao} 个` : ""}
                        </Typography.Text>
                      </div>
                    ) : null}
                    <Table<AtpTestSetCase>
                      rowKey="id"
                      size="small"
                      loading={casesQuery.isFetching}
                      dataSource={casesQuery.data?.items ?? []}
                      columns={caseColumns}
                      tableLayout="fixed"
                      scroll={{ x: 980, y: 340 }}
                      pagination={false}
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("暂无用例。点击「新增用例」为测试集添加模型与计算类型的测试用例。")}
                          />
                        ),
                      }}
                    />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      用例自动按顺序执行 · 勾选「勾选执行」可只跑选中用例 · 试运行只检查命令与参数不真正仿真
                    </Typography.Text>
                  </Space>
                ),
              },
              {
                key: "history",
                label: `执行历史（${runsQuery.data?.total ?? 0}）`,
                children: (
                  <Table<AtpTestSetRunSummary>
                    rowKey="run_id"
                    size="small"
                    loading={runsQuery.isFetching}
                    dataSource={runsQuery.data?.items ?? []}
                    columns={runHistoryColumns}
                    tableLayout="fixed"
                    scroll={{ x: 980, y: 420 }}
                    pagination={false}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无执行记录。点击「执行测试集」发起一次批量仿真测试。")}
                        />
                      ),
                    }}
                  />
                ),
              },
            ]}
          />
        )}
      </Drawer>

      {/* 用例编辑弹窗 */}
      <Modal
        title={editingCase ? t("编辑用例") : "新增用例"}
        open={caseModalOpen}
        onCancel={() => setCaseModalOpen(false)}
        onOk={() => void caseForm.submit()}
        confirmLoading={saveCaseMutation.isPending}
        destroyOnHidden
        okText={saveCaseMutation.isPending ? t("提交中...") : editingCase ? t("保存") : "添加"}
        cancelText={t("取消")}
        width={720}
      >
        <Form
          form={caseForm}
          layout="vertical"
          onFinish={(values) => void saveCaseMutation.mutateAsync(values)}
          autoComplete="off"
        >
          <div className="grid gap-x-4 md:grid-cols-2">
            <Form.Item
              name="job_kind"
              label={t("计算类型")}
              rules={[{ required: true, message: t("请选择计算类型") }]}
            >
              <Select options={JOB_KIND_OPTIONS.map((o) => ({ ...o, label: t(o.label) }))} />
            </Form.Item>
            <Form.Item name="name" label={t("用例名称")}>
              <Input placeholder={t("如：普通计算-110kV-反击-酒杯塔（可空）")} maxLength={255} />
            </Form.Item>
            <Form.Item
              name="asset_id"
              label={t("ATP 模型")}
              rules={[{ required: true, message: t("请选择模型") }]}
              className="md:col-span-2"
            >
              <Select
                showSearch
                filterOption={false}
                onSearch={setAssetKeyword}
                loading={assetsQuery.isFetching}
                placeholder={t("搜索并选择模型（输入编码/名称过滤）")}
                options={(assetsQuery.data?.items ?? []).map((asset) => ({
                  value: asset.id,
                  label: `${asset.code} · ${[asset.voltage_level, asset.tower_type, asset.scene_type, asset.arrester_config].filter(Boolean).join("/") || t("无维度")}`,
                }))}
              />
            </Form.Item>
            <Form.Item name="current_ka" label={t("雷电流(kA)")}>
              <InputNumber min={0.1} max={500} step={0.5} style={{ width: "100%" }} placeholder={t("默认 31")} />
            </Form.Item>
            <Form.Item name="scene" label={t("场景")}>
              <Input placeholder={t("如 fanji / raoji1（可空，用默认）")} />
            </Form.Item>
            <Form.Item name="stages" label={t("测试阶段")} className="md:col-span-1">
              <Input placeholder={t("materialize,geometry,simulate（留空=全部）")} />
            </Form.Item>
            <Form.Item name="expected_extra" label={t("预期结果(JSON，可选)")} className="md:col-span-2">
              <Input.TextArea
                rows={2}
                placeholder='如 {"flashover_count": 2}（回归断言；可空）'
              />
            </Form.Item>
            <Form.Item
              name="params_extra"
              label={t("测试参数(JSON 高级，可选)")}
              className="md:col-span-2"
              extra='如 {"params_source":"tower","execution_options":{"method_raoji":"egm"}}'
            >
              <Input.TextArea rows={2} placeholder={t("留空则只用上面的常用字段")} />
            </Form.Item>
            <Form.Item name="enabled" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Checkbox defaultChecked>{t("启用该用例（执行时默认包含）")}</Checkbox>
            </Form.Item>
          </div>
        </Form>
      </Modal>

      {/* 执行结果抽屉 */}
      <AtpTestSetRunDrawer
        runId={viewRunId}
        open={Boolean(viewRunId)}
        onClose={() => setViewRunId(null)}
      />
    </>
  );
}
