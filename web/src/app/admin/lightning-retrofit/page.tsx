"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Empty, Input, Pagination, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { SearchOutlined } from "@ant-design/icons";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
  LineListResponse,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import { formatDateTime, riskColor } from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

type RetrofitTaskItem = FlAnalysisJobSummary & {
  retrofit_type?: string | null;
};

export default function AdminLightningRetrofitPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useState<HTMLDivElement | null>(null)[0];

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

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
    queryKey: [jobsListPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(jobsListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisJobListResponse;
    },
  });

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const total = jobsQuery.data?.total ?? 0;

  const handleSearch = () => {
    setKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  const handleDeleteJob = async (job: FlAnalysisJobSummary) => {
    const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${job.id}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    await jobsQuery.refetch();
  };

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
      align: "center" as const,
      render: (_value, job) => (
        <Space size="small">
          <Button type="link" size="small">
            查看详情
          </Button>
          <Button
            type="link"
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

  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Space direction="vertical" size={12}>
        <Typography.Text type="secondary">请先登录后再查看防雷改造任务。</Typography.Text>
      </Space>
    );
  }

  if (!canRead) {
    return (
      <Space direction="vertical" size={12}>
        <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `line.manage`）。</Typography.Text>
      </Space>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-6">
        <Space className="flex-wrap">
          <Button type="primary" href="/admin/lightning-retrofit/high-risk-reason">
            高风险原因分析
          </Button>
          <Button type="primary" href="/admin/lightning-retrofit/measure-recommend">
            改造措施推荐
          </Button>
          <Button type="primary" href="/admin/lightning-retrofit/measure-recommend-nonnew">
            改造措施推荐(非建线)
          </Button>
        </Space>

        <div className="admin-filter-bar">
          <Space.Compact style={{ display: "inline-flex" }}>
            <Input
              value={keywordInput}
              allowClear
              onChange={(event) => setKeywordInput(event.target.value)}
              placeholder="按任务名/线路名/线路编码筛选"
              onPressEnter={handleSearch}
            />
            <Button icon={<SearchOutlined />} onClick={handleSearch}>
              查询
            </Button>
          </Space.Compact>
          <Button onClick={() => setViewMode(viewMode === "card" ? "list" : "card")}>
            {viewMode === "card" ? "列表视图" : "卡片视图"}
          </Button>
        </div>

        {jobs.length === 0 ? (
          <Empty description="暂无防雷改造任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : viewMode === "card" ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {jobs.map((job) => (
              <div
                key={job.id}
                className="admin-fl-analysis-job-card border border-gray-200 rounded-lg"
              >
                <div className="admin-fl-analysis-job-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
                  <Typography.Text strong className="truncate">
                    {job.job_name || job.line_name || job.line_code || "-"}
                  </Typography.Text>
                  <span style={{ color: statusColor(job.status) }}>{job.status}</span>
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
                <div className="admin-fl-analysis-job-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
                  <Space>
                    <Button type="link" size="small">
                      查看详情
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      danger
                      disabled={["queued", "running"].includes(job.status)}
                      onClick={() => handleDeleteJob(job)}
                    >
                      删除
                    </Button>
                  </Space>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div
            ref={tableScrollAnchorRef}
            style={{ "--admin-fl-analysis-table-body-min-height": `${tableScrollY}px` } as React.CSSProperties}
          >
            <Table
              rowKey="id"
              className="admin-fl-analysis-job-table"
              columns={columns}
              dataSource={jobs}
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total,
                showSizeChanger: true,
                pageSizeOptions: [6, 12, 24, 48],
                showTotal: (total) => `共 ${total} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1200, y: tableScrollY }}
              locale={{
                emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无防雷改造任务" />,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

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

function statusColor(value: string | null | undefined): string {
  if (value === "success") return "green";
  if (value === "failed" || value === "blocked") return "red";
  if (value === "running") return "blue";
  if (value === "queued") return "cyan";
  return "default";
}
