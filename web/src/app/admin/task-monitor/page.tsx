"use client";

import Link from "next/link";
import dayjs from "dayjs";
import type { ComponentType, RefAttributes } from "react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  type CardProps,
  type TableColumnsType,
} from "antd";
import { CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, FileTextOutlined, SearchOutlined, SyncOutlined, UnorderedListOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { ModoPagination, modoTablePagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";
import { getTaskDisplayName } from "@/lib/celery-task-display";
import { measureTableScrollY } from "@/lib/table-scroll-y";
import {
  formatTaskMonitorDuration,
  formatTaskMonitorErrorMessage,
  getQueueDisplayName,
  getTaskStateDisplay,
} from "@/lib/task-monitor-display";

const { Text } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const TASK_MONITOR_TABLE_MIN_SCROLL_Y = 180;
const TASK_MONITOR_TABLE_FALLBACK_RESERVE = 220;

/** 状态过滤选项（与后端 STATE_LABELS 合法状态集一致，后端忽略未知值） */
const TASK_STATE_FILTER_OPTIONS = [
  "PENDING",
  "RECEIVED",
  "STARTED",
  "SCHEDULED",
  "RETRY",
  "SUCCESS",
  "FAILURE",
  "REVOKED",
] as const;

/** Response type from /api/v1/admin/task-monitor/overview */
type OverviewStateBucketItem = {
  key: string;
  label: string;
  count: number;
};

type OverviewQueueItem = {
  name: string;
  pending_count: number;
};

type OverviewMonitorTaskItem = {
  task_id: string;
  name: string;
  state: string;
  queue_name: string | null;
  worker: string | null;
  retries: number;
  eta: string | null;
  started_at: string | null;
  done_at: string | null;
  runtime_seconds: number | null;
  error: string | null;
};

type OverviewMonitorWorkerItem = {
  worker: string;
  online: boolean;
  queue_names: string[];
  max_concurrency: number;
  prefetch_count: number;
  uptime_seconds: number;
  processed_total: number;
  active_count: number;
  reserved_count: number;
  scheduled_count: number;
};

type TaskMonitorOverviewResponse = {
  generated_at: string;
  workers: OverviewMonitorWorkerItem[];
  tasks: OverviewMonitorTaskItem[];
  total: number;
  /** 全量（按关键词过滤后）任务状态分桶聚合 */
  task_state_buckets?: OverviewStateBucketItem[];
  /** Redis 队列中待消费消息总数 */
  queue_pending_total?: number;
  queues?: OverviewQueueItem[];
};

/** 顶部统计卡片数据（由 task_state_buckets 聚合得出） */
type TaskMonitorStats = {
  ready: boolean;
  total: number;
  running: number;
  pending: number;
  success: number;
  failed: number;
  share: (count: number) => string;
  queueCount: number;
  queuePending: number;
};

type TaskTableRow = {
  key: string;
  task_id: string;
  name: string;
  state: string;
  queue_name: string | null;
  worker: string;
  started_at: string | null;
  finished_at: string | null;
  runtime_seconds: number | null;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}

function renderTaskStateTag(state: string, t: (s: string) => string) {
  const display = getTaskStateDisplay(state, t);
  const isRunning = ["STARTED", "RUNNING"].includes(state?.toUpperCase());
  return (
    <Tag color={display.color} className={isRunning ? "admin-task-tag-running" : undefined}>
      {isRunning && <Spin size="small" style={{ marginRight: 4 }} />}
      {display.label}
    </Tag>
  );
}

export default function AdminTaskMonitorPage() {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();
  const canRead = hasPermission("celery.read") || hasPermission("celery.manage");
  const canManage = hasPermission("celery.manage");

  const [pendingKeyword, setPendingKeyword] = useState("");
  const [taskKeyword, setTaskKeyword] = useState("");
  const [pendingState, setPendingState] = useState<string | undefined>(undefined);
  const [taskState, setTaskState] = useState<string | undefined>(undefined);
  const [searchVersion, setSearchVersion] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(TASK_MONITOR_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [logTaskId, setLogTaskId] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);

  const handleViewLog = useCallback((taskId: string) => {
    setLogTaskId(taskId);
    setLogOpen(true);
  }, []);

  const handleCloseLogModal = useCallback(() => {
    setLogOpen(false);
    setLogTaskId(null);
  }, []);

  const resetTaskListPagination = useCallback(() => {
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const overviewQuery = useQuery({
    queryKey: ["task-monitor-overview", paginationCurrent, paginationPageSize, taskKeyword, taskState, searchVersion],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const params = new URLSearchParams({
        offset: String((paginationCurrent - 1) * paginationPageSize),
        limit: String(paginationPageSize),
      });
      if (taskKeyword.trim()) {
        params.set("keyword", taskKeyword.trim());
      }
      if (taskState) {
        params.set("state", taskState);
      }
      const response = await fetchWithAuth(`/api/v1/admin/task-monitor/overview?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TaskMonitorOverviewResponse;
    },
    placeholderData: (previousData) => previousData,
    staleTime: 5_000,
  });

  const overviewData = overviewQuery.data;

  // 顶部统计卡：表格/卡片视图共用（同一关键词下聚合口径一致，均来自后端全量分桶）
  const activeOverview = overviewData;

  const taskStats = useMemo<TaskMonitorStats>(() => {
    const buckets = activeOverview?.task_state_buckets ?? [];
    const countOf = (states: string[]) =>
      buckets
        .filter((bucket) => states.includes((bucket.key || "").toUpperCase()))
        .reduce((sum, bucket) => sum + (Number(bucket.count) || 0), 0);
    const total = activeOverview?.total ?? 0;
    return {
      ready: Boolean(activeOverview),
      total,
      running: countOf(["STARTED", "RUNNING"]),
      pending: countOf(["PENDING", "RECEIVED", "SCHEDULED", "RETRY"]),
      success: countOf(["SUCCESS"]),
      failed: countOf(["FAILURE", "REVOKED"]),
      share: (count: number) => (total > 0 ? `${((count / total) * 100).toFixed(1)}%` : "-"),
      queueCount: activeOverview?.queues?.length ?? 0,
      queuePending: activeOverview?.queue_pending_total ?? 0,
    };
  }, [activeOverview]);

  const handleDeleteTask = useCallback(async (taskId: string) => {
    setDeletingTaskId(taskId);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/task-monitor/tasks/${encodeURIComponent(taskId)}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      overviewQuery.refetch();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("删除任务失败");
      Modal.error({ title: t("删除任务失败"), content: message });
    } finally {
      setDeletingTaskId(null);
    }
  }, [fetchWithAuth, overviewQuery]);

  const confirmDeleteTask = useCallback((taskId: string) => {
    Modal.confirm({
      title: `${t("确认删除任务")} ${taskId}${t("？")}`,
      okText: t("删除"),
      cancelText: t("取消"),
      okButtonProps: { danger: true },
      onOk: () => handleDeleteTask(taskId),
    });
  }, [handleDeleteTask]);

  const taskColumns = useMemo<TableColumnsType<TaskTableRow>>(
    () => [
      {
        title: t("任务 ID"),
        dataIndex: "task_id",
        key: "task_id",
        width: 286,
        ellipsis: { showTitle: false },
        render: (value: string) => (
          <Text copyable style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }}>
            {value}
          </Text>
        ),
      },
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        width: 242,
        render: (value: string) => getTaskDisplayName(value, t),
      },
      {
        title: t("状态"),
        dataIndex: "state",
        key: "state",
        width: 121,
        render: (value: string) => renderTaskStateTag(value, t),
      },
      {
        title: t("开始时间"),
        dataIndex: "started_at",
        key: "started_at",
        width: 198,
        render: (value: string | null) => (
          <span style={{ whiteSpace: 'nowrap' }}>{formatDateTime(value)}</span>
        ),
      },
      {
        title: t("完成时间"),
        dataIndex: "finished_at",
        key: "finished_at",
        width: 198,
        render: (value: string | null) => (
          <span style={{ whiteSpace: 'nowrap' }}>{formatDateTime(value)}</span>
        ),
      },
      {
        title: t("运行时长"),
        dataIndex: "runtime_seconds",
        key: "runtime_seconds",
        width: 121,
        render: (value: number | null) => formatTaskMonitorDuration(value, t),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 160,
        fixed: "right",
        render: (_: unknown, record: TaskTableRow) => (
          <ModoActionGroup
            actions={[
              { key: "log", label: t("日志"), onClick: () => handleViewLog(record.task_id) },
              {
                key: "delete",
                label: t("删除"),
                danger: true,
                loading: deletingTaskId === record.task_id,
                disabled: !canManage,
                onClick: () => confirmDeleteTask(record.task_id),
              },
            ]}
          />
        ),
      },
    ],
    [handleViewLog, canManage, deletingTaskId, confirmDeleteTask],
  );

  const allTaskRows = useMemo<TaskTableRow[]>(() => {
    const tasks = overviewData?.tasks || [];
    return tasks.map((task) => ({
      task_id: task.task_id,
      name: task.name,
      state: task.state,
      worker: task.worker || "-",
      queue_name: task.queue_name,
      started_at: task.started_at,
      finished_at: task.done_at,
      runtime_seconds: task.runtime_seconds,
      key: `overview:${task.task_id}`,
    }));
  }, [overviewData]);

  // 关键词已由后端过滤并分页，当前页数据即 overviewData.tasks；
  // 分页总数使用后端真实 total（服务端过滤后计数）。
  const taskTotal = overviewData?.total ?? 0;

  // 删除/筛选后 total 缩小，若 current 超出最大页则回退到最后一页，避免空白页
  useEffect(() => {
    if (taskTotal <= 0) {
      return;
    }
    const maxPage = Math.max(1, Math.ceil(taskTotal / paginationPageSize));
    if (paginationCurrent > maxPage) {
      setPagination((prev) => ({ ...prev, current: maxPage }));
    }
  }, [taskTotal, paginationPageSize, paginationCurrent]);

  const handleSearch = useCallback(() => {
    setSearchVersion((prev) => prev + 1);
    setTaskKeyword(pendingKeyword);
    setTaskState(pendingState);
    resetTaskListPagination();
  }, [pendingKeyword, pendingState, resetTaskListPagination]);

  // 状态过滤即时生效：Select 变更（含清除）即应用并重置分页
  const handleStateChange = useCallback(
    (value: string | undefined) => {
      setPendingState(value);
      setTaskState(value);
      resetTaskListPagination();
    },
    [resetTaskListPagination],
  );

  const overviewErrorMessage =
    overviewQuery.error instanceof Error
      ? formatTaskMonitorErrorMessage(
          overviewQuery.error?.message ?? "",
          t("任务监控概览数据加载失败，请稍后重试。"),
          t,
        )
      : "";

  useToastFeedback({
    errorMessage: overviewErrorMessage,
  });

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorTop = anchor.getBoundingClientRect().top;
    let nextHeight = Math.floor(window.innerHeight - anchorTop - TASK_MONITOR_TABLE_FALLBACK_RESERVE);
    // 站点级样式（globals.css）把表格锚点拉伸为撑满白卡的 flex 列，旧公式
    // wrapper.height - body.height 会把拉伸空白误算成外围高度，导致表体被钳在
    // 最小值、未占满剩余空间就出现纵向滚动条；改用统一测量工具按实际
    // chrome（表头+分页+边框）与滚动容器底边计算，两种布局都稳定收敛
    const measuredHeight = measureTableScrollY(anchor);
    if (measuredHeight !== null) {
      nextHeight = measuredHeight;
    }

    const clampedHeight = Math.max(TASK_MONITOR_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "table") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [
    overviewQuery.isFetching,
    allTaskRows.length,
    updateTableScrollY,
    viewMode,
  ]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "table") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    if (viewMode !== "table") {
      return;
    }

    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollY, viewMode]);

  const statCards = useMemo(
    () => [
      {
        key: "total",
        label: t("任务总数"),
        value: taskStats.ready ? String(taskStats.total) : "—",
        hint: taskStats.ready
          ? `${t("队列")} ${taskStats.queueCount} · ${t("排队消息")} ${taskStats.queuePending}`
          : "",
        icon: <UnorderedListOutlined />,
        tone: "#4d5e7d",
        toneBg: "#eff4f9",
      },
      {
        key: "running",
        label: t("执行中"),
        value: taskStats.ready ? String(taskStats.running) : "—",
        hint: taskStats.ready ? `${t("占比")} ${taskStats.share(taskStats.running)}` : "",
        icon: <SyncOutlined />,
        tone: "#3261ce",
        toneBg: "rgba(50, 97, 206, 0.08)",
      },
      {
        key: "pending",
        label: t("待执行"),
        value: taskStats.ready ? String(taskStats.pending) : "—",
        hint: taskStats.ready ? `${t("占比")} ${taskStats.share(taskStats.pending)}` : "",
        icon: <ClockCircleOutlined />,
        tone: "#cb7f16",
        toneBg: "rgba(245, 166, 35, 0.12)",
      },
      {
        key: "success",
        label: t("成功"),
        value: taskStats.ready ? String(taskStats.success) : "—",
        hint: taskStats.ready ? `${t("占比")} ${taskStats.share(taskStats.success)}` : "",
        icon: <CheckCircleOutlined />,
        tone: "#36a071",
        toneBg: "rgba(85, 188, 138, 0.14)",
      },
      {
        key: "failed",
        label: t("失败"),
        value: taskStats.ready ? String(taskStats.failed) : "—",
        hint: taskStats.ready ? `${t("占比")} ${taskStats.share(taskStats.failed)}` : "",
        icon: <CloseCircleOutlined />,
        tone: "#c3342f",
        toneBg: "rgba(195, 52, 47, 0.1)",
      },
    ],
    [t, taskStats],
  );

  const renderTaskCard = (task: TaskTableRow) => (
    <AntCard
      key={task.key}
      className="admin-task-monitor-task-card"
      size="small"
      hoverable
      onClick={() => handleViewLog(task.task_id)}
    >
      <div className="admin-task-monitor-task-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
        <Typography.Text strong ellipsis={{ tooltip: getTaskDisplayName(task.name, t) }} className="truncate flex-1">
          {getTaskDisplayName(task.name, t)}
        </Typography.Text>
        <div className="flex flex-shrink-0 items-center gap-2">
          {renderTaskStateTag(task.state, t)}
        </div>
      </div>
      <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("任务 ID")}</Typography.Text>
          <Typography.Text
            copyable
            ellipsis={{ tooltip: task.task_id }}
            onClick={(event) => event.stopPropagation()}
          >
            {task.task_id}
          </Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("队列")}</Typography.Text>
          <Typography.Text>{getQueueDisplayName(task.queue_name, t)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("节点")}</Typography.Text>
          <Typography.Text ellipsis={{ tooltip: task.worker || "-" }}>
            {task.worker || "-"}
          </Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("开始")}</Typography.Text>
          <Typography.Text>{formatDateTime(task.started_at)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("完成")}</Typography.Text>
          <Typography.Text>{formatDateTime(task.finished_at)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">{t("时长")}</Typography.Text>
          <Typography.Text>{formatTaskMonitorDuration(task.runtime_seconds, t)}</Typography.Text>
        </div>
      </Space>
      <div className="admin-task-monitor-task-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
        <div />
        <Space size="small" className="shrink-0">
          <Tooltip title={t("日志")}>
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                handleViewLog(task.task_id);
              }}
            />
          </Tooltip>
        </Space>
      </div>
    </AntCard>
  );

  if (initializing) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问任务监控页面。")}</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          {t("返回首页")}
        </Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问任务监控页面的权限，请联系管理员开通相关权限。")}</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          {t("返回首页")}
        </Link>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="modo-page-tabs"
        items={[
          {
            key: "list",
            label: <>{t("任务监控")}</>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="modo-page-card admin_task_monitor_list_pane">
        <div className="admin-task-monitor-stats">
          {statCards.map((card) => (
            <div key={card.key} className="admin-task-monitor-stat-card">
              <div
                className="admin-task-monitor-stat-icon"
                style={{ color: card.tone, background: card.toneBg }}
              >
                {card.icon}
              </div>
              <div className="admin-task-monitor-stat-meta">
                <div className="admin-task-monitor-stat-label">{card.label}</div>
                <div className="admin-task-monitor-stat-value">{card.value}</div>
                <div className="admin-task-monitor-stat-hint">{card.hint}</div>
              </div>
            </div>
          ))}
        </div>
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label={t("任务")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  maxLength={200}
                  placeholder={t("按任务 ID / 任务名称筛选")}
                  value={pendingKeyword}
                  onChange={(event) => {
                    setPendingKeyword(event.target.value);
                  }}
                  onPressEnter={handleSearch}
                  style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                />
              </Form.Item>

              <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                <Select
                  allowClear
                  style={{ minWidth: 132 }}
                  placeholder={t("全部状态")}
                  value={taskState}
                  onChange={handleStateChange}
                  options={TASK_STATE_FILTER_OPTIONS.map((state) => ({
                    value: state,
                    label: getTaskStateDisplay(state, t).label,
                  }))}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
                  className="admin-search-btn" loading={overviewQuery.isFetching}
                >
                  {t("查询")}
                </Button>
              </Form.Item>
            </Form>
          </div>
        ) : (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label={t("任务")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  maxLength={200}
                  placeholder={t("按任务 ID / 任务名称筛选")}
                  value={pendingKeyword}
                  onChange={(event) => {
                    setPendingKeyword(event.target.value);
                  }}
                  onPressEnter={handleSearch}
                />
              </Form.Item>

              <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                <Select
                  allowClear
                  style={{ minWidth: 132 }}
                  placeholder={t("全部状态")}
                  value={taskState}
                  onChange={handleStateChange}
                  options={TASK_STATE_FILTER_OPTIONS.map((state) => ({
                    value: state,
                    label: getTaskStateDisplay(state, t).label,
                  }))}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
                  className="admin-search-btn" loading={overviewQuery.isFetching}
                >
                  {t("查询")}
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}


        {!overviewData && !overviewQuery.isFetching && (
          <div className="mt-4">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("暂无任务监控数据")}
            />
          </div>
        )}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-task-monitor-table-anchor"
            style={{ "--admin-task-monitor-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<TaskTableRow>
              rowKey={(record) => record.task_id}
              columns={taskColumns}
              dataSource={allTaskRows}
              loading={overviewQuery.isFetching}
              tableLayout="fixed"
              pagination={modoTablePagination({
                current: paginationCurrent,
                pageSize: paginationPageSize,
                total: Math.max(taskTotal, 1),
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              })}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("未找到符合筛选条件的任务。")}
                  />
                ),
              }}
              scroll={{ x: 1190, y: tableScrollY }}
            />
          </div>
        ) : (
          <div className="admin-task-monitor-card-view">
            {overviewQuery.isFetching && allTaskRows.length === 0 ? (
              <div className="admin-task-monitor-card-view-state">
                <Spin />
              </div>
            ) : allTaskRows.length === 0 ? (
              <div className="admin-task-monitor-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("未找到符合筛选条件的任务。")}
                />
              </div>
            ) : (
              <div className="admin-task-monitor-card-view-content">
                <Row gutter={[12, 12]}>
                  {allTaskRows.map((task) => (
                    <Col key={task.key} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderTaskCard(task)}
                    </Col>
                  ))}
                </Row>
              </div>
            )}
            <ModoPagination
              current={paginationCurrent}
              pageSize={paginationPageSize}
              total={Math.max(taskTotal, 1)}
              onChange={(page, pageSize) => {
                setPagination({ current: page, pageSize });
              }}
              style={{ flexShrink: 0, marginTop: "auto" }}
            />
          </div>
        )}
              </div>
            ),
          },
        ]}
      />

      <TaskLogViewerDrawer
        taskId={logTaskId}
        title={`${t("任务执行日志")} - ${logTaskId ?? ""}`}
        open={logOpen}
        onClose={handleCloseLogModal}
      />
    </div>
  );
}
