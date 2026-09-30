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
  Timeline,
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
import { formatDateTime, riskColor, runningProgressPercent } from "@/components/fl-analysis/types";
import { statusColor } from "@/components/fl-analysis/types";
import { RetrofitCreateModal } from "@/components/fl-analysis/retrofit-create-modal";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

// ⚠️ 2026-09-30 页面重构(参考 fl-analysis 页):只保留「防雷改造」任务列表单 Tab，
// 「改造」入口改为 tabBarExtraContent 按钮 → 弹窗(选前置计算任务+勾选高风险塔+提交)。
// 成因分析已并入「防雷计算」详情（result-table「原因分析」列）。
const LIST_TAB_KEY = "jobs";

type DetailTabItem = {
  key: string;
  label: React.ReactNode;
  closable: boolean;
  children: React.ReactNode;
};

type RetrofitTaskItem = FlAnalysisJobSummary & {
  retrofit_type?: string | null;
};

export default function AdminLightningRetrofitPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [messageApi, contextHolder] = message.useMessage();
  const queryClient = useQueryClient();

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

  // ── Tab / 任务类型 ──────────────────────────────────────────────
  // 动态选项卡：固定「防雷改造任务」列表，点任务「查看详情」在当前页 append 动态详情 tab（不跳转页面），可关闭
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);

  // ── 任务列表（Tab1）────────────────────────────────────────────
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [searchNonce, setSearchNonce] = useState(0);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // ── 改造弹窗（2026-09-30：仿 fl-analysis「新建任务」入口）──────
  const [retrofitOpen, setRetrofitOpen] = useState(false);

  // ── 任务列表查询（Tab1）────────────────────────────────────────
  const jobsListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    // 2026-09-30：防雷改造页只列改造类任务；防雷计算任务(normal/tongtiao)
    // 只在「改造」弹窗里作为前置任务下拉出现。
    params.set("job_types", "mitigation,scenario,report");
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

  // 从任务列表 ?jobId= 跳转：直接打开该任务详情动态 tab（不跳转）
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

  // ⚠️ 2026-09-30：措施推荐任务创建逻辑已整体迁至 RetrofitCreateModal 弹窗组件
  // （选前置计算任务 → 勾选高风险塔 → 创建并启动），本页只保留任务列表 + 详情动态 Tab。
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
  }, [updateTableScrollHeight, jobs.length, viewMode, activeTabKey]);

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
          tabBarExtraContent={
            <Space>
              {canManage ? (
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setRetrofitOpen(true)}>
                  改造
                </Button>
              ) : null}
            </Space>
          }
          items={[
            {
              key: LIST_TAB_KEY,
              label: <span className="admin-power-lines-tab-title">防雷改造任务</span>,
              closable: false,
              children: renderJobsPane(),
            },
            ...detailTabs,
          ]}
        />
      </div>

      {/* 改造弹窗：选前置防雷计算任务 → 勾选高风险杆塔 → 创建并启动措施任务 */}
      <RetrofitCreateModal
        open={retrofitOpen}
        onClose={() => setRetrofitOpen(false)}
        onCreated={() => {
          void invalidateMeasureQueries();
        }}
      />
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
        width: 140,
        render: (value, job) => (
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            <span style={{ color: statusColor(value) }}>{value}</span>
            {value === "running" ? (
              <Progress
                percent={runningProgressPercent(job)}
                size="small"
                strokeColor="var(--accent-9)"
                trailColor="var(--ant-color-border-secondary)"
              />
            ) : null}
          </Space>
        ),
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
                className="admin-search-btn" loading={jobsQuery.isFetching}
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
                          {job.status === "running" ? (
                            <div className="flex items-center gap-2">
                              <Progress
                                percent={runningProgressPercent(job)}
                                size="small"
                                style={{ flex: 1 }}
                                strokeColor="var(--accent-9)"
                                trailColor="var(--ant-color-border-secondary)"
                              />
                            </div>
                          ) : null}
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

// ⚠️ 2026-09-30：isHighRisk 判定逻辑已迁入 RetrofitCreateModal（弹窗默认勾选高风险塔）

