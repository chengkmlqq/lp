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
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  type CardProps,
  type TableColumnsType,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError, API_BASE_URL } from "@/lib/api";
import { getTaskDisplayName } from "@/lib/celery-task-display";
import {
  formatTaskMonitorDuration,
  formatTaskMonitorErrorMessage,
  getQueueDisplayName,
  getTaskSourceDisplay,
  getTaskStateDisplay,
} from "@/lib/task-monitor-display";

const { Text } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const DEFAULT_RECENT_LIMIT = 100;
const TASK_MONITOR_TABLE_MIN_SCROLL_Y = 180;
const TASK_MONITOR_TABLE_VIEWPORT_GAP = 40;
const TASK_MONITOR_TABLE_FALLBACK_RESERVE = 220;

type FlowerWorkerItem = {
  worker: string;
  status: string;
  queue_names: string[];
  registered_count: number;
  processed_count: number;
  concurrency: number;
  prefetch_count: number;
  active_count: number;
  reserved_count: number;
  scheduled_count: number;
  last_heartbeat_at: string | null;
};

type FlowerWorkersOverviewResponse = {
  generated_at: string;
  workers: FlowerWorkerItem[];
  summary: {
    total: number;
    online: number;
    offline: number;
  };
};

type FlowerTaskItem = {
  task_id: string;
  name: string;
  state: string;
  source: string;
  worker: string;
  queue_name: string | null;
  args_text: string | null;
  kwargs_text: string | null;
  eta: string | null;
  received_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  runtime_seconds: number | null;
  result_text: string | null;
  exception_text: string | null;
};

type FlowerWorkerTaskOverviewResponse = {
  generated_at: string;
  worker: string;
  active_tasks: FlowerTaskItem[];
  reserved_tasks: FlowerTaskItem[];
  scheduled_tasks: FlowerTaskItem[];
  recent_tasks: FlowerTaskItem[];
  summary: {
    active: number;
    reserved: number;
    scheduled: number;
    recent: number;
  };
};

type TaskTableRow = FlowerTaskItem & {
  key: string;
};

/** Response type from /api/v1/admin/task-monitor/overview */
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

function renderTaskStateTag(state: string) {
  const display = getTaskStateDisplay(state);
  const isRunning = ["STARTED", "RUNNING"].includes(state?.toUpperCase());
  return (
    <Tag color={display.color} className={isRunning ? "admin-task-tag-running" : undefined}>
      {isRunning && <Spin size="small" style={{ marginRight: 4 }} />}
      {display.label}
    </Tag>
  );
}

function renderTaskSourceTag(source: string) {
  const display = getTaskSourceDisplay(source);
  return <Tag color={display.color}>{display.label}</Tag>;
}

function containsText(source: string | null | undefined, keyword: string): boolean {
  if (!keyword) {
    return true;
  }
  return (source || "").toLowerCase().includes(keyword.toLowerCase());
}

function toTaskRows(workerName: string, source: string, tasks: FlowerTaskItem[]): TaskTableRow[] {
  return tasks.map((item, index) => ({
    ...item,
    source: item.source || source,
    worker: item.worker || workerName,
    key: `${workerName}:${source}:${item.task_id}:${index + 1}`,
  }));
}

