"use client";

import { Badge, Button, Dropdown, Empty, Progress, Space, Spin, Tooltip, Typography } from "antd";
import {
  ApartmentOutlined,
  BarChartOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DeploymentUnitOutlined,
  FileTextOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ReactNode } from "react";
import { Card } from "@/components/ui-antd";
import type { FlAnalysisJobSummary } from "@/types/auth";

import {
  formatDateTime,
  formatJobType,
  mitigationMode,
} from "./types";

const { Text } = Typography;

type JobCardListProps = {
  jobs: FlAnalysisJobSummary[];
  loading: boolean;
  onDeleteJob: (job: FlAnalysisJobSummary) => void;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
  /** 点击卡片主体打开任务详情（查看结果） */
  onOpenDetail?: (job: FlAnalysisJobSummary) => void;
};

/** 卡片底部操作：默认平铺 2 个直接按钮，其余收进 ⋯ 三点下拉（对齐雷电流幅值统计页）。 */
const MAX_VISIBLE_ACTIONS = 2;

const LOCKED_STATUSES = new Set(["queued", "running"]);

const statusTextMap: Record<string, string> = {
  pending: "待处理",
  queued: "排队中",
  running: "处理中",
  blocked: "阻塞",
  success: "已完成",
  failed: "失败",
};

const badgeStatusMap: Record<string, "success" | "processing" | "error" | "warning" | "default"> = {
  pending: "default",
  queued: "default",
  running: "processing",
  blocked: "error",
  success: "success",
  failed: "error",
};

type CardAction = {
  key: string;
  tooltip: string;
  icon: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onClick: (event: { stopPropagation: () => void }) => void;
};

function isJobLocked(job: FlAnalysisJobSummary) {
  return LOCKED_STATUSES.has(job.status);
}

export function JobCardList({ jobs, loading, onDeleteJob, canReadLogs, onOpenLog, onOpenDetail }: JobCardListProps) {
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

        // 底部操作列表：查看结果/查看日志/删除；多于 2 个时其余收进 ⋯ 三点下拉
        const actions: CardAction[] = [];
        if (onOpenDetail) {
          actions.push({
            key: "result",
            tooltip: "查看结果",
            icon: <BarChartOutlined />,
            onClick: (event) => {
              event.stopPropagation();
              onOpenDetail?.(job);
            },
          });
        }
        if (canReadLogs && onOpenLog) {
          actions.push({
            key: "log",
            tooltip: "查看日志",
            icon: <FileTextOutlined />,
            disabled: !job.task_id,
            onClick: (event) => {
              event.stopPropagation();
              onOpenLog?.(job.task_id, "任务执行日志", job.job_name || job.line_name || job.line_code || "防雷任务");
            },
          });
        }
        actions.push({
          key: "delete",
          tooltip: "删除",
          icon: <DeleteOutlined />,
          danger: true,
          disabled: isJobLocked(job),
          onClick: (event) => {
            event.stopPropagation();
            onDeleteJob(job);
          },
        });
        const visibleActions = actions.slice(0, MAX_VISIBLE_ACTIONS);
        const overflowActions = actions.slice(MAX_VISIBLE_ACTIONS);

        return (
          <Card
            key={job.id}
            size="small"
            hoverable
            className="admin-fl-analysis-job-card"
            onClick={() => onOpenDetail?.(job)}
          >
            <div className="flex flex-col">
              {/* 标题区：状态徽标置于右上角（对齐雷电流幅值统计页） */}
              <div className="admin-fl-analysis-job-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
                <ThunderboltOutlined className="text-base text-gray-500" />
                <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
                  <div className="flex flex-1 min-w-0">
                    <Typography.Text strong className="truncate">
                      {job.job_name || lineName}
                    </Typography.Text>
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-2">
                    <Badge status={badgeStatusMap[job.status] ?? "default"} />
                    <Text type="secondary" className="text-xs">{statusTextMap[job.status] ?? job.status}</Text>
                  </div>
                </div>
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

              {/* 操作区：默认展示 2 个直接按钮，多了才收进 ⋯ 三点下拉 */}
              <div className="admin-fl-analysis-job-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
                <div className="min-w-0">
                  {job.status === "running" ? (
                    <Progress percent={0} size="small" className="flex-1 max-w-40" />
                  ) : null}
                </div>
                <Space size="small" className="shrink-0">
                  {visibleActions.map((action) => (
                    <Tooltip key={action.key} title={action.tooltip}>
                      <Button
                        type="text"
                        size="small"
                        danger={action.danger}
                        disabled={action.disabled}
                        icon={action.icon}
                        onClick={action.onClick}
                      />
                    </Tooltip>
                  ))}
                  {overflowActions.length > 0 ? (
                    <Dropdown
                      menu={{
                        items: overflowActions.map((action) => ({
                          key: action.key,
                          danger: action.danger,
                          disabled: action.disabled,
                          label: (
                            <Space size={4}>
                              {action.icon}
                              <span>{action.tooltip}</span>
                            </Space>
                          ),
                          onClick: (info) => action.onClick(info.domEvent),
                        })),
                      }}
                      trigger={["click"]}
                    >
                      <Tooltip title="更多">
                        <Button
                          type="text"
                          size="small"
                          icon={<MoreOutlined />}
                          onClick={(event) => {
                            event.stopPropagation();
                          }}
                        />
                      </Tooltip>
                    </Dropdown>
                  ) : null}
                </Space>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
