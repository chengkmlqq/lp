"use client";

// 防雷改造（合并页，2026-09-27）：
// 由 4 个页面（任务列表 / 高杆塔成因分析 / 改造措施推荐 / 措施推荐(非建线)）合并而来，
// 外层 2 个 Tab：①任务列表 ②成因分析与措施推荐（内部用「任务类型」Segmented 切换）。
// 后端逻辑对齐 C# MyCanShu_2/MyCanShu_3 状态机（普通计算/同跳任务作前驱）。

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent } from "react";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import { formatDateTime, riskColor } from "@/components/fl-analysis/types";
import { statusColor } from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

const LIST_TAB_KEY = "jobs";
const WORK_TAB_KEY = "work";
const TASK_MODE_REASON = "reason";
const TASK_MODE_MEASURE = "measure";
const TASK_MODE_NONNEW = "measure_nonnew";
type TaskMode = typeof TASK_MODE_REASON | typeof TASK_MODE_MEASURE | typeof TASK_MODE_NONNEW;

type DetailTabItem = {
  key: string;
  label: React.ReactNode;
  closable: boolean;
  children: React.ReactNode;
};

type RetrofitTaskItem = FlAnalysisJobSummary & {
  retrofit_type?: string | null;
};

type TowerSelectionRow = {
  id: string;
  tower_id: string;
  tower_no: string | null;
  risk_level: string | null;
  status: string | null;
  include: boolean;
};