// ── 动态详情 Tab 内容：防雷改造任务详情（信息 + 塔结果）────────────
function RetrofitJobDetail({ jobId }: { jobId: string }) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const [job, setJob] = useState<FlAnalysisJobSummary | null>(null);
  const [rows, setRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  // 优化过程弹窗：展示状态机逐轮计算过程（2026-09-30）
  const [processRow, setProcessRow] = useState<FlAnalysisTowerResultSummary | null>(null);

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
    {
      title: "优化过程",
      key: "process",
      width: 100,
      render: (_value, row) => {
        const steps = (row.result_json ?? {}).mitigation_process;
        if (!Array.isArray(steps) || steps.length === 0) {
          return <Typography.Text type="secondary">-</Typography.Text>;
        }
        return (
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => setProcessRow(row)}
          >
            查看过程
          </Button>
        );
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

      {/* 优化过程弹窗：状态机逐轮计算过程（2026-09-30） */}
      <Modal
        title={processRow ? `优化过程 - ${processRow.tower_no || processRow.tower_id}` : "优化过程"}
        open={processRow !== null}
        onCancel={() => setProcessRow(null)}
        footer={<Button onClick={() => setProcessRow(null)}>关闭</Button>}
        width={760}
      >
        {processRow ? (
          <ProcessTimeline row={processRow} />
        ) : null}
      </Modal>
    </div>
  );
}

/** 措施推荐状态机逐轮过程时间线（后端 result_json.mitigation_process） */
function ProcessTimeline({ row }: { row: FlAnalysisTowerResultSummary }) {
  const result = (row.result_json ?? {}) as Record<string, unknown>;
  const steps = Array.isArray(result.mitigation_process) ? result.mitigation_process : [];
  if (steps.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="该杆塔无逐轮过程记录（历史任务未保存，重新生成任务后即可查看）。"
      />
    );
  }
  const colorForRisk = (level: string | null | undefined) => {
    if (level === "high") return "red";
    if (level === "medium") return "orange";
    return "green";
  };
  const lastStep = steps[steps.length - 1] as Record<string, unknown>;
  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={`共 ${steps.length} 轮调参`}
        description={`从「从轻到重试改参数，每轮用 ATP 重算验证」到${(lastStep.decision as string) || "完成"}；最终风险：${
          typeof result.expected_risk_level === "string" ? result.expected_risk_level : "-"
        }`}
      />
      <Timeline
        items={(steps as Record<string, unknown>[]).map((step) => {
          const changes = Array.isArray(step.changes) ? (step.changes as Record<string, unknown>[]) : [];
          const recomputed = step.recomputed as Record<string, unknown> | null | undefined;
          const decision = typeof step.decision === "string" && step.decision ? String(step.decision) : "继续下一轮加重措施";
          const grades = (step.grades as Record<string, unknown>) || {};
          const riskLevel = typeof recomputed?.risk_level === "string" ? String(recomputed.risk_level) : null;
          return {
            color: riskLevel ? colorForRisk(riskLevel) : "blue",
            children: (
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <Space wrap>
                  <Typography.Text strong>第 {String(step.step)} 轮</Typography.Text>
                  <Tag color="blue">{String(step.state ?? "-")}</Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    分级：绝缘{String(grades.insulator ?? "-")} / 接地{String(grades.ground ?? "-")} / 保护角{String(grades.protection ?? "-")}
                  </Typography.Text>
                </Space>
                {changes.length > 0 ? (
                  <Typography.Text>
                    改动：
                    {changes.map((c, i) => (
                      <Tag key={i} color="purple" style={{ marginLeft: 4 }}>
                        {String(c.label ?? "")} {String(c.old ?? "")} → {String(c.new ?? "")} {String(c.unit ?? "")}
                      </Tag>
                    ))}
                  </Typography.Text>
                ) : (
                  <Typography.Text type="secondary">本轮无参数改动</Typography.Text>
                )}
                {recomputed ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    ATP 重算：风险等级
                    {riskLevel ? (
                      <Tag color={colorForRisk(riskLevel)} style={{ marginLeft: 4 }}>{riskLevel}</Tag>
                    ) : (
                      <Tag style={{ marginLeft: 4 }}>-</Tag>
                    )}
                    {typeof recomputed.counterstrike_trip_rate === "number" ? `，反击跳闸率 ${Number(recomputed.counterstrike_trip_rate).toFixed(4)}` : ""}
                    {typeof recomputed.shielding_trip_rate === "number" ? `，绕击跳闸率 ${Number(recomputed.shielding_trip_rate).toFixed(4)}` : ""}
                  </Typography.Text>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>本轮未重算（直接进入终态判定）</Typography.Text>
                )}
                <Typography.Text style={{ fontSize: 12, color: decision.includes("补装避雷器") ? "#cf1322" : "#1677ff" }}>
                  ▸ {decision}
                </Typography.Text>
              </Space>
            ),
          };
        })}
      />
    </Space>
  );
}
