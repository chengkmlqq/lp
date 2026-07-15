"use client";

import Link from "next/link";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ComponentType, RefAttributes } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Form,
  Input,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
  type CardProps,
  type TableColumnsType,
} from "antd";
import { EyeOutlined, SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";
import { getTaskDisplayName } from "@/lib/celery-task-display";
import {
  formatTaskMonitorDuration,
  formatTaskMonitorErrorMessage,
  getQueueDisplayName,
  getTaskSourceDisplay,
  getTaskStateDisplay,
  normalizeQueueNames,
} from "@/lib/task-monitor-display";

const { Text } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const DEFAULT_RECENT_LIMIT = 100;
const WORKERS_TABLE_MIN_SCROLL_Y = 180;
const WORKERS_TABLE_VIEWPORT_GAP = 40;
const WORKERS_TABLE_FALLBACK_RESERVE = 220;

type WorkerMonitorWorkerItem = {
  worker: string;
  status: string;
  queue_names: string[];
  concurrency: number;
  prefetch_count: number;
  processed_count: number;
  active_count: number;
  reserved_count: number;
  scheduled_count: number;
  registered_count: number;
  last_heartbeat_at: string | null;
};

type WorkerMonitorOverviewResponse = {
  generated_at: string;
  summary: {
    total: number;
    online: number;
    offline: number;
  };
  workers: WorkerMonitorWorkerItem[];
};

type WorkerMonitorTaskItem = {
  task_id: string;
  name: string;
  state: string;
  source: string;
  queue_name: string | null;
  worker: string;
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

type WorkerMonitorTaskOverviewResponse = {
  generated_at: string;
  worker: string;
  summary: {
    active: number;
    reserved: number;
    scheduled: number;
    recent: number;
  };
  active_tasks: WorkerMonitorTaskItem[];
  reserved_tasks: WorkerMonitorTaskItem[];
  scheduled_tasks: WorkerMonitorTaskItem[];
  recent_tasks: WorkerMonitorTaskItem[];
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
  return <Tag color={display.color}>{display.label}</Tag>;
}

function renderTaskSourceTag(source: string) {
  const display = getTaskSourceDisplay(source);
  return <Tag color={display.color}>{display.label}</Tag>;
}

function renderWorkerStatusTag(status: string) {
  return (status || "").toUpperCase() === "ONLINE" ? <Tag color="green">在线</Tag> : <Tag color="default">离线</Tag>;
}

function renderQueueTags(queueNames: string[]) {
  const normalized = normalizeQueueNames(queueNames);
  return normalized.length > 0 ? (
    <Space wrap size={[4, 4]}>
      {normalized.map((queueName) => (
        <Tag key={queueName} color="blue" bordered={false}>
          {getQueueDisplayName(queueName)}
        </Tag>
      ))}
    </Space>
  ) : (
    <Typography.Text type="secondary">-</Typography.Text>
  );
}

function containsText(source: string | null | undefined, keyword: string): boolean {
  if (!keyword) {
    return true;
  }
  return (source || "").toLowerCase().includes(keyword.toLowerCase());
}

function parseStatusFilter(value: string | undefined): "all" | "online" | "offline" {
  if (value === "online" || value === "offline") {
    return value;
  }
  return "all";
}

export default function AdminWorkersPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();
  const canRead = hasPermission("celery.read") || hasPermission("celery.manage");

  const [workerKeyword, setWorkerKeyword] = useState("");
  const [queueKeyword, setQueueKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");
  const [selectedWorker, setSelectedWorker] = useState<string | null>(null);
  const [tableScrollY, setTableScrollY] = useState(WORKERS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";

  const overviewQuery = useQuery({
    queryKey: ["worker-monitor-overview"],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/flower/workers?forceRefresh=true");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as WorkerMonitorOverviewResponse;
    },
    refetchInterval: false,
    staleTime: 15_000,
  });

  const workerTasksPath = useMemo(() => {
    if (!selectedWorker) {
      return null;
    }
    const params = new URLSearchParams();
    params.set("worker", selectedWorker);
    params.set("recentLimit", String(DEFAULT_RECENT_LIMIT));
    params.set("forceRefresh", "true");
    return `/api/v1/admin/flower/worker-tasks?${params.toString()}`;
  }, [selectedWorker]);

  const workerTasksQuery = useQuery({
    queryKey: ["worker-monitor-tasks", workerTasksPath],
    enabled: Boolean(user) && canRead && Boolean(workerTasksPath),
    queryFn: async () => {
      if (!workerTasksPath) {
        throw new Error("missing worker path");
      }
      const response = await fetchWithAuth(workerTasksPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as WorkerMonitorTaskOverviewResponse;
    },
    refetchInterval: false,
    staleTime: 15_000,
  });

  const workerColumns = useMemo<TableColumnsType<WorkerMonitorWorkerItem>>(
    () => [
      {
        title: "执行节点",
        dataIndex: "worker",
        key: "worker",
        width: 220,
        ellipsis: {
          showTitle: false,
        },
        render: (value: string) => (
          <Typography.Text ellipsis={{ tooltip: value || "-" }}>
            {value || "-"}
          </Typography.Text>
        ),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 90,
        align: "center",
        render: (value: string) => renderWorkerStatusTag(value),
      },
      {
        title: "队列",
        dataIndex: "queue_names",
        key: "queue_names",
        width: 180,
        render: (value: string[]) => renderQueueTags(value),
      },
      {
        title: "并发",
        dataIndex: "concurrency",
        key: "concurrency",
        width: 70,
        align: "center",
      },
      {
        title: "预取",
        dataIndex: "prefetch_count",
        key: "prefetch_count",
        width: 70,
        align: "center",
        render: () => 1,
      },
      {
        title: "任务统计",
        key: "runtime_counts",
        width: 130,
        render: (_: unknown, record) => `${record.active_count}/${record.reserved_count}/${record.scheduled_count}`,
      },
      {
        title: "累计处理",
        dataIndex: "processed_count",
        key: "processed_count",
        width: 100,
      },
      {
        title: "注册任务",
        dataIndex: "registered_count",
        key: "registered_count",
        width: 100,
      },
      {
        title: "最近心跳",
        dataIndex: "last_heartbeat_at",
        key: "last_heartbeat_at",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: "操作",
        key: "action",
        width: 110,
        render: (_: unknown, record) => (
          <Button size="small" icon={<EyeOutlined />} onClick={() => setSelectedWorker(record.worker)}>
            任务
          </Button>
        ),
      },
    ],
    [],
  );

  const taskColumns = useMemo<TableColumnsType<WorkerMonitorTaskItem>>(
    () => [
      {
        title: "任务 ID",
        dataIndex: "task_id",
        key: "task_id",
        width: 260,
        render: (value: string) => <Text copyable>{value}</Text>,
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
        title: "监控分组",
        dataIndex: "source",
        key: "source",
        width: 120,
        render: (value: string) => renderTaskSourceTag(value),
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
        title: "ETA",
        dataIndex: "eta",
        key: "eta",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: "接收时间",
        dataIndex: "received_at",
        key: "received_at",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: "开始时间",
        dataIndex: "started_at",
        key: "started_at",
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
        title: "运行时长",
        dataIndex: "runtime_seconds",
        key: "runtime_seconds",
        width: 110,
        render: (value: number | null) => formatTaskMonitorDuration(value),
      },
      {
        title: "位置参数",
        dataIndex: "args_text",
        key: "args_text",
        width: 220,
        render: (value: string | null) => (value ? <Text ellipsis={{ tooltip: value }}>{value}</Text> : "-"),
      },
      {
        title: "关键字参数",
        dataIndex: "kwargs_text",
        key: "kwargs_text",
        width: 220,
        render: (value: string | null) => (value ? <Text ellipsis={{ tooltip: value }}>{value}</Text> : "-"),
      },
      {
        title: "执行结果",
        dataIndex: "result_text",
        key: "result_text",
        width: 220,
        render: (value: string | null) =>
          value ? (
            <Text ellipsis={{ tooltip: value }}>
              {value}
            </Text>
          ) : (
            "-"
          ),
      },
      {
        title: "异常信息",
        dataIndex: "exception_text",
        key: "exception_text",
        width: 220,
        render: (value: string | null) =>
          value ? (
            <Text type="danger" ellipsis={{ tooltip: value }}>
              {value}
            </Text>
          ) : (
            "-"
          ),
      },
    ],
    [],
  );

  const filteredWorkers = useMemo(() => {
    const rows = overviewQuery.data?.workers || [];
    return rows.filter((item) => {
      const online = (item.status || "").toUpperCase() === "ONLINE";
      if (statusFilter === "online" && !online) {
        return false;
      }
      if (statusFilter === "offline" && online) {
        return false;
      }
      if (!containsText(item.worker, workerKeyword.trim())) {
        return false;
      }
      if (queueKeyword.trim()) {
        const text = item.queue_names.join(", ");
        if (!containsText(text, queueKeyword.trim())) {
          return false;
        }
      }
      return true;
    });
  }, [overviewQuery.data?.workers, queueKeyword, statusFilter, workerKeyword]);

  const overviewErrorMessage = overviewQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(overviewQuery.error.message, "Worker监控数据加载失败，请稍后重试。")
    : "";
  const taskErrorMessage = workerTasksQuery.error instanceof Error
    ? formatTaskMonitorErrorMessage(workerTasksQuery.error.message, "Worker任务数据加载失败，请稍后重试。")
    : "";

  useToastFeedback({
    errorMessage: overviewErrorMessage || taskErrorMessage,
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
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - WORKERS_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? WORKERS_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - WORKERS_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(WORKERS_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [filteredWorkers.length, overviewErrorMessage, overviewQuery.isFetching, updateTableScrollY, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
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
  }, [updateTableScrollY]);

  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问Worker监控页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `celery.read` 或 `celery.manage`）。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  const overview = overviewQuery.data;
  const taskOverview = workerTasksQuery.data;

  const renderWorkerCard = (workerItem: WorkerMonitorWorkerItem) => (
    <AntCard
      key={workerItem.worker}
      className="admin-workers-worker-card"
      size="small"
      title={
        <Space className="min-w-0" size={8}>
          <Typography.Text strong ellipsis={{ tooltip: workerItem.worker }}>
            {workerItem.worker}
          </Typography.Text>
          {renderWorkerStatusTag(workerItem.status)}
        </Space>
      }
      extra={
        <Button
          type="text"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => setSelectedWorker(workerItem.worker)}
        />
      }
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">队列</Typography.Text>
          {renderQueueTags(workerItem.queue_names)}
        </div>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">并发/预取</Typography.Text>
          <Typography.Text>{workerItem.concurrency}/1</Typography.Text>
        </div>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">任务</Typography.Text>
          <Typography.Text>{workerItem.active_count}/{workerItem.reserved_count}/{workerItem.scheduled_count}</Typography.Text>
        </div>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">累计处理</Typography.Text>
          <Typography.Text>{workerItem.processed_count}</Typography.Text>
        </div>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">注册任务</Typography.Text>
          <Typography.Text>{workerItem.registered_count}</Typography.Text>
        </div>
        <div className="admin-workers-worker-card-field">
          <Typography.Text type="secondary">最近心跳</Typography.Text>
          <Typography.Text>{formatDateTime(workerItem.last_heartbeat_at)}</Typography.Text>
        </div>
      </Space>
    </AntCard>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        className="admin-workers-page-card"
        title="Worker监控"
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="执行节点" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  placeholder="按节点名称筛选"
                  value={workerKeyword}
                  onChange={(event) => setWorkerKeyword(event.target.value)}
                />
              </Form.Item>

              <Form.Item label="队列" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  placeholder="按队列名称筛选"
                  value={queueKeyword}
                  onChange={(event) => setQueueKeyword(event.target.value)}
                />
              </Form.Item>

              <Form.Item label="状态" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select
                  value={statusFilter}
                  onChange={(value) => setStatusFilter(parseStatusFilter(value))}
                  options={[
                    { label: "全部状态", value: "all" },
                    { label: "在线", value: "online" },
                    { label: "离线", value: "offline" },
                  ]}
                />
              </Form.Item>

              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />} onClick={() => void overviewQuery.refetch()} className="admin-search-btn">
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        ) : (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="执行节点" className="admin-filter-keyword-item">
                <Input
                  allowClear
                  placeholder="按节点名称筛选"
                  value={workerKeyword}
                  onChange={(event) => setWorkerKeyword(event.target.value)}
                  onPressEnter={() => void overviewQuery.refetch()}
                />
              </Form.Item>

              <Form.Item label="队列" className="admin-filter-keyword-item">
                <Input
                  allowClear
                  placeholder="按队列名称筛选"
                  value={queueKeyword}
                  onChange={(event) => setQueueKeyword(event.target.value)}
                  onPressEnter={() => void overviewQuery.refetch()}
                />
              </Form.Item>

              <Form.Item label="状态" className="admin-filter-keyword-item">
                <Select
                  value={statusFilter}
                  onChange={(value) => setStatusFilter(parseStatusFilter(value))}
                  options={[
                    { label: "全部状态", value: "all" },
                    { label: "在线", value: "online" },
                    { label: "离线", value: "offline" },
                  ]}
                />
              </Form.Item>

              <Form.Item>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />} onClick={() => void overviewQuery.refetch()} className="admin-search-btn">
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-workers-table-anchor"
            style={{ "--admin-workers-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<WorkerMonitorWorkerItem>
              rowKey={(record) => record.worker}
              columns={workerColumns}
              dataSource={filteredWorkers}
              loading={{
                spinning: overviewQuery.isFetching,
                indicator: <Spin />,
              }}
              tableLayout="fixed"
              pagination={{
                pageSize: 10,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: (total) => `共 ${total} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
              }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的执行节点。"
                  />
                ),
              }}
              scroll={{ y: tableScrollY }}
            />
          </div>
        ) : (
          <div className="admin-workers-card-view">
            {overviewQuery.isLoading && filteredWorkers.length === 0 ? (
              <div className="admin-workers-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : filteredWorkers.length === 0 ? (
              <div className="admin-workers-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的执行节点。"
                />
              </div>
            ) : (
              <div className="admin-workers-card-view-content">
                <Row gutter={[12, 12]}>
                  {filteredWorkers.map((workerItem) => (
                    <Col key={workerItem.worker} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderWorkerCard(workerItem)}
                    </Col>
                  ))}
                </Row>
              </div>
            )}
          </div>
        )}
      </AntCard>

      <Drawer
        title={`执行节点任务明细 - ${selectedWorker || "-"}`}
        open={Boolean(selectedWorker)}
        width={1260}
        onClose={() => setSelectedWorker(null)}
        extra={
          <Space>
            <Button size="small" onClick={() => void workerTasksQuery.refetch()} loading={workerTasksQuery.isFetching}>
              刷新任务
            </Button>
            <Text type="secondary">{taskOverview ? `采集时间：${formatDateTime(taskOverview.generated_at)}` : "-"}</Text>
          </Space>
        }
      >
        {workerTasksQuery.isLoading && !taskOverview ? <Spin tip="任务数据加载中..." /> : null}
        {!workerTasksQuery.isLoading && !taskOverview ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={taskErrorMessage || "暂无任务数据"}
          />
        ) : null}
        {taskOverview ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Space size={8} wrap>
              <Tag color="processing">运行中: {taskOverview.summary.active}</Tag>
              <Tag color="gold">预留中: {taskOverview.summary.reserved}</Tag>
              <Tag color="purple">已调度: {taskOverview.summary.scheduled}</Tag>
              <Tag color="default">最近记录: {taskOverview.summary.recent}</Tag>
            </Space>

            <AntCard title="运行中任务">
              <Table<WorkerMonitorTaskItem>
                rowKey={(record) => `active-${record.task_id}`}
                columns={taskColumns}
                dataSource={taskOverview.active_tasks}
                pagination={false}
                locale={{ emptyText: "暂无运行中任务" }}
                scroll={{ x: 2200 }}
              />
            </AntCard>

            <AntCard title="保留任务">
              <Table<WorkerMonitorTaskItem>
                rowKey={(record) => `reserved-${record.task_id}`}
                columns={taskColumns}
                dataSource={taskOverview.reserved_tasks}
                pagination={false}
                locale={{ emptyText: "暂无保留任务" }}
                scroll={{ x: 2200 }}
              />
            </AntCard>

            <AntCard title="定时任务">
              <Table<WorkerMonitorTaskItem>
                rowKey={(record) => `scheduled-${record.task_id}`}
                columns={taskColumns}
                dataSource={taskOverview.scheduled_tasks}
                pagination={false}
                locale={{ emptyText: "暂无定时任务" }}
                scroll={{ x: 2200 }}
              />
            </AntCard>

            <AntCard title="最近完成任务">
              <Table<WorkerMonitorTaskItem>
                rowKey={(record) => `recent-${record.task_id}`}
                columns={taskColumns}
                dataSource={taskOverview.recent_tasks}
                pagination={false}
                locale={{ emptyText: "暂无最近任务" }}
                scroll={{ x: 2200 }}
              />
            </AntCard>
          </Space>
        ) : null}
      </Drawer>
    </div>
  );
}
