"use client";

import { useMemo } from "react";
import { Button, Dropdown, Empty, Progress, Spin, Table, Tag, Space } from "antd";
import type { MenuProps } from "antd";
import { MoreOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import type { FlAnalysisJobSummary } from "@/types/auth";

import {
  formatDateTime,
  formatJobStatus,
  formatJobType,
  isJobCancellable,
  isJobDetailLocked,
  mitigationMode,
  runningProgressPercent,
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
  /** 取消运行中/排队中的任务（终止执行 + 清理残留进程） */
  onCancelJob?: (job: FlAnalysisJobSummary) => void;
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
  onCancelJob,
  canReadLogs,
  onOpenLog,
  onOpenDetail,
}: JobTableProps) {
  const { t } = useI18n();
  const columns = useMemo<ColumnsType<FlAnalysisJobSummary>>(() => [
    {
      title: t("任务名"),
      dataIndex: "job_name",
      key: "job_name",
      width: 280,
      ellipsis: true,
      render: (value: string | null, job) => value || job.line_name || job.line_code || "-",
    },
    {
      title: t("线路"),
      key: "line",
      width: 200,
      ellipsis: true,
      render: (_value, job) => job.line_name || job.line_code || "-",
    },
    {
      title: t("任务类型"),
      key: "job_type",
      width: 150,
      render: (_value, job) => formatJobType(job.job_type, mitigationMode(job), t),
    },
    {
      title: t("杆塔数"),
      dataIndex: "total_tower_count",
      key: "total_tower_count",
      width: 90,
      align: "center" as const,
    },
    {
      title: t("结果数"),
      dataIndex: "result_tower_count",
      key: "result_tower_count",
      width: 90,
      align: "center" as const,
    },
    {
      title: t("状态"),
      key: "status",
      width: 160,
      align: "center" as const,
      render: (_value, job) =>
        // 运行中在本列展示实时进度条（不再单独建「进度」列）；运行结束后进度条消失，展示状态标签
        job.status === "running" ? (
          <Progress percent={runningProgressPercent(job)} size="small" />
        ) : (
          <Tag color={statusColor(job.status)}>{formatJobStatus(job.status, t)}</Tag>
        ),
    },
    {
      title: t("创建时间"),
      dataIndex: "create_date",
      key: "create_date",
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: t("完成时间"),
      dataIndex: "finished_at",
      key: "finished_at",
      width: 170,
      render: (value: string | null) => formatDateTime(value),
    },
    ...(onDeleteJob
      ? [
          {
            title: t("操作"),
            key: "operation",
            width: 200,
            align: "center" as const,
            fixed: "right" as const,
            render: (_value: unknown, job: FlAnalysisJobSummary) => {
              const menuItems: MenuProps["items"] = [];
              if (onCancelJob && isJobCancellable(job)) {
                menuItems.push({
                  key: "cancel",
                  label: t("取消"),
                  onClick: () => onCancelJob(job),
                });
              }
              if (onDeleteJob) {
                menuItems.push({
                  key: "delete",
                  label: t("删除"),
                  danger: true,
                  disabled: isJobLocked(job),
                  onClick: () => onDeleteJob(job),
                });
              }
              return (
                <Space size={4}>
                  {onOpenDetail ? (
                    <Button
                      type="link"
                      size="small"
                      disabled={isJobDetailLocked(job)}
                      onClick={() => onOpenDetail(job)}
                    >
                      详情
                    </Button>
                  ) : null}
                  {canReadLogs && onOpenLog ? (
                    <Button
                      type="link"
                      size="small"
                      disabled={!job.task_id}
                      onClick={() => onOpenLog(job.task_id, t("任务执行日志"), job.job_name || job.line_name || job.line_code || t("防雷任务"))}
                    >
                      日志
                    </Button>
                  ) : null}
                  {menuItems.length > 0 ? (
                    <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
                      <Button size="small" icon={<MoreOutlined />} />
                    </Dropdown>
                  ) : null}
                </Space>
              );
            },
          },
        ]
      : []),
  ], [onDeleteJob, onCancelJob, canReadLogs, onOpenLog, onOpenDetail]);

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
      scroll={{ x: 1520, y: scrollY }}
      locale={{
        emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无防雷分析任务")} />,
      }}
    />
  );
}
