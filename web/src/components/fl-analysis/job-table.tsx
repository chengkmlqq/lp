"use client";

import { useMemo } from "react";
import { Empty, Spin, Table, Tag } from "antd";
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
  selectedJobId: string | null;
  loading: boolean;
  onSelect: (job: FlAnalysisJobSummary) => void;
};

export function JobTable({ jobs, selectedJobId, loading, onSelect }: JobTableProps) {
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
  ], []);

  if (loading) {
    return <Spin />;
  }

  return (
    <Table<FlAnalysisJobSummary>
      rowKey="id"
      className="admin-fl-analysis-job-table"
      columns={columns}
      dataSource={jobs}
      rowClassName={(job) => (job.id === selectedJobId ? "admin-fl-analysis-job-row-selected" : "")}
      onRow={(job) => ({
        onClick: () => {
          onSelect(job);
        },
      })}
      pagination={{ pageSize: 20, showSizeChanger: true, hideOnSinglePage: false }}
      scroll={{ x: 1200 }}
      locale={{
        emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无防雷分析任务" />,
      }}
    />
  );
}
