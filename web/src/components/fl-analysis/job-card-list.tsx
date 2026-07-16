"use client";

import { Empty, Spin, Space, Tag, Typography } from "antd";

import { Card } from "@/components/ui-antd";
import type { FlAnalysisJobSummary } from "@/types/auth";

import {
  formatDateTime,
  formatJobType,
  mitigationMode,
  statusColor,
} from "./types";

type JobCardListProps = {
  jobs: FlAnalysisJobSummary[];
  selectedJobId: string | null;
  loading: boolean;
  onSelect: (jobId: string) => void;
};

export function JobCardList({ jobs, selectedJobId, loading, onSelect }: JobCardListProps) {
  if (loading) {
    return <Spin />;
  }

  if (jobs.length === 0) {
    return <Empty description="暂无防雷分析任务" />;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {jobs.map((job) => {
        const selected = job.id === selectedJobId;
        const lineName = job.line_name || job.line_code || "-";
        return (
          <button
            key={job.id}
            type="button"
            className={`w-full cursor-pointer rounded-lg border bg-white p-3 text-left transition hover:border-blue-400 hover:shadow-sm ${
              selected ? "border-blue-500 shadow-sm ring-1 ring-blue-500" : "border-gray-200"
            }`}
            onClick={() => {
              onSelect(job.id);
            }}
          >
            <Space direction="vertical" size={8} className="flex w-full">
              <Space size={[6, 6]} wrap>
                <Tag color={statusColor(job.status)}>{job.status}</Tag>
                <Tag>{formatJobType(job.job_type, mitigationMode(job))}</Tag>
              </Space>
              <div>
                <Typography.Text strong className="line-clamp-1">
                  {job.job_name || lineName}
                </Typography.Text>
                <Typography.Text type="secondary" className="block line-clamp-1">
                  {lineName}
                </Typography.Text>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-gray-500">
                <span>创建：{formatDateTime(job.create_date)}</span>
                <span>完成：{formatDateTime(job.finished_at)}</span>
                <span>杆塔：{job.total_tower_count}</span>
                <span>结果：{job.result_tower_count}</span>
              </div>
            </Space>
          </button>
        );
      })}
    </div>
  );
}

export function JobListCard(props: JobCardListProps) {
  return (
    <Card>
      <Space direction="vertical" size={12} className="flex w-full">
        <div>
          <Typography.Title level={5} style={{ margin: 0 }}>
            任务列表
          </Typography.Title>
          <Typography.Text type="secondary">
            点击卡片查看任务详情与杆塔结果。
          </Typography.Text>
        </div>
        <JobCardList {...props} />
      </Space>
    </Card>
  );
}
