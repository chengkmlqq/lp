"use client";

import { useMemo } from "react";
import { Button, Empty, Spin, Table, Tag, Space } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { FlAnalysisJobSummary } from "@/types/auth";

import {
  formatDateTime,
  formatJobType,
  mitigationMode,
  statusColor,
} from "./types";

type JobTableProps = {
  jobs: FlAnalysisJobSummary[];
  loading: boolean;
  total: number;
  pagination: { current: number; pageSize: number };
  onPaginationChange: (next: { current: number; pageSize: number }) => void;
  scrollY?: number;
  onDeleteJob: (job: FlAnalysisJobSummary) => void;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
  /** 打开任务详情（查看结果） */
  onOpenDetail?: (job: FlAnalysisJobSummary) => void;
};

const LOCKED_STATUSES = new Set(["queued", "running"]);

function isJobLocked(job: FlAnalysisJobSummary) {
  return LOCKED_STATUSES.has(job.status);
}

export function JobTable({
  jobs,
  loading,
  total,
  pagination,
  onPaginationChange,
  scrollY,
  onDeleteJob,
  canReadLogs,
  onOpenLog,
  onOpenDetail,
}: JobTableProps) {
  const columns = useMemo<ColumnsType<FlAnalysisJobSummary>>(() => [
    {
      title: "任务名",
      dataIndex: "job_name",
      key: "job_name",
      ellipsis: true,
      render: (value: string | null, job) => value || job.line_name || job.line_code || "-",
    },
    {
      title: "线路",
      key: "line",
      ellipsis: true,
      render: (_value, job) => job.line_name || job.line_code || "-",
    },
    {
      title: "任务类型",
      key: "job_type",
      width: 150,
      render: (_value, job) => formatJobType(job.job_type, mitigationMode(job)),
    },
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_value, job) => <Tag color={statusColor(job.status)}>{job.status}</Tag>,
    },
    {
      title: "创建时间",
      dataIndex: "create_date",
      key: "create_date",
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: "完成时间",
      dataIndex: "finished_at",
      key: "finished_at",
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: "杆塔数",
      dataIndex: "total_tower_count",
      key: "total_tower_count",
      width: 90,
      align: "right" as const,
    },
    {
      title: "结果数",
      dataIndex: "result_tower_count",
      key: "result_tower_count",
      width: 90,
      align: "right" as const,
    },
    {
      title: "错误信息",
      dataIndex: "error_message",
      key: "error_message",
      ellipsis: true,
      render: (value: string | null) => value || "-",
    },
    ...(onDeleteJob
      ? [
          {
            title: "操作",
            key: "operation",
            width: 280,
            align: "center" as const,
            render: (_value: unknown, job: FlAnalysisJobSummary) => (
              <Space size="small">
                {onOpenDetail ? (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => onOpenDetail(job)}
                  >
                    查看结果
                  </Button>
                ) : null}
                {canReadLogs && onOpenLog ? (
                  <Button
                    type="link"
                    size="small"
                    disabled={!job.task_id}
                    onClick={() => onOpenLog(job.task_id, "任务执行日志", job.job_name || job.line_name || job.line_code || "防雷任务")}
                  >
                    查看日志
                  </Button>
                ) : null}
                <Button
                  danger
                  type="link"
                  size="small"
                  disabled={isJobLocked(job)}
                  onClick={() => onDeleteJob(job)}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]
      : []),
  ], [onDeleteJob, canReadLogs, onOpenLog]);

  if (jobs.length === 0 && loading) {
    // 无数据可展示时的首载/空结果：居中加载指示；有数据时由下方 Table 的 loading
    // 遮罩保留现有行，接口返回后再更新，避免查询开始时清空表格
    return (
      <div className="flex w-full flex-1 items-center justify-center">
        <Spin />
      </div>
    );
  }

  return (
    <Table<FlAnalysisJobSummary>
      rowKey="id"
      className="admin-fl-analysis-job-table"
      columns={columns}
      dataSource={jobs}
      loading={loading}
      pagination={{
        current: pagination.current,
        pageSize: pagination.pageSize,
        total,
        showSizeChanger: true,
        pageSizeOptions: [6, 12, 24, 48],
        showTotal: (total) => `共 ${total} 条`,
        hideOnSinglePage: false,
        onChange: (page, pageSize) => {
          onPaginationChange({ current: page, pageSize });
        },
      }}
      scroll={{ x: 1200, y: scrollY }}
      locale={{
        emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无防雷分析任务" />,
      }}
    />
  );
}
