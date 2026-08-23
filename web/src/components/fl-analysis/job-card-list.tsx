"use client";

import { Button, Dropdown, Empty, Space, Spin, Tag, Typography } from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DeploymentUnitOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
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
  loading: boolean;
  onDeleteJob: (job: FlAnalysisJobSummary) => void;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
};

const LOCKED_STATUSES = new Set(["queued", "running"]);

function isJobLocked(job: FlAnalysisJobSummary) {
  return LOCKED_STATUSES.has(job.status);
}

export function JobCardList({ jobs, loading, onDeleteJob, canReadLogs, onOpenLog }: JobCardListProps) {
  if (loading) {
    return <Spin />;
  }

  if (jobs.length === 0) {
    return <Empty description="暂无防雷分析任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {jobs.map((job) => {
        const lineName = job.line_name || job.line_code || "-";
        return (
          <Card
            key={job.id}
            size="small"
            hoverable
            className="admin-fl-analysis-job-card"
          >
            <div className="flex flex-col">
              <div className="admin-fl-analysis-job-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
                <ThunderboltOutlined className="text-base text-gray-500" />
                <Typography.Text strong className="truncate">
                  {job.job_name || lineName}
                </Typography.Text>
                <Tag color={statusColor(job.status)}>{job.status}</Tag>
              </div>

              <div className="flex flex-col gap-2 px-4 py-3">
                <div className="flex items-center gap-2">
                  <ApartmentOutlined className="text-xs text-gray-500" />
                  <Typography.Text type="secondary" className="text-xs truncate">
                    {lineName}
                  </Typography.Text>
                </div>
                <div className="flex items-center gap-2">
                  <DeploymentUnitOutlined className="text-xs text-gray-500" />
                  <Typography.Text type="secondary" className="text-xs">
                    {formatJobType(job.job_type, mitigationMode(job))}
                  </Typography.Text>
                </div>
                <div className="flex items-center gap-2">
                  <ClockCircleOutlined className="text-xs text-gray-500" />
                  <Typography.Text type="secondary" className="text-xs">
                    创建：{formatDateTime(job.create_date)} / 完成：{formatDateTime(job.finished_at)}
                  </Typography.Text>
                </div>
                <div className="flex items-center gap-2">
                  <DeploymentUnitOutlined className="text-xs text-gray-500" />
                  <Typography.Text type="secondary" className="text-xs">
                    杆塔：{job.total_tower_count} / 结果：{job.result_tower_count}
                  </Typography.Text>
                </div>
              </div>

              <div className="admin-fl-analysis-job-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
                <Space>
                  {canReadLogs ? (
                    <Button
                      type="link"
                      size="small"
                      disabled={!job.task_id}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpenLog?.(job.task_id, "任务执行日志", job.job_name || job.line_name || job.line_code || "防雷任务");
                      }}
                    >
                      查看日志
                    </Button>
                  ) : null}
                </Space>
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: "delete",
                        label: (
                          <Space size={4}>
                            <DeleteOutlined />
                            <span>删除</span>
                          </Space>
                        ),
                        danger: true,
                        disabled: isJobLocked(job),
                        onClick: (event) => {
                          event.domEvent.stopPropagation();
                          onDeleteJob(job);
                        },
                      },
                    ],
                  }}
                  trigger={["click"]}
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                    }}
                  />
                </Dropdown>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
