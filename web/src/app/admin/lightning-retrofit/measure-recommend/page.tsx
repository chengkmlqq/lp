"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Form,
  message,
  Pagination,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useQueryClient } from "@tanstack/react-query";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
  TowerSelectionRow,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import {
  formatJobType,
  mitigationMode,
  riskColor,
  statusColor,
} from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

export default function AdminLightningMeasureRecommendPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [messageApi, contextHolder] = message.useMessage();
  const queryClient = useQueryClient();
  const [baseJobs, setBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [selectedBaseJobId, setSelectedBaseJobId] = useState<string>("");
  const [towerRows, setTowerRows] = useState<TowerSelectionRow[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [loadingTowers, setLoadingTowers] = useState(false);
  const [creating, setCreating] = useState(false);
  const [jobName, setJobName] = useState("");
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [viewMode, setViewMode] = useState<"card" | "list">("list");
  const [errorMessage, setErrorMessage] = useState("");

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

  const selectedBaseJob = useMemo(
    () => baseJobs.find((job) => job.id === selectedBaseJobId) ?? null,
    [baseJobs, selectedBaseJobId],
  );

  const towerQueryPath = useMemo(() => {
    if (!selectedBaseJobId) return null;
    const params = new URLSearchParams();
    params.set("limit", "500");
    return `/api/v1/fl-analysis/jobs/${selectedBaseJobId}/results?${params.toString()}`;
  }, [selectedBaseJobId]);

  const towerQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs", selectedBaseJobId, "results"],
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

  const detailQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs", selectedBaseJobId],
    enabled: !!user && canRead && Boolean(selectedBaseJobId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${selectedBaseJobId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { job: FlAnalysisJobSummary };
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
      include: row.risk_level === "high" || (row.risk_level && parseInt(row.risk_level, 10) > 2),
    }));
  }, [towerQuery.data?.items]);

  const total = towerQuery.data?.total ?? 0;
  const paginatedTowerRows = useMemo(() => {
    const start = (paginationCurrent - 1) * paginationPageSize;
    const end = start + paginationPageSize;
    return computedTowerRows.slice(start, end);
  }, [computedTowerRows, paginationCurrent, paginationPageSize]);

  const invalidateMeasureQueries = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0]?.startsWith?.("/api/v1/fl-analysis/jobs"),
    });
  }, [queryClient]);

  useTopicSubscription("admin.fl-analysis", useCallback(() => {
    void invalidateMeasureQueries();
  }, [invalidateMeasureQueries]));

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

  const handleBaseJobChange = async (nextJobId: string) => {
    setSelectedBaseJobId(nextJobId);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setErrorMessage("");
    await loadBaseJobs();
  };

  const toggleTowerInclude = (rowId: string) => {
    setTowerRows((previous) =>
      previous.map((row) => (row.id === rowId ? { ...row, include: !row.include } : row)),
    );
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
      const payload = {
        line_id: selectedBaseJob.line_id,
        job_name: jobName.trim() || `${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "防雷任务"}-措施推荐`,
        job_type: "mitigation",
        execution_options_json: {
          non_construction: false,
          base_job_id: selectedBaseJob.id,
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
      setPagination((prev) => ({ ...prev, current: 1 }));
      await Promise.all([loadBaseJobs(), invalidateMeasureQueries()]);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "措施推荐任务创建失败");
    } finally {
      setCreating(false);
    }
  };

  const columns: ColumnsType<TowerSelectionRow> = useMemo(
    () => [
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
    ],
    [],
  );

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    // 用「视口可用高度」推导：anchor 自身高度会被表体 min-height 撑大，用它反推
    // 会形成正反馈（每次翻页多累加一次未计入间距，表体持续变高）。2026-09-12 修复
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
  }, [updateTableScrollHeight, towerRows.length, viewMode]);

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
  }, [updateTableScrollHeight, viewMode]);

  const measureListError = towerQuery.error instanceof Error ? towerQuery.error.message : errorMessage;
  useToastFeedback({
    errorMessage: measureListError,
    successMessage: "",
    clearError: () => setErrorMessage(""),
    clearSuccess: () => {},
  });

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再查看改造措施推荐。</Typography.Text>
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
        <div className="admin-fl-analysis-list-pane">
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="前置任务" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select
                  value={selectedBaseJobId}
                  onChange={handleBaseJobChange}
                  loading={loadingJobs}
                  placeholder="选择前置任务"
                  style={{ width: 320 }}
                  options={baseJobs.map((job) => ({
                    value: job.id,
                    label: `${job.job_name || job.line_name || job.line_code || "-"}（${formatJobType(job.job_type, mitigationMode(job))}）`,
                  }))}
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<PlusOutlined />}
                  onClick={loadBaseJobs}
                  className="admin-search-btn"
                >
                  刷新
                </Button>
              </Form.Item>
            </Form>
            <Segmented
              value={viewMode}
              onChange={(value) => setViewMode(value as "card" | "list")}
              options={[
                { label: "列表视图", value: "list" },
              ]}
            />
          </div>

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
          ) : loadingTowers ? (
            <div className="admin-fl-analysis-loading-bar">
              <Progress percent={0} size="small" />
            </div>
          ) : viewMode === "list" ? (
            <div
              ref={tableScrollAnchorRef}
              className="admin-fl-analysis-table-view"
              style={{ "--admin-fl-analysis-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
            >
              <Table<TowerSelectionRow>
                rowKey="id"
                className="admin-fl-analysis-job-table"
                columns={columns}
                dataSource={paginatedTowerRows}
                loading={towerQuery.isFetching}
                tableLayout="fixed"
                pagination={{
                  current: pagination.current,
                  pageSize: pagination.pageSize,
                  total,
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  showTotal: (total) => `共 ${total} 条`,
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
          ) : (
            <Card>
              <Space direction="vertical" size={12}>
                <Typography.Text type="secondary">改造措施推荐当前仅支持列表视图。</Typography.Text>
              </Space>
            </Card>
          )}

          <div className="flex flex-col gap-2">
            <Input
              value={jobName}
              onChange={(event) => setJobName(event.target.value)}
              placeholder="任务名称"
            />
            <div className="flex flex-wrap gap-3">
              <Button type="primary" onClick={handleCreateJob} loading={creating} disabled={!selectedBaseJobId || towerRows.length === 0}>
                生成措施推荐
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
