"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Alert,
  Button,
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
import { ArrowUpOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import {
  formatJobType,
  readMitigationMode,
  riskColor,
  statusColor,
} from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

export default function AdminLightningHighRiskReasonPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [messageApi, contextHolder] = message.useMessage();
  const queryClient = useQueryClient();
  const [lineId, setLineId] = useState<string>("");
  const [lines, setLines] = useState<FlAnalysisJobSummary[]>([]);
  const [loadingLines, setLoadingLines] = useState(false);
  const [loadingRisk, setLoadingRisk] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [selectedRow, setSelectedRow] = useState<FlAnalysisTowerResultSummary | null>(null);
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [viewMode, setViewMode] = useState<"card" | "list">("list");

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

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
  const total = highRiskQuery.data?.total ?? 0;

  const invalidateHighRisk = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0] === "/admin/lightning-retrofit/high-risk-reason",
    });
  }, [queryClient]);

  useTopicSubscription("admin.lightning-retrofit", useCallback(() => {
    void invalidateHighRisk();
  }, [invalidateHighRisk]));

  const loadLines = useCallback(async (nextLineId: string) => {
    if (!nextLineId) {
      setLines([]);
      return;
    }
    setLoadingLines(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as { items: FlAnalysisJobSummary[] };
      const matched = data.items.filter((item) => item.line_id === nextLineId);
      setLines(matched);
    } catch (error) {
      setLines([]);
    } finally {
      setLoadingLines(false);
    }
  }, [fetchWithAuth]);

  const handleLineChange = async (nextLineId: string) => {
    setLineId(nextLineId);
    setPagination((prev) => ({ ...prev, current: 1 }));
    await loadLines(nextLineId);
  };

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

  const handleViewDetail = (row: FlAnalysisTowerResultSummary) => {
    setSelectedRow(row);
    setDetailVisible(true);
  };

  const columns: ColumnsType<FlAnalysisTowerResultSummary> = useMemo(
    () => [
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
        align: "center" as const,
        render: (_value, row) => (
          <Button size="small" onClick={() => handleViewDetail(row)}>
            查看详情
          </Button>
        ),
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
    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? TABLE_HEADER_HEIGHT;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? TABLE_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - TABLE_BOTTOM_GAP);
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
  }, [updateTableScrollHeight, riskRows.length, viewMode]);

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

  const highRiskListError = highRiskQuery.error instanceof Error ? highRiskQuery.error.message : "";
  useToastFeedback({
    errorMessage: highRiskListError,
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
          <Typography.Text type="secondary">请先登录后再查看高风险原因分析。</Typography.Text>
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
              <Form.Item label="线路" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select
                  value={lineId}
                  onChange={handleLineChange}
                  loading={loadingLines}
                  placeholder="选择线路"
                  style={{ width: 320 }}
                  options={lines.map((line) => ({
                    value: line.line_id || line.id,
                    label: `${line.line_name || line.line_code || "-"}（${formatJobType(line.job_type, readMitigationMode(line))}）`,
                  }))}
                  showSearch
                  optionFilterProp="label"
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<ArrowUpOutlined />}
                  onClick={() => loadLines(lineId)}
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

          {highRiskQuery.error && (
            <Alert
              type="error"
              showIcon
              message={highRiskQuery.error instanceof Error ? highRiskQuery.error.message : "加载失败"}
            />
          )}

          {!lineId ? (
            <Empty description="请先选择线路" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          ) : loadingRisk ? (
            <div className="admin-fl-analysis-loading-bar">
              <Progress percent={0} size="small" />
            </div>
          ) : viewMode === "list" ? (
            <div
              ref={tableScrollAnchorRef}
              className="admin-fl-analysis-table-view"
              style={{ "--admin-fl-analysis-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
            >
              <Table<FlAnalysisTowerResultSummary>
                rowKey="id"
                className="admin-fl-analysis-job-table"
                columns={columns}
                dataSource={riskRows}
                loading={highRiskQuery.isFetching}
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
                scroll={{ x: 1000, y: tableScrollY }}
                locale={{
                  emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无高风险杆塔" />,
                }}
              />
            </div>
          ) : (
            <Card>
              <Space direction="vertical" size={12}>
                <Typography.Text type="secondary">高风险原因分析当前仅支持列表视图。</Typography.Text>
              </Space>
            </Card>
          )}

          <div className="flex justify-end">
            <Button onClick={handleExport} disabled={!lineId || riskRows.length === 0}>
              导出报告
            </Button>
          </div>
        </div>
      </div>

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