export default function AdminTaskMonitorPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();
  const canRead = hasPermission("celery.read") || hasPermission("celery.manage");

  const [autoRefresh, setAutoRefresh] = useState(false);
  const [pendingKeyword, setPendingKeyword] = useState("");
  const [taskKeyword, setTaskKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(TASK_MONITOR_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedTasks, setAllLoadedTasks] = useState<TaskTableRow[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [logModalVisible, setLogModalVisible] = useState(false);
  const [logModalContent, setLogModalContent] = useState("");
  const [logModalTaskId, setLogModalTaskId] = useState("");
  const [logModalLoading, setLogModalLoading] = useState(false);
  const [logModalStreaming, setLogModalStreaming] = useState(false);
  const [logModalStatus, setLogModalStatus] = useState("");
  const logEventSourceRef = useRef<EventSource | null>(null);
  const logModalContentRef = useRef<HTMLPreElement | null>(null);

  const resetTaskListPagination = useCallback(() => {
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setAllLoadedTasks([]);
    setIsLoadingMore(false);
  }, []);

  const closeLogEventSource = useCallback(() => {
    const es = logEventSourceRef.current;
    if (es) {
      es.close();
      logEventSourceRef.current = null;
    }
  }, []);

  const handleViewLog = async (taskId: string) => {
    setLogModalTaskId(taskId);
    setLogModalVisible(true);
    setLogModalLoading(true);
    setLogModalContent("");
    setLogModalStatus("");
    setLogModalStreaming(false);
    closeLogEventSource();

    try {
      // 1. 先签发一次性 ticket（复用 /api/v1/ws/ticket）
      const ticketRes = await fetchWithAuth("/api/v1/ws/ticket", { method: "POST" });
      if (!ticketRes.ok) {
        const errorText = await readApiError(ticketRes);
        throw new Error(errorText || "获取日志凭证失败");
      }
      const ticketPayload = (await ticketRes.json()) as { ticket: string };
      if (!ticketPayload.ticket) {
        throw new Error("获取日志凭证失败");
      }

      // 2. 建立 SSE 连接（EventSource 无法自定义 Authorization header，走 ticket 查询参数）
      const es = new EventSource(
        `${API_BASE_URL}/api/v1/admin/task-logs/${encodeURIComponent(taskId)}/sse?ticket=${encodeURIComponent(ticketPayload.ticket)}`,
      );
      logEventSourceRef.current = es;

      es.onopen = () => {
        setLogModalLoading(false);
        setLogModalStreaming(true);
      };

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as { line?: string; lines?: string };
          const linesText = data.lines;
          const singleLine = data.line;
          if (linesText) {
            setLogModalContent(linesText);
          } else if (singleLine) {
            setLogModalContent((prev) => (prev ? `${prev}\n${singleLine}` : singleLine));
          }
        } catch {
          // 忽略无法解析的 SSE 数据
        }
      };

      es.addEventListener("done", () => {
        es.close();
        logEventSourceRef.current = null;
        setLogModalStreaming(false);
        setLogModalStatus("任务已完成");
      });

      es.addEventListener("error", (e) => {
        // error 事件也可能由 `event: error` 自定义事件触发
        const eventSourceError = e as MessageEvent<string>;
        try {
          const data = JSON.parse(eventSourceError.data ?? "") as { message?: string };
          if (data.message) {
            setLogModalContent(data.message);
          }
        } catch {
          // 普通连接错误（EventSource 自动重连，无需处理）
        }
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "获取日志失败";
      setLogModalContent(`错误：${errorMessage}`);
      setLogModalLoading(false);
    }
  };

  const handleCloseLogModal = () => {
    closeLogEventSource();
    setLogModalVisible(false);
    setLogModalTaskId("");
    setLogModalContent("");
    setLogModalStatus("");
    setLogModalStreaming(false);
  };

  // 组件卸载时断开 SSE
  useEffect(() => () => closeLogEventSource(), [closeLogEventSource]);

  // 日志追加时自动滚底（仅流式场景）
  useEffect(() => {
    if (!logModalStreaming || logModalStatus) {
      return;
    }
    const el = logModalContentRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logModalContent, logModalStreaming, logModalStatus]);

  const workersOverviewQuery = useQuery({
    queryKey: ["flower-workers-overview"],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/flower/workers?forceRefresh=false");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlowerWorkersOverviewResponse;
    },
    refetchInterval: autoRefresh ? 5_000 : false,
    staleTime: 15_000,
  });

  const workerNames = useMemo(() => (workersOverviewQuery.data?.workers || []).map((item) => item.worker), [workersOverviewQuery.data?.workers]);

  const allTasksQuery = useQuery({
    queryKey: ["flower-worker-tasks-batch", workerNames],
    enabled: Boolean(user) && canRead && workerNames.length > 0,
    queryFn: async () => {
      const settled = await Promise.all(
        workerNames.map(async (worker) => {
          const params = new URLSearchParams();
          params.set("worker", worker);
          params.set("recentLimit", String(DEFAULT_RECENT_LIMIT));
          params.set("forceRefresh", "false");
          const response = await fetchWithAuth(`/api/v1/admin/flower/worker-tasks?${params.toString()}`);
          if (!response.ok) {
            throw new Error(await readApiError(response));
          }
          return (await response.json()) as FlowerWorkerTaskOverviewResponse;
        }),
      );
      return settled;
    },
    refetchInterval: autoRefresh ? 5_000 : false,
    staleTime: 15_000,
  });

  const overviewQuery = useQuery({
    queryKey: ["task-monitor-overview"],
    enabled: Boolean(user) && canRead && workerNames.length === 0,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/task-monitor/overview?task_limit=500&history_limit=100");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TaskMonitorOverviewResponse;
    },
    refetchInterval: autoRefresh ? 10_000 : false,
    staleTime: 30_000,
  });

  const overviewData = overviewQuery.data;

  const workersOverview = useMemo(() => {
    if (workersOverviewQuery.data) {
      return workersOverviewQuery.data;
    }
    if (overviewData && overviewData.workers.length > 0) {
      return {
        generated_at: overviewData.generated_at,
        workers: overviewData.workers.map((w) => ({
          worker: w.worker,
          status: w.online ? "ONLINE" : "OFFLINE",
          queue_names: w.queue_names,
          registered_count: 0,
          processed_count: w.processed_total,
          concurrency: w.max_concurrency,
          prefetch_count: w.prefetch_count,
          active_count: w.active_count,
          reserved_count: w.reserved_count,
          scheduled_count: w.scheduled_count,
          last_heartbeat_at: null,
        })),
        summary: {
          total: overviewData.workers.length,
          online: overviewData.workers.filter((w) => w.online).length,
          offline: overviewData.workers.filter((w) => !w.online).length,
        },
      };
    }
    return workersOverviewQuery.data;
  }, [workersOverviewQuery.data, overviewData]);

  const taskColumns = useMemo<TableColumnsType<TaskTableRow>>(
    () => [
      {
        title: "任务 ID",
        dataIndex: "task_id",
        key: "task_id",
        width: 260,
        ellipsis: { showTitle: false },
        render: (value: string) => (
          <Text copyable style={{ maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }}>
            {value}
          </Text>
        ),
      },
      {
        title: "任务名称",
        dataIndex: "name",
        key: "name",
        width: 220,
        render: (value: string) => getTaskDisplayName(value),
      },
      {
        title: "状态",
        dataIndex: "state",
        key: "state",
        width: 110,
        render: (value: string) => renderTaskStateTag(value),
      },
      {
        title: "队列",
        dataIndex: "queue_name",
        key: "queue_name",
        width: 120,
        render: (value: string | null) => getQueueDisplayName(value),
      },
      {
        title: "执行节点",
        dataIndex: "worker",
        key: "worker",
        width: 220,
        render: (value: string) => value || "-",
      },
      {
        title: "开始时间",
        dataIndex: "started_at",
        key: "started_at",
        width: 180,
        render: (value: string | null) => (
          <span style={{ whiteSpace: 'nowrap' }}>{formatDateTime(value)}</span>
        ),
      },
      {
        title: "完成时间",
        dataIndex: "finished_at",
        key: "finished_at",
        width: 180,
        render: (value: string | null) => (
          <span style={{ whiteSpace: 'nowrap' }}>{formatDateTime(value)}</span>
        ),
      },
      {
        title: "运行时长",
        dataIndex: "runtime_seconds",
        key: "runtime_seconds",
        width: 110,
        render: (value: number | null) => formatTaskMonitorDuration(value),
      },
      {
        title: "操作",
        key: "actions",
        width: 100,
        fixed: "right",
        render: (_: unknown, record: TaskTableRow) => (
          <Space size={4}>
            <Button size="small" onClick={() => handleViewLog(record.task_id)}>
              日志
            </Button>
          </Space>
        ),
      },
    ],
    [handleViewLog],
  );

  const filteredWorkers = useMemo(() => workersOverview?.workers || [], [workersOverview?.workers]);

  const allTaskRows = useMemo(() => {
    const workerTaskOverviews = allTasksQuery.data || [];
    const rows: TaskTableRow[] = [];
    for (const overview of workerTaskOverviews) {
      rows.push(...toTaskRows(overview.worker, "ACTIVE", overview.active_tasks));
      rows.push(...toTaskRows(overview.worker, "RESERVED", overview.reserved_tasks));
      rows.push(...toTaskRows(overview.worker, "SCHEDULED", overview.scheduled_tasks));
      rows.push(...toTaskRows(overview.worker, "RECENT", overview.recent_tasks));
    }

    // Fallback: use overview endpoint data when Flower returns no tasks
    if (rows.length === 0 && overviewData && overviewData.tasks.length > 0) {
      const overviewRows: TaskTableRow[] = overviewData.tasks.map((task, index) => ({
        task_id: task.task_id,
        name: task.name,
        state: task.state,
        source: "RECENT",
        worker: task.worker || "-",
        queue_name: task.queue_name,
        args_text: null,
        kwargs_text: null,
        eta: task.eta,
        received_at: null,
        started_at: task.started_at,
        finished_at: task.done_at,
        runtime_seconds: task.runtime_seconds,
        result_text: null,
        exception_text: task.error,
        key: `overview:${task.task_id}:${index}`,
      }));
      return overviewRows;
    }

    return rows.filter((task) =>
      task.name !== "app.tasks.worker_registry_tasks.sweep_worker_registry_offline" &&
      task.name !== "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks"
    );
  }, [allTasksQuery.data, overviewData]);

  const filteredTaskRows = useMemo(() => {
    const workerSet = new Set(filteredWorkers.map((item) => item.worker));
    const keyword = taskKeyword.trim();
    return allTaskRows.filter((item) => {
      if (!workerSet.has(item.worker)) {
        return false;
      }
      if (!keyword) {
        return true;
      }
      const haystack = [
        item.task_id,
        item.name,
        getTaskDisplayName(item.name),
        item.queue_name || "",
        getQueueDisplayName(item.queue_name),
        item.worker,
        getTaskSourceDisplay(item.source).label,
        getTaskStateDisplay(item.state).label,
        item.args_text || "",
        item.kwargs_text || "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword.toLowerCase());
    });
  }, [allTaskRows, filteredWorkers, taskKeyword]);

  const handleSearch = useCallback(() => {
    setTaskKeyword(pendingKeyword);
    resetTaskListPagination();
    workersOverviewQuery.refetch();
    allTasksQuery.refetch();
  }, [pendingKeyword, resetTaskListPagination]);

  const handleResetFilters = () => {
    setTaskKeyword("");
    setPendingKeyword("");
    resetTaskListPagination();
  };

  const workersOverviewErrorMessage = workersOverviewQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(workersOverviewQuery.error.message, "任务监控数据加载失败，请稍后重试。")
    : "";
  const allTasksErrorMessage = allTasksQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(allTasksQuery.error.message, "任务列表数据加载失败，请稍后重试。")
    : "";
  const overviewErrorMessage = overviewQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(overviewQuery.error.message, "任务监控概览数据加载失败，请稍后重试。")
    : "";
  const anyError = workersOverviewErrorMessage || allTasksErrorMessage || (workersOverviewQuery.data ? "" : overviewErrorMessage);

  useToastFeedback({
    errorMessage: anyError,
  });

  useEffect(() => {
    if (viewMode !== "card" || allTasksQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const nextTasks = filteredTaskRows.slice(0, cardViewPage * paginationPageSize);

      if (cardViewPage === 1) {
        setAllLoadedTasks(() => nextTasks);
      } else {
        setAllLoadedTasks((prev) => {
          if (nextTasks.length === 0) {
            return prev;
          }
          const existingKeys = new Set(prev.map((task) => task.key));
          const newTasks = nextTasks.filter((task) => !existingKeys.has(task.key));
          return [...prev, ...newTasks];
        });
      }

      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [allTasksQuery.isLoading, cardViewPage, filteredTaskRows, paginationPageSize, viewMode]);

  useEffect(() => {
    if (viewMode !== "card") {
      return;
    }

    const pageCard = pageCardRef.current;
    if (!pageCard) {
      return;
    }

    const cardBody = pageCard as HTMLElement;

    const handleScroll = () => {
      if (isLoadingMore || allTasksQuery.isLoading) {
        return;
      }

      const { scrollTop, scrollHeight, clientHeight } = cardBody;
      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = filteredTaskRows.length;
        const loadedCount = allLoadedTasks.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => {
      cardBody.removeEventListener("scroll", handleScroll);
    };
  }, [allLoadedTasks.length, allTasksQuery.isLoading, filteredTaskRows.length, isLoadingMore, viewMode]);

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorTop = anchor.getBoundingClientRect().top;
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - TASK_MONITOR_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? TASK_MONITOR_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - TASK_MONITOR_TABLE_VIEWPORT_GAP);
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
    allTasksQuery.isFetching,
    filteredTaskRows.length,
    updateTableScrollY,
    viewMode,
    workersOverviewQuery.error,
    workersOverviewQuery.isFetching,
    workersOverview?.summary.total,
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

  const renderTaskCard = (task: TaskTableRow) => (
    <AntCard
      key={task.key}
      className="admin-task-monitor-task-card"
      size="small"
      title={
        <Space className="min-w-0" size={8}>
          <Typography.Text strong ellipsis={{ tooltip: getTaskDisplayName(task.name) }}>
            {getTaskDisplayName(task.name)}
          </Typography.Text>
          {renderTaskStateTag(task.state)}
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">任务 ID</Typography.Text>
          <Typography.Text copyable ellipsis={{ tooltip: task.task_id }}>
            {task.task_id}
          </Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">队列</Typography.Text>
          <Typography.Text>{getQueueDisplayName(task.queue_name)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">节点</Typography.Text>
          <Typography.Text ellipsis={{ tooltip: task.worker || "-" }}>
            {task.worker || "-"}
          </Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">开始</Typography.Text>
          <Typography.Text>{formatDateTime(task.started_at)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">完成</Typography.Text>
          <Typography.Text>{formatDateTime(task.finished_at)}</Typography.Text>
        </div>
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">时长</Typography.Text>
          <Typography.Text>{formatTaskMonitorDuration(task.runtime_seconds)}</Typography.Text>
        </div>
        <div style={{ marginTop: 8 }}>
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Button size="small" block onClick={() => handleViewLog(task.task_id)}>
              日志
            </Button>
          </Space>
        </div>
      </Space>
    </AntCard>
  );

  if (initializing) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin tip="初始化中..." />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问任务监控页面。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">你没有访问任务监控页面的权限，请联系管理员开通相关权限。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="admin_task_monitor_tabs"
        items={[
          {
            key: "list",
            label: <span className="admin_task_monitor_tab_title">任务监控</span>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="admin_task_monitor_list_pane">
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="任务" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  maxLength={200}
                  placeholder="按任务 ID / 任务名称筛选"
                  value={pendingKeyword}
                  onChange={(event) => {
                    setPendingKeyword(event.target.value);
                  }}
                  onPressEnter={handleSearch}
                  style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        ) : (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="任务" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  maxLength={200}
                  placeholder="按任务 ID / 任务名称筛选"
                  value={pendingKeyword}
                  onChange={(event) => {
                    setPendingKeyword(event.target.value);
                  }}
                  onPressEnter={handleSearch}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}


        {!workersOverview && !workersOverviewQuery.isFetching && !overviewQuery.isFetching && (
          <div className="mt-4">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无任务监控数据"
            />
          </div>
        )}

        {workersOverview && viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-task-monitor-table-anchor"
            style={{ "--admin-task-monitor-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<TaskTableRow>
              rowKey={(record) => record.key}
              columns={taskColumns}
              dataSource={filteredTaskRows}
              loading={allTasksQuery.isFetching || workersOverviewQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: paginationCurrent,
                pageSize: paginationPageSize,
                total: Math.max(filteredTaskRows.length, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${filteredTaskRows.length} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的任务。"
                  />
                ),
              }}
              scroll={{ x: 1600, y: tableScrollY }}
            />
          </div>
        ) : workersOverview ? (
          <div className="admin-task-monitor-card-view">
            {allTasksQuery.isLoading && allLoadedTasks.length === 0 ? (
              <div className="admin-task-monitor-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedTasks.length === 0 ? (
              <div className="admin-task-monitor-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的任务。"
                />
              </div>
            ) : (
              <div className="admin-task-monitor-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedTasks.map((task) => (
                    <Col key={task.key} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderTaskCard(task)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedTasks.length >= filteredTaskRows.length && allLoadedTasks.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedTasks.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : null}
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={`任务执行日志 - ${logModalTaskId}`}
        open={logModalVisible}
        onCancel={handleCloseLogModal}
        footer={[
          <Button key="close" onClick={handleCloseLogModal}>
            关闭
          </Button>,
        ]}
        width={800}
        style={{ top: 20 }}
      >
        {logModalLoading ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin tip="加载日志中..." />
          </div>
        ) : (
          <>
            {logModalStreaming && !logModalStatus && (
              <div style={{ marginBottom: 8, fontSize: 12, color: "var(--gray-11)" }}>
                <Spin size="small" style={{ marginRight: 6 }} />
                任务运行中，实时接收日志...
              </div>
            )}
            {logModalStatus && (
              <div style={{ marginBottom: 8, fontSize: 12, color: "var(--gray-11)" }}>
                {logModalStatus}
              </div>
            )}
            <pre
              ref={logModalContentRef}
              style={{
                maxHeight: "60vh",
                overflow: "auto",
                padding: "16px",
                backgroundColor: "#f5f5f5",
                borderRadius: "4px",
                fontSize: "12px",
                lineHeight: "1.5",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {logModalContent}
            </pre>
          </>
        )}
      </Modal>
    </div>
  );
}