export default function AdminLightningRetrofitPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [messageApi, contextHolder] = message.useMessage();
  const queryClient = useQueryClient();

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

  // ── Tab / 任务类型 ──────────────────────────────────────────────
  // 动态选项卡（严格参照线路管理）：固定「任务列表」+「成因分析与措施推荐」，
  // 点任务「查看详情」在当前页 append 动态详情 tab（不跳转页面），可关闭
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [taskMode, setTaskMode] = useState<TaskMode>(TASK_MODE_REASON);

  // ── 任务列表（Tab1）────────────────────────────────────────────
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchNonce, setSearchNonce] = useState(0);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // ── 成因分析（Tab2 / reason）────────────────────────────────────
  const [lines, setLines] = useState<FlAnalysisJobSummary[]>([]);
  const [loadingLines, setLoadingLines] = useState(false);
  const [lineId, setLineId] = useState<string>("");
  const [detailVisible, setDetailVisible] = useState(false);
  const [selectedRow, setSelectedRow] = useState<FlAnalysisTowerResultSummary | null>(null);

  // ── 措施推荐（Tab2 / measure*）─────────────────────────────────
  const [baseJobs, setBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [selectedBaseJobId, setSelectedBaseJobId] = useState<string>("");
  const [towerRows, setTowerRows] = useState<TowerSelectionRow[]>([]);
  const [jobName, setJobName] = useState("");
  const [creating, setCreating] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const selectedBaseJob = useMemo(
    () => baseJobs.find((job) => job.id === selectedBaseJobId) ?? null,
    [baseJobs, selectedBaseJobId],
  );

  // ── 任务列表查询（Tab1）────────────────────────────────────────
  const jobsListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    const query = params.toString();
    return `/api/v1/fl-analysis/jobs${query ? `?${query}` : ""}`;
  }, [keyword, paginationCurrent, paginationPageSize]);

  const jobsQuery = useQuery({
    queryKey: [jobsListPath, searchNonce],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(jobsListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisJobListResponse;
    },
    placeholderData: (previousData) => previousData,
  });

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const total = jobsQuery.data?.total ?? 0;

  const handleSearch = () => {
    setKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setSearchNonce((n) => n + 1);
  };

  const handleDeleteJob = async (job: FlAnalysisJobSummary) => {
    const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${job.id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    await jobsQuery.refetch();
    messageApi.success(`已删除防雷改造任务：${job.job_name || job.line_name || job.id}`);
  };

  // 查看详情 → 当前页动态追加详情 tab（严格参照线路管理 openDetail，不跳转页面）
  const handleViewDetail = (job: FlAnalysisJobSummary) => {
    const key = job.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span className="admin-power-lines-tab-title">防雷改造详情 - {job.job_name || job.line_name || job.line_code || job.id}</span>,
          closable: true,
          children: <RetrofitJobDetail jobId={job.id} />,
        },
      ];
    });
    setActiveTabKey(key);
  };

  const handleTabsEdit = useCallback(
    (targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
      if (action !== "remove") {
        return;
      }
      const key = String(targetKey);
      const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
      const next = detailTabs.filter((tab) => tab.key !== key);
      setDetailTabs(next);
      if (activeTabKey === key) {
        const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
        setActiveTabKey(fallback);
      }
    },
    [detailTabs, activeTabKey],
  );

  // ── 成因分析数据（Tab2 / reason）───────────────────────────────
  const loadLines = useCallback(async () => {
    setLoadingLines(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as { items: FlAnalysisJobSummary[] };
      const seen = new Set<string>();
      const distinctLines: FlAnalysisJobSummary[] = [];
      for (const item of data.items) {
        const key = item.line_id || item.id;
        if (!key || seen.has(key)) {
          continue;
        }
        seen.add(key);
        distinctLines.push(item);
      }
      setLines(distinctLines);
    } catch (error) {
      setLines([]);
    } finally {
      setLoadingLines(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    if (!user || !canRead) {
      return;
    }
    void loadLines();
  }, [user, canRead, loadLines]);

  // 从任务列表 ?jobId= 跳转：预选线路（成因分析模式）
  useEffect(() => {
    if (!user || !canRead) {
      return;
    }
    const jobIdFromUrl = new URLSearchParams(window.location.search).get("jobId");
    if (!jobIdFromUrl) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobIdFromUrl}`);
        if (!response.ok) {
          return;
        }
        const data = (await response.json()) as { job: FlAnalysisJobSummary };
        const targetLineId = data.job?.line_id;
        if (!cancelled && targetLineId) {
          // ?jobId= 直达：打开该任务详情动态 tab（不跳转）；成因分析工作区不再预选线路
          handleViewDetail(data.job);
        }
      } catch {
        // 预选失败不阻断页面
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, canRead, fetchWithAuth]);

  const highRiskQueryPath = useMemo(() => {
    if (!lineId) {
      return null;
    }
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    return `/api/v1/lightning-retrofit/high-risk-reason?line_id=${lineId}${params.toString() ? `&${params.toString()}` : ""}`;
  }, [lineId, paginationCurrent, paginationPageSize]);

  const highRiskQuery = useQuery({
    queryKey: ["/admin/lightning-retrofit/high-risk-reason", lineId, paginationCurrent, paginationPageSize],
    enabled: !!user && canRead && Boolean(lineId),
    queryFn: async () => {
      const response = await fetchWithAuth(highRiskQueryPath as string);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as {
        items: FlAnalysisTowerResultSummary[];
        total: number;
      };
    },
  });

  const riskRows = useMemo(() => highRiskQuery.data?.items ?? [], [highRiskQuery.data?.items]);
  const riskTotal = highRiskQuery.data?.total ?? 0;

  const handleExport = () => {
    const headers = "塔号,风险等级,原因类型,状态\n";
    const rows = riskRows
      .map((row) => `${row.tower_no},${row.risk_level ?? "-"},${readReasonType(row)},${row.status}`)
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "高风险原因分析.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // ── 措施推荐数据（Tab2 / measure*）─────────────────────────────
  const loadBaseJobs = useCallback(async () => {
    setLoadingJobs(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as { items: FlAnalysisJobSummary[] };
      const matched = data.items.filter((item) => item.job_type === "normal" || item.job_type === "tongtiao");
      setBaseJobs(matched);
    } catch (error) {
      setBaseJobs([]);
    } finally {
      setLoadingJobs(false);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    void loadBaseJobs();
  }, [loadBaseJobs]);

  const towerQueryPath = useMemo(() => {
    if (!selectedBaseJobId) return null;
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    return `/api/v1/fl-analysis/jobs/${selectedBaseJobId}/results?${params.toString()}`;
  }, [selectedBaseJobId, paginationCurrent, paginationPageSize]);

  const towerQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs", selectedBaseJobId, "results", paginationCurrent, paginationPageSize],
    enabled: !!user && canRead && Boolean(selectedBaseJobId),
    queryFn: async () => {
      const response = await fetchWithAuth(towerQueryPath as string);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as {
        items: FlAnalysisTowerResultSummary[];
        total: number;
      };
    },
  });

  const computedTowerRows = useMemo(() => {
    const items = towerQuery.data?.items ?? [];
    return items.map((row) => ({
      id: row.id,
      tower_id: row.tower_id,
      tower_no: row.tower_no,
      risk_level: row.risk_level,
      status: row.status,
      include: isHighRisk(row.risk_level),
    }));
  }, [towerQuery.data?.items]);

  useEffect(() => {
    setTowerRows(computedTowerRows);
  }, [computedTowerRows]);

  const towerTotal = towerQuery.data?.total ?? 0;

  const toggleTowerInclude = (rowId: string) => {
    setTowerRows((previous) =>
      previous.map((row) => (row.id === rowId ? { ...row, include: !row.include } : row)),
    );
  };

  const handleBaseJobChange = (nextJobId: string) => {
    setSelectedBaseJobId(nextJobId);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setErrorMessage("");
  };

  const handleCreateJob = async () => {
    if (!selectedBaseJob) {
      setErrorMessage("请先选择前置任务");
      return;
    }
    const selectedTowers = towerRows.filter((row) => row.include);
    if (selectedTowers.length === 0) {
      setErrorMessage("请至少包含一个杆塔");
      return;
    }
    setCreating(true);
    setErrorMessage("");
    try {
      const isNonNew = taskMode === TASK_MODE_NONNEW;
      const payload = {
        line_id: selectedBaseJob.line_id,
        job_name:
          jobName.trim() ||
          `${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "防雷任务"}-${isNonNew ? "措施推荐(非建线)" : "措施推荐"}`,
        job_type: "mitigation",
        execution_options_json: {
          non_construction: isNonNew,
          source_job_id: selectedBaseJob.id,
          selected_tower_ids: selectedTowers.map((row) => row.tower_id),
        },
      };
      const createResponse = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!createResponse.ok) {
        throw new Error(await readApiError(createResponse));
      }
      const created = (await createResponse.json()) as { job: FlAnalysisJobSummary };
      const startResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${created.job.id}/start`, {
        method: "POST",
      });
      if (!startResponse.ok) {
        throw new Error(await readApiError(startResponse));
      }
      messageApi.success(`措施推荐任务已创建并启动：${created.job.job_name || created.job.id}`);
      setJobName("");
      setSelectedBaseJobId("");
      await Promise.all([loadBaseJobs(), invalidateMeasureQueries()]);
      // 切回任务列表看新任务
      setActiveTabKey(LIST_TAB_KEY);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "措施推荐任务创建失败");
    } finally {
      setCreating(false);
    }
  };

  const invalidateMeasureQueries = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0]?.startsWith?.("/api/v1/fl-analysis/jobs"),
    });
  }, [queryClient]);

  useTopicSubscription("admin.fl-analysis", useCallback(() => {
    void invalidateMeasureQueries();
  }, [invalidateMeasureQueries]));

  useTopicSubscription("admin.lightning-retrofit", useCallback(() => {
    void queryClient.invalidateQueries({
      predicate: (query) => Array.isArray(query.queryKey) && String(query.queryKey[0]).includes("lightning-retrofit"),
    });
  }, [queryClient]));

  // ── 动态表体高度（共用）─────────────────────────────────────────
  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const anchorTop = anchor.getBoundingClientRect().top;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? TABLE_HEADER_HEIGHT;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? TABLE_PAGINATION_HEIGHT;
    const available = window.innerHeight - anchorTop - TABLE_BOTTOM_GAP;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16);
    const clampedHeight = Math.max(TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || viewMode !== "list") {
      return;
    }
    const frameId = window.requestAnimationFrame(updateTableScrollHeight);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollHeight, jobs.length, riskRows.length, towerRows.length, viewMode, activeTabKey]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined" || viewMode !== "list") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollHeight);
    });
    resizeObserver.observe(anchor);
    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollHeight, viewMode, activeTabKey]);

  useToastFeedback({
    errorMessage:
      jobsQuery.error instanceof Error ? jobsQuery.error.message : "",
    successMessage: "",
    clearError: () => {},
    clearSuccess: () => {},
  });

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再访问防雷改造页面。</Typography.Text>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `line.manage`）。</Typography.Text>
        </Space>
      </Card>
    );
  }

  const taskModeOptions = [
    { label: "高杆塔成因分析", value: TASK_MODE_REASON },
    { label: "改造措施推荐", value: TASK_MODE_MEASURE },
    { label: "措施推荐（非建线）", value: TASK_MODE_NONNEW },
  ];

  const handleTaskModeChange = (value: TaskMode) => {
    setTaskMode(value);
    setErrorMessage("");
    setSelectedBaseJobId("");
    setLineId("");
    setJobName("");
    setTowerRows([]);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col">
        <Tabs
          type="editable-card"
          hideAdd
          activeKey={activeTabKey}
          onChange={setActiveTabKey}
          onEdit={handleTabsEdit}
          className="admin-power-lines-tabs"
          items={[
            {
              key: LIST_TAB_KEY,
              label: <span className="admin-power-lines-tab-title">任务列表</span>,
              closable: false,
              children: renderJobsPane(),
            },
            {
              key: WORK_TAB_KEY,
              label: <span className="admin-power-lines-tab-title">成因分析与措施推荐</span>,
              closable: false,
              children: renderWorkPane(),
            },
            ...detailTabs,
          ]}
        />
      </div>

      {/* 成因分析：杆塔详情弹窗 */}
      <Modal
        title="杆塔详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={<Button onClick={() => setDetailVisible(false)}>关闭</Button>}
        width={720}
      >
        {selectedRow ? (
          <Space direction="vertical" size={12} className="flex w-full">
            <Alert
              type="warning"
              showIcon
              message={`高风险杆塔：${selectedRow.tower_no || selectedRow.tower_id}`}
              description={`风险等级：${selectedRow.risk_level ?? "-"}；状态：${selectedRow.status}`}
            />
            <Typography.Text>原因详情：</Typography.Text>
            <Typography.Text type="secondary">
              {typeof selectedRow.result_json?.cause_analysis === "string"
                ? selectedRow.result_json.cause_analysis
                : JSON.stringify(selectedRow.result_json ?? {}, null, 2)}
            </Typography.Text>
          </Space>
        ) : null}
      </Modal>
    </>
  );

  // ── Tab1：任务列表 ──────────────────────────────────────────────
  function renderJobsPane() {
    const columns: ColumnsType<RetrofitTaskItem> = [
      {
        title: "任务名",
        dataIndex: "job_name",
        key: "job_name",
        ellipsis: true,
        render: (value, job) => value || job.line_name || job.line_code || "-",
      },
      {
        title: "线路",
        key: "line",
        ellipsis: true,
        render: (_value, job) => job.line_name || job.line_code || "-",
      },
      {
        title: "类型",
        dataIndex: "job_type",
        key: "job_type",
        width: 150,
        render: (_value, job) => formatJobType(job.job_type, readMitigationMode(job)),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 100,
        render: (value) => <span style={{ color: statusColor(value) }}>{value}</span>,
      },
      {
        title: "创建时间",
        dataIndex: "create_date",
        key: "create_date",
        width: 180,
        render: (value) => formatDateTime(value),
      },
      {
        title: "杆塔数",
        dataIndex: "total_tower_count",
        key: "total_tower_count",
        width: 100,
        align: "right" as const,
      },
      {
        title: "结果数",
        dataIndex: "result_tower_count",
        key: "result_tower_count",
        width: 100,
        align: "right" as const,
      },
      {
        title: "操作",
        key: "operation",
        width: 160,
        render: (_value, job) => (
          <Space size="small">
            <Button size="small" onClick={() => handleViewDetail(job)}>
              查看详情
            </Button>
            <Button
              size="small"
              danger
              disabled={["queued", "running"].includes(job.status)}
              onClick={() => handleDeleteJob(job)}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ];

    return (
      <div className="admin-power-lines-list-pane">
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="关键字" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Input
                value={keywordInput}
                allowClear
                onChange={(event) => setKeywordInput(event.target.value)}
                placeholder="按任务名/线路名/线路编码筛选"
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                htmlType="button"
                icon={<SearchOutlined />}
                onClick={handleSearch}
                className="admin-search-btn"
              >
                查询
              </Button>
            </Form.Item>
          </Form>
          <Segmented
            value={viewMode}
            onChange={(value) => setViewMode(value as "card" | "list")}
            options={[
              { label: "卡片视图", value: "card" },
              { label: "列表视图", value: "list" },
            ]}
          />
        </div>

        {jobsQuery.error && (
          <Alert
            type="error"
            showIcon
            message={jobsQuery.error instanceof Error ? jobsQuery.error.message : "加载失败"}
          />
        )}

        {jobs.length === 0 ? (
          jobsQuery.isFetching ? (
            <div className="flex w-full flex-1 items-center justify-center">
              <Spin />
            </div>
          ) : (
            <Empty description="暂无防雷改造任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )
        ) : viewMode === "list" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-power-lines-table-view"
            style={{ "--admin-power-lines-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<RetrofitTaskItem>
              rowKey="id"
              columns={columns}
              dataSource={jobs}
              loading={jobsQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total,
                showSizeChanger: true,
                pageSizeOptions: [6, 12, 24, 48],
                showTotal: (totalCount) => `共 ${totalCount} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1200, y: tableScrollY }}
              locale={{
                emptyText: (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无防雷改造任务" />
                ),
              }}
            />
          </div>
        ) : (
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div className="admin-power-lines-card-scroll">
              <Spin spinning={jobsQuery.isFetching}>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  {jobs.map((job) => (
                    <Card
                      key={job.id}
                      size="small"
                      hoverable
                      className="admin-power-lines-line-card"
                      onClick={() => handleViewDetail(job)}
                    >
                      <div className="flex flex-col">
                        <div className="admin-power-lines-line-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
                          <Typography.Text strong className="truncate flex-1">
                            {job.job_name || job.line_name || job.line_code || "-"}
                          </Typography.Text>
                          <div className="flex flex-shrink-0 items-center gap-2">
                            <Badge status={retrofitJobBadgeStatus(job.status)} />
                            <Typography.Text type="secondary" className="text-xs">{job.status}</Typography.Text>
                          </div>
                        </div>
                        <div className="flex flex-col gap-2 px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Typography.Text type="secondary" className="text-xs truncate">
                              {job.line_name || job.line_code || "-"}
                            </Typography.Text>
                          </div>
                          <div className="flex items-center gap-2">
                            <Typography.Text type="secondary" className="text-xs">
                              创建：{formatDateTime(job.create_date)}
                            </Typography.Text>
                          </div>
                        </div>
                        <div className="admin-power-lines-line-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
                          <div />
                          <Space size="small" className="shrink-0">
                            <Tooltip title="查看详情">
                              <Button
                                type="text"
                                size="small"
                                icon={<EyeOutlined />}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleViewDetail(job);
                                }}
                              />
                            </Tooltip>
                            <Tooltip title="删除">
                              <Button
                                type="text"
                                size="small"
                                danger
                                disabled={["queued", "running"].includes(job.status)}
                                icon={<DeleteOutlined />}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleDeleteJob(job);
                                }}
                              />
                            </Tooltip>
                          </Space>
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              </Spin>
            </div>
            <div className="admin-power-lines-pagination">
              <Pagination
                current={pagination.current}
                pageSize={pagination.pageSize}
                total={total}
                onChange={(page, pageSize) => {
                  setPagination({ current: page, pageSize });
                }}
                showSizeChanger
                showTotal={(totalCount) => `共 ${totalCount} 条`}
              />
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Tab2：成因分析与措施推荐 ────────────────────────────────────
  function renderWorkPane() {
    const isMeasureMode = taskMode === TASK_MODE_MEASURE || taskMode === TASK_MODE_NONNEW;
    const isNonNew = taskMode === TASK_MODE_NONNEW;

    return (
      <div className="admin-power-lines-list-pane">
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="任务类型" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Segmented
                value={taskMode}
                onChange={(value) => handleTaskModeChange(value as TaskMode)}
                options={taskModeOptions}
              />
            </Form.Item>
            {taskMode === TASK_MODE_REASON ? (
              <Form.Item label="线路" style={{ marginBottom: 0 }}>
                <Select
                  value={lineId}
                  onChange={(next) => {
                    setLineId(next);
                    setPagination((prev) => ({ ...prev, current: 1 }));
                  }}
                  loading={loadingLines}
                  placeholder="选择线路"
                  style={{ width: 320 }}
                  options={lines.map((line) => ({
                    value: line.line_id || line.id,
                    label: line.line_name || line.line_code || "-",
                  }))}
                  showSearch
                  optionFilterProp="label"
                />
              </Form.Item>
            ) : (
              <Form.Item label="前置任务" style={{ marginBottom: 0 }}>
                <Select
                  value={selectedBaseJobId}
                  onChange={handleBaseJobChange}
                  loading={loadingJobs}
                  placeholder="选择前置任务"
                  style={{ width: 320 }}
                  options={baseJobs.map((job) => ({
                    value: job.id,
                    label: `${job.job_name || job.line_name || job.line_code || "-"}（${formatJobType(job.job_type)}）`,
                  }))}
                  showSearch
                  optionFilterProp="label"
                />
              </Form.Item>
            )}
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                htmlType="button"
                icon={<ArrowUpOutlined />}
                onClick={() => {
                  if (taskMode === TASK_MODE_REASON) {
                    void loadLines();
                  } else {
                    void loadBaseJobs();
                  }
                }}
                className="admin-search-btn"
              >
                刷新
              </Button>
            </Form.Item>
          </Form>
        </div>

        {errorMessage && (
          <Alert type="error" showIcon message={errorMessage} style={{ marginBottom: 12 }} />
        )}

        {taskMode === TASK_MODE_REASON ? renderReasonPane() : renderMeasurePane(isNonNew)}
      </div>
    );
  }

  // 成因分析：高风险杆塔分档明细（只读）
  function renderReasonPane() {
    const columns: ColumnsType<FlAnalysisTowerResultSummary> = [
      {
        title: "塔号",
        dataIndex: "tower_no",
        key: "tower_no",
        width: 120,
        render: (value) => value || "-",
      },
      {
        title: "风险等级",
        dataIndex: "risk_level",
        key: "risk_level",
        width: 120,
        render: (value) => <Tag color={riskColor(value)}>{value ?? "-"}</Tag>,
      },
      {
        title: "原因类型",
        key: "reason_type",
        width: 180,
        render: (_value, row) => readReasonType(row),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (value) => <span style={{ color: statusColor(value) }}>{value}</span>,
      },
      {
        title: "操作",
        key: "operation",
        width: 140,
        render: (_value, row) => (
          <Button
            size="small"
            onClick={() => {
              setSelectedRow(row);
              setDetailVisible(true);
            }}
          >
            查看详情
          </Button>
        ),
      },
    ];

    return (
      <>
        {highRiskQuery.error && (
          <Alert
            type="error"
            showIcon
            message={highRiskQuery.error instanceof Error ? highRiskQuery.error.message : "加载失败"}
          />
        )}
        {!lineId ? (
          <Empty description="请先选择线路" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div
            ref={tableScrollAnchorRef}
            className="admin-power-lines-table-view"
            style={{ "--admin-power-lines-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<FlAnalysisTowerResultSummary>
              rowKey="id"
              columns={columns}
              dataSource={riskRows}
              loading={highRiskQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total: riskTotal,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: (totalCount) => `共 ${totalCount} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1000, y: tableScrollY }}
              locale={{
                emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无高风险杆塔" />,
              }}
            />
          </div>
        )}
        <div className="flex justify-end">
          <Button onClick={handleExport} disabled={!lineId || riskRows.length === 0}>
            导出报告
          </Button>
        </div>
      </>
    );
  }

  // 措施推荐 / 非建线：勾选高风险塔 → 生成任务
  function renderMeasurePane(isNonNew: boolean) {
    const columns: ColumnsType<TowerSelectionRow> = [
      {
        title: "包含",
        key: "include",
        width: 80,
        align: "center" as const,
        render: (_value, row) => (
          <Checkbox checked={row.include} onChange={() => toggleTowerInclude(row.id)} />
        ),
      },
      {
        title: "塔号",
        dataIndex: "tower_no",
        key: "tower_no",
        width: 120,
        render: (value) => value || "-",
      },
      {
        title: "风险等级",
        dataIndex: "risk_level",
        key: "risk_level",
        width: 120,
        render: (value) => <Tag color={riskColor(value)}>{value ?? "-"}</Tag>,
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (value) => <span style={{ color: statusColor(value) }}>{value}</span>,
      },
    ];

    return (
      <>
        {selectedBaseJob ? (
          <Alert
            type="info"
            showIcon
            message="已选择前置任务"
            description={`${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "-"} / 杆塔总数：${selectedBaseJob.total_tower_count}`}
          />
        ) : null}
        {!selectedBaseJobId ? (
          <Empty description="请先选择前置任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div
            ref={tableScrollAnchorRef}
            className="admin-power-lines-table-view"
            style={{ "--admin-power-lines-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<TowerSelectionRow>
              rowKey="id"
              columns={columns}
              dataSource={towerRows}
              loading={towerQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total: towerTotal,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: (totalCount) => `共 ${totalCount} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 800, y: tableScrollY }}
              locale={{
                emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无杆塔结果" />,
              }}
            />
          </div>
        )}
        <div className="flex flex-col gap-2">
          <Input
            value={jobName}
            onChange={(event) => setJobName(event.target.value)}
            placeholder="任务名称"
          />
          <div className="flex flex-wrap gap-3">
            <Button
              type="primary"
              onClick={() => void handleCreateJob()}
              loading={creating}
              disabled={!selectedBaseJobId || towerRows.length === 0}
            >
              {isNonNew ? "生成措施推荐（非建线）" : "生成措施推荐"}
            </Button>
          </div>
        </div>
      </>
    );
  }
}

// ── helpers ──────────────────────────────────────────────────────
function formatJobType(jobType: string, nonConstruction = false): string {
  if (jobType === "risk") return "风险评估";
  if (jobType === "mitigation") return nonConstruction ? "措施推荐(非建线)" : "措施推荐";
  if (jobType === "normal") return "普通计算";
  if (jobType === "tongtiao") return "同跳计算";
  if (jobType === "report") return "报告";
  if (jobType === "scenario") return "加装避雷器复算";
  return jobType || "-";
}

function readMitigationMode(job: FlAnalysisJobSummary | FlAnalysisJobDetail | null): boolean {
  if (!job) return false;
  const options = job.execution_options_json as Record<string, unknown> | undefined;
  return Boolean(options?.non_construction);
}

function retrofitJobBadgeStatus(
  value: string | null | undefined,
): "success" | "processing" | "error" | "default" | "warning" {
  if (value === "success") return "success";
  if (value === "failed" || value === "blocked") return "error";
  if (value === "running" || value === "queued") return "processing";
  return "default";
}

function readReasonType(row: FlAnalysisTowerResultSummary): string {
  const value = row.result_json?.reason_type;
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.join("、");
  }
  const summary = row.summary_text;
  return typeof summary === "string" && summary.trim().length > 0 ? summary : "-";
}

function isHighRisk(riskLevel: string | null | undefined): boolean {
  if (!riskLevel) {
    return false;
  }
  if (riskLevel === "high") {
    return true;
  }
  const numeric = Number(riskLevel);
  return Number.isFinite(numeric) && numeric > 2;
}

// ── 动态详情 Tab 内容：防雷改造任务详情（信息 + 塔结果）────────────
function RetrofitJobDetail({ jobId }: { jobId: string }) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const [job, setJob] = useState<FlAnalysisJobSummary | null>(null);
  const [rows, setRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const loadJob = useCallback(async () => {
    const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}`);
    if (response.ok) {
      const data = (await response.json()) as { job: FlAnalysisJobSummary };
      setJob(data.job);
    }
  }, [fetchWithAuth, jobId]);

  const loadResults = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(pagination.pageSize));
      params.set("offset", String((pagination.current - 1) * pagination.pageSize));
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/results?${params.toString()}`);
      if (!response.ok) {
        return;
      }
      const data = (await response.json()) as { items: FlAnalysisTowerResultSummary[]; total: number };
      setRows(data.items ?? []);
      setTotal(data.total ?? 0);
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, jobId, pagination.current, pagination.pageSize]);

  useEffect(() => {
    if (!user || !canRead) {
      return;
    }
    void loadJob();
    void loadResults();
  }, [user, canRead, loadJob, loadResults]);

  useTopicSubscription("admin.fl-analysis", useCallback(() => {
    void loadResults();
  }, [loadResults]));

  const handleExport = () => {
    const headers = "塔号,当前风险,预期风险,预期得分,措施建议,结论\n";
    const lines = rows
      .map((row) => {
        const result = row.result_json ?? {};
        const current = result.current_risk_level ?? row.risk_level ?? "-";
        const expected = result.expected_risk_level ?? "-";
        const score = result.expected_score ?? "-";
        const recommendation = result.mitigation_recommendation ?? "-";
        const conclusion = result.recommendation_result ?? result.summary_text ?? "-";
        return `${row.tower_no ?? "-"},${current},${expected},${score},${String(recommendation).replace(/[",\n]/g, " ")},${String(conclusion).replace(/[",\n]/g, " ")}`;
      })
      .join("\n");
    const blob = new Blob([headers + lines], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `防雷改造任务-${jobId.slice(0, 8)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const columns: ColumnsType<FlAnalysisTowerResultSummary> = [
    {
      title: "塔号",
      dataIndex: "tower_no",
      key: "tower_no",
      width: 120,
      render: (value) => value || "-",
    },
    {
      title: "当前风险",
      key: "current_risk",
      width: 120,
      render: (_value, row) => {
        const result = (row.result_json ?? {}) as Record<string, unknown>;
        const current = String(result.current_risk_level ?? row.risk_level ?? "-");
        return <Tag color={riskColor(current)}>{current}</Tag>;
      },
    },
    {
      title: "预期风险",
      key: "expected_risk",
      width: 120,
      render: (_value, row) => {
        const result = (row.result_json ?? {}) as Record<string, unknown>;
        const expected = String(result.expected_risk_level ?? "-");
        return <Tag color={riskColor(expected)}>{expected}</Tag>;
      },
    },
    {
      title: "预期得分",
      key: "expected_score",
      width: 100,
      align: "right" as const,
      render: (_value, row) => {
        const result = (row.result_json ?? {}) as Record<string, unknown>;
        return String(result.expected_score ?? "-");
      },
    },
    {
      title: "措施建议",
      key: "recommendation",
      ellipsis: true,
      render: (_value, row) => {
        const recommendation = (row.result_json ?? {}).mitigation_recommendation;
        return typeof recommendation === "string" ? recommendation : "-";
      },
    },
    {
      title: "结论",
      key: "conclusion",
      width: 180,
      render: (_value, row) => {
        const conclusion = (row.result_json ?? {}).recommendation_result;
        if (typeof conclusion === "string") {
          return <Tag color={conclusion.includes("避雷器") ? "orange" : "green"}>{conclusion}</Tag>;
        }
        return "-";
      },
    },
  ];

  return (
    <div className="admin-power-lines-list-pane">
      <Alert
        type="info"
        showIcon
        message={job ? (job.job_name || job.line_name || job.line_code || "防雷改造任务") : "加载中…"}
        description={
          job
            ? `${job.line_name || job.line_code || "-"} / ${formatJobType(job.job_type, readMitigationMode(job))} / ${job.status} / 创建：${formatDateTime(job.create_date)}`
            : undefined
        }
      />
      <div
        className="admin-power-lines-table-view"
        style={{ "--admin-power-lines-table-body-min-height": "240px" } as CSSProperties}
      >
        <Table<FlAnalysisTowerResultSummary>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          tableLayout="fixed"
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (totalCount) => `共 ${totalCount} 条`,
            hideOnSinglePage: false,
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          scroll={{ x: 1000, y: 240 }}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无杆塔结果" />,
          }}
        />
      </div>
      <div className="flex justify-end">
        <Button onClick={() => void handleExport()} disabled={rows.length === 0}>
          导出结果
        </Button>
      </div>
    </div>
  );
}
