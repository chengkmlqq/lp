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
  Drawer,
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
  getTaskStateDisplay,
} from "@/lib/task-monitor-display";

const { Text } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const TASK_MONITOR_TABLE_MIN_SCROLL_Y = 180;
const TASK_MONITOR_TABLE_VIEWPORT_GAP = 40;
const TASK_MONITOR_TABLE_FALLBACK_RESERVE = 220;

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
  total: number;
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

export default function AdminTaskMonitorPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();
  const canRead = hasPermission("celery.read") || hasPermission("celery.manage");
  const canManage = hasPermission("celery.manage");

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
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [logModalVisible, setLogModalVisible] = useState(false);
  const [logModalContent, setLogModalContent] = useState("");
  const [logModalTaskId, setLogModalTaskId] = useState("");
  const [logModalLoading, setLogModalLoading] = useState(false);
  const [logModalStreaming, setLogModalStreaming] = useState(false);
  const [logModalStatus, setLogModalStatus] = useState("");
  const logEventSourceRef = useRef<EventSource | null>(null);
  const logModalContentRef = useRef<HTMLPreElement | null>(null);
  // 断线补偿游标：记录最近一条 SSE 事件的 id；重连时作为 lastEventId 查询参数传回服务端
  const logLastEventIdRef = useRef("");
  // 重连指数退避（秒）：1 / 2 / 4 / 8 / 16 → 最多 30
  const logRetryDelayRef = useRef(1);
  // 弹窗可见性：关闭后遗留的重连定时器不得重新拉起弹窗
  const logModalVisibleRef = useRef(false);
  // handleViewLog / reconnectLogEventSource 相互引用，经 ref 打破循环
  const handleViewLogRef = useRef<((taskId: string, cancelledRef?: { current: boolean }) => Promise<void>) | null>(null);
  const reconnectLogEventSourceRef = useRef<((cancelledRef: { current: boolean }, taskId: string) => void) | null>(null);

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

  /**
   * 断线重连：关闭旧连接（终止 EventSource 自动"复用旧 URL + 旧 ticket"导致的 401 循环），
   * 指数退避后重新签发 ticket 并重建连接；lastEventId 游标随查询参数传回，断线日志不丢。
   */
  const reconnectLogEventSource = useCallback((cancelledRef: { current: boolean }, taskId: string) => {
    if (cancelledRef.current) return;
    closeLogEventSource();
    setLogModalStreaming(false);
    const delay = logRetryDelayRef.current;
    logRetryDelayRef.current = Math.min(30, delay * 2);
    setLogModalStatus("重连中");
    window.setTimeout(() => {
      if (cancelledRef.current || !logModalVisibleRef.current) return;
      void handleViewLogRef.current?.(taskId, cancelledRef);
    }, delay * 1000);
  }, [closeLogEventSource]);
  useEffect(() => {
    reconnectLogEventSourceRef.current = reconnectLogEventSource;
  }, [reconnectLogEventSource]);

  const handleViewLog = useCallback(async (taskId: string, cancelledRef?: { current: boolean }) => {
    const cancelled = cancelledRef ?? { current: false };
    setLogModalTaskId(taskId);
    setLogModalVisible(true);
    logModalVisibleRef.current = true;
    if (!cancelledRef) {
      // 首次打开时重置重连状态
      setLogModalLoading(true);
      setLogModalContent("");
      setLogModalStatus("");
      logLastEventIdRef.current = "";
      logRetryDelayRef.current = 1;
    }
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
      const params = new URLSearchParams({ ticket: ticketPayload.ticket });
      // 断线重连：重建连接后浏览器不会自动带 Last-Event-ID header，须显式传查询参数，
      // 后端 sse 端点同时兼容 header 与 lastEventId 查询参数两种来源
      if (logLastEventIdRef.current) {
        params.set("lastEventId", logLastEventIdRef.current);
      }
      const es = new EventSource(
        `${API_BASE_URL}/api/v1/admin/task-logs/${encodeURIComponent(taskId)}/sse?${params.toString()}`,
      );
      logEventSourceRef.current = es;

      es.onopen = () => {
        if (cancelled.current) return;
        logRetryDelayRef.current = 1;
        setLogModalLoading(false);
        setLogModalStreaming(true);
        setLogModalStatus("");
      };

      es.onmessage = (e) => {
        if (cancelled.current) return;
        if (e.lastEventId) {
          logLastEventIdRef.current = e.lastEventId;
        }
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
        if (cancelled.current) return;
        es.close();
        logEventSourceRef.current = null;
        setLogModalStreaming(false);
        setLogModalStatus("任务已完成");
      });

      es.addEventListener("error", (e) => {
        if (cancelled.current) return;
        // error 事件也可能由 `event: error` 自定义事件触发（服务端推送的明确错误）
        const eventSourceError = e as MessageEvent<string>;
        try {
          const data = JSON.parse(eventSourceError.data ?? "") as { message?: string };
          if (data.message) {
            setLogModalContent(data.message);
            setLogModalStreaming(false);
            return;
          }
        } catch {
          // 普通连接错误：关闭旧连接，重新取票并重建连接（ticket 已过期 / 连接中断）
        }
        reconnectLogEventSourceRef.current?.(cancelled, taskId);
      });
    } catch (error) {
      if (cancelled.current) return;
      const errorMessage = error instanceof Error ? error.message : "获取日志失败";
      setLogModalContent(`错误：${errorMessage}`);
      setLogModalLoading(false);
      reconnectLogEventSourceRef.current?.(cancelled, taskId);
    }
  }, [fetchWithAuth, closeLogEventSource]);
  useEffect(() => {
    handleViewLogRef.current = handleViewLog;
  }, [handleViewLog]);

  const handleCloseLogModal = () => {
    logModalVisibleRef.current = false;
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

  const overviewQuery = useQuery({
    queryKey: ["task-monitor-overview"],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/task-monitor/overview?task_limit=500&history_limit=100");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TaskMonitorOverviewResponse;
    },
    staleTime: 5_000,
  });

  const overviewData = overviewQuery.data;

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
      const message = error instanceof Error ? error.message : "删除任务失败";
      Modal.error({ title: "删除任务失败", content: message });
    } finally {
      setDeletingTaskId(null);
    }
  }, [fetchWithAuth, overviewQuery]);

  const confirmDeleteTask = useCallback((taskId: string) => {
    Modal.confirm({
      title: `确认删除任务 ${taskId}？`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => handleDeleteTask(taskId),
    });
  }, [handleDeleteTask]);

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
        width: 200,
        fixed: "right",
        render: (_: unknown, record: TaskTableRow) => (
          <Space wrap>
            <Button size="small" onClick={() => handleViewLog(record.task_id)}>
              日志
            </Button>
            <Button
              size="small"
              danger
              loading={deletingTaskId === record.task_id}
              disabled={!canManage}
              onClick={() => confirmDeleteTask(record.task_id)}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ],
    [handleViewLog, canManage, deletingTaskId, confirmDeleteTask],
  );

  const allTaskRows = useMemo<TaskTableRow[]>(() => {
    const tasks = overviewData?.tasks || [];
    return tasks.map((task, index) => ({
      task_id: task.task_id,
      name: task.name,
      state: task.state,
      worker: task.worker || "-",
      queue_name: task.queue_name,
      started_at: task.started_at,
      finished_at: task.done_at,
      runtime_seconds: task.runtime_seconds,
      key: `overview:${task.task_id}:${index}`,
    }));
  }, [overviewData]);

  const filteredTaskRows = useMemo(() => {
    const keyword = taskKeyword.trim();
    return allTaskRows.filter((item) => {
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
        getTaskStateDisplay(item.state).label,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword.toLowerCase());
    });
  }, [allTaskRows, taskKeyword]);

  // 分页总数：有关键词时后端过滤在前端完成，总数以本地筛选结果为准；
  // 无关键词时使用后端真实 total（删除任务后 refetch 自动更新，不再固定 500）
  const taskTotal = useMemo(() => {
    if (taskKeyword.trim()) {
      return filteredTaskRows.length;
    }
    return overviewData?.total ?? filteredTaskRows.length;
  }, [overviewData, filteredTaskRows, taskKeyword]);

  const handleSearch = useCallback(() => {
    setTaskKeyword(pendingKeyword);
    resetTaskListPagination();
  }, [pendingKeyword, resetTaskListPagination]);

  const handleResetFilters = () => {
    setTaskKeyword("");
    setPendingKeyword("");
    resetTaskListPagination();
  };

  const overviewErrorMessage = overviewQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(overviewQuery.error.message, "任务监控概览数据加载失败，请稍后重试。")
    : "";

  useToastFeedback({
    errorMessage: overviewErrorMessage,
  });

  useEffect(() => {
    if (viewMode !== "card" || overviewQuery.isFetching) {
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
  }, [overviewQuery.isFetching, cardViewPage, filteredTaskRows, paginationPageSize, viewMode]);

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
      if (isLoadingMore || overviewQuery.isFetching) {
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
  }, [allLoadedTasks.length, overviewQuery.isFetching, filteredTaskRows.length, isLoadingMore, viewMode]);

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
    overviewQuery.isFetching,
    filteredTaskRows.length,
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


        {!overviewData && !overviewQuery.isFetching && (
          <div className="mt-4">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无任务监控数据"
            />
          </div>
        )}

        {overviewData && viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-task-monitor-table-anchor"
            style={{ "--admin-task-monitor-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<TaskTableRow>
              rowKey={(record) => record.key}
              columns={taskColumns}
              dataSource={filteredTaskRows}
              loading={overviewQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: paginationCurrent,
                pageSize: paginationPageSize,
                total: Math.max(Math.min(taskTotal, filteredTaskRows.length), 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${taskTotal} 条`,
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
        ) : overviewData ? (
          <div className="admin-task-monitor-card-view">
            {overviewQuery.isFetching && allLoadedTasks.length === 0 ? (
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

      <Drawer
        title={`任务执行日志 - ${logModalTaskId}`}
        width={800}
        open={logModalVisible}
        onClose={handleCloseLogModal}
        destroyOnClose
      >
        {logModalLoading ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin tip="加载日志中..." />
          </div>
        ) : (
          <>
            <Space
              style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }}
              align="center"
            >
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {logModalStreaming && !logModalStatus && (
                  <>
                    <Spin size="small" />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      任务运行中，实时接收日志...
                    </Text>
                  </>
                )}
                {logModalStatus && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {logModalStatus}
                  </Text>
                )}
              </span>
              {logModalContent && (
                <Button
                  type="link"
                  size="small"
                  onClick={() => navigator.clipboard?.writeText(logModalContent)}
                >
                  复制
                </Button>
              )}
            </Space>
            <pre
              ref={logModalContentRef}
              style={{
                maxHeight: "60vh",
                overflow: "auto",
                padding: "16px",
                backgroundColor: "#0f172a",
                color: "#e2e8f0",
                borderRadius: "4px",
                fontSize: "12px",
                lineHeight: "1.5",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              }}
            >
              {logModalContent || (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={logModalStatus ? logModalStatus : "等待日志..."}
                />
              )}
            </pre>
          </>
        )}
      </Drawer>
    </div>
  );
}
