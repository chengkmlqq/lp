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
  Tooltip,
  Typography,
  type CardProps,
  type TableColumnsType,
} from "antd";
import { FileTextOutlined, SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";
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
  const [searchVersion, setSearchVersion] = useState(0);
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
    setCardViewPage(1);
    setAllLoadedTasks([]);
    setIsLoadingMore(false);
  }, []);

  const overviewQuery = useQuery({
    queryKey: ["task-monitor-overview", paginationCurrent, paginationPageSize, taskKeyword, searchVersion],
    enabled: Boolean(user) && canRead && viewMode === "table",
    queryFn: async () => {
      const params = new URLSearchParams({
        offset: String((paginationCurrent - 1) * paginationPageSize),
        limit: String(paginationPageSize),
      });
      if (taskKeyword.trim()) {
        params.set("keyword", taskKeyword.trim());
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

  const cardQuery = useQuery({
    queryKey: ["task-monitor-overview-card", cardViewPage, paginationPageSize, taskKeyword, searchVersion],
    enabled: Boolean(user) && canRead && viewMode === "card",
    queryFn: async () => {
      const params = new URLSearchParams({
        offset: String((cardViewPage - 1) * paginationPageSize),
        limit: String(paginationPageSize),
      });
      if (taskKeyword.trim()) {
        params.set("keyword", taskKeyword.trim());
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

  const handleDeleteTask = useCallback(async (taskId: string) => {
    setDeletingTaskId(taskId);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/task-monitor/tasks/${encodeURIComponent(taskId)}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      if (viewMode === "card") {
        setCardViewPage(1);
        setAllLoadedTasks([]);
        setIsLoadingMore(false);
        cardQuery.refetch();
      } else {
        overviewQuery.refetch();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除任务失败";
      Modal.error({ title: "删除任务失败", content: message });
    } finally {
      setDeletingTaskId(null);
    }
  }, [fetchWithAuth, overviewQuery, cardQuery, viewMode]);

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
      align: "right" as const,
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
    if (viewMode !== "table" || taskTotal <= 0) {
      return;
    }
    const maxPage = Math.max(1, Math.ceil(taskTotal / paginationPageSize));
    if (paginationCurrent > maxPage) {
      setPagination((prev) => ({ ...prev, current: maxPage }));
    }
  }, [viewMode, taskTotal, paginationPageSize, paginationCurrent]);

  const handleSearch = useCallback(() => {
    setSearchVersion((prev) => prev + 1);
    setTaskKeyword(pendingKeyword);
    resetTaskListPagination();
  }, [pendingKeyword, resetTaskListPagination]);

  const overviewErrorMessage = (
    viewMode === "table" ? overviewQuery.error : cardQuery.error
  ) instanceof Error
    ? formatTaskMonitorErrorMessage(
        (viewMode === "table" ? overviewQuery.error : cardQuery.error)?.message ?? "",
        "任务监控概览数据加载失败，请稍后重试。",
      )
    : "";

  useToastFeedback({
    errorMessage: overviewErrorMessage,
  });

  useEffect(() => {
    if (viewMode !== "card" || cardQuery.isFetching) {
      return;
    }

    const pageTasks = (cardQuery.data?.tasks ?? []).map((task) => ({
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

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedTasks(() => pageTasks);
      } else {
        setAllLoadedTasks((prev) => {
          if (pageTasks.length === 0) {
            return prev;
          }
          const existingKeys = new Set(prev.map((task) => task.key));
          const newTasks = pageTasks.filter((task) => !existingKeys.has(task.key));
          return [...prev, ...newTasks];
        });
      }

      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [cardQuery.isFetching, cardQuery.data, cardViewPage, viewMode]);

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
      if (isLoadingMore || cardQuery.isFetching) {
        return;
      }

      const { scrollTop, scrollHeight, clientHeight } = cardBody;
      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = cardQuery.data?.total ?? 0;
        const loadedCount = allLoadedTasks.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => {
      cardBody.removeEventListener("scroll", handleScroll);
    };
  }, [allLoadedTasks.length, cardQuery.isFetching, cardQuery.data?.total, isLoadingMore, viewMode]);

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

  const renderTaskCard = (task: TaskTableRow) => (
    <AntCard
      key={task.key}
      className="admin-task-monitor-task-card"
      size="small"
      hoverable
      onClick={() => handleViewLog(task.task_id)}
    >
      <div className="admin-task-monitor-task-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
        <Typography.Text strong ellipsis={{ tooltip: getTaskDisplayName(task.name) }} className="truncate flex-1">
          {getTaskDisplayName(task.name)}
        </Typography.Text>
        <div className="flex flex-shrink-0 items-center gap-2">
          {renderTaskStateTag(task.state)}
        </div>
      </div>
      <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
        <div className="admin-task-monitor-task-card-field">
          <Typography.Text type="secondary">任务 ID</Typography.Text>
          <Typography.Text
            copyable
            ellipsis={{ tooltip: task.task_id }}
            onClick={(event) => event.stopPropagation()}
          >
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
      </Space>
      <div className="admin-task-monitor-task-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
        <div />
        <Space size="small" className="shrink-0">
          <Tooltip title="日志">
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


        {viewMode === "table" && !overviewData && !overviewQuery.isFetching && (
          <div className="mt-4">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无任务监控数据"
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
              pagination={{
                current: paginationCurrent,
                pageSize: paginationPageSize,
                total: Math.max(taskTotal, 1),
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
        ) : (
          <div className="admin-task-monitor-card-view">
            {cardQuery.isFetching && allLoadedTasks.length === 0 ? (
              <div className="admin-task-monitor-card-view-state">
                <Spin />
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
                    <Spin />
                  </div>
                )}
                {allLoadedTasks.length >= (cardQuery.data?.total ?? 0) && allLoadedTasks.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedTasks.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
              </div>
            ),
          },
        ]}
      />

      <TaskLogViewerDrawer
        taskId={logTaskId}
        title={`任务执行日志 - ${logTaskId ?? ""}`}
        open={logOpen}
        onClose={handleCloseLogModal}
      />
    </div>
  );
}
