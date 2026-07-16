"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
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
import { SearchOutlined } from "@ant-design/icons";
import type { ComponentType, RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type { ScheduledTaskListResponse, ScheduledTaskRunResponse, ScheduledTaskSummary } from "@/types/auth";

type StatusFilter = "all" | "enabled" | "disabled" | ScheduledTaskSummary["status"];

type FormState = {
  task_key: string;
  name: string;
  description: string;
  cron_expression: string;
  timezone: string;
  retain_days: number;
  enabled: boolean;
};


const STATUS_FILTER_OPTIONS = [
  { label: "全部", value: "all" },
  { label: "已启用", value: "enabled" },
  { label: "已禁用", value: "disabled" },
  { label: "空闲", value: "idle" },
  { label: "已排队", value: "queued" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "success" },
  { label: "失败", value: "failed" },
] as const satisfies ReadonlyArray<{ label: string; value: StatusFilter }>;

const TIMEZONE_OPTIONS = [
  { label: "Asia/Shanghai", value: "Asia/Shanghai" },
  { label: "UTC", value: "UTC" },
] as const;

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_VIEWPORT_GAP = 40;
const TABLE_FALLBACK_RESERVE = 220;

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleString();
}

function renderStatus(value: ScheduledTaskSummary["status"]) {
  if (value === "success") {
    return <Tag color="green">成功</Tag>;
  }
  if (value === "failed") {
    return <Tag color="red">失败</Tag>;
  }
  if (value === "running") {
    return <Tag color="processing">运行中</Tag>;
  }
  if (value === "queued") {
    return <Tag color="blue">已排队</Tag>;
  }
  if (value === "disabled") {
    return <Tag>已禁用</Tag>;
  }
  return <Tag color="default">空闲</Tag>;
}

function renderTaskType(value: ScheduledTaskSummary["task_type"]) {
  if (value === "syslog_cleanup") {
    return "系统日志清理";
  }
  return value;
}

export default function AdminScheduledTasksPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [formApi] = Form.useForm<FormState>();

  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const [runningId, setRunningId] = useState<number | null>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const canRead = hasPermission("celery.read") || hasPermission("celery.manage");
  const canManage = hasPermission("celery.manage");

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    if (statusFilter !== "all") {
      params.set("status", statusFilter);
    }
    const qs = params.toString();
    return `/api/v1/admin/scheduled-tasks${qs ? `?${qs}` : ""}`;
  }, [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ScheduledTaskListResponse;
    },
  });

  const refreshList = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/admin/scheduled-tasks"),
    });
  }, [queryClient]);

  useTopicSubscription("admin.scheduled-tasks", useCallback(() => {
    void refreshList();
  }, [refreshList]));

  const resetForm = useCallback(() => {
    setEditingId(null);
    formApi.setFieldsValue({
      task_key: "",
      name: "",
      description: "",
      cron_expression: "0 3 * * *",
      timezone: "Asia/Shanghai",
      retain_days: 30,
      enabled: true,
    });
  }, [formApi]);

  const closeEditor = useCallback(() => {
    setEditorOpen(false);
    resetForm();
  }, [resetForm]);

  const startEdit = useCallback((item: ScheduledTaskSummary) => {
    setError("");
    setSuccess("");
    setEditingId(item.id);
    formApi.setFieldsValue({
      task_key: item.task_key,
      name: item.name,
      description: item.description ?? "",
      cron_expression: item.cron_expression,
      timezone: item.timezone,
      retain_days: item.retain_days,
      enabled: item.enabled,
    });
    setEditorOpen(true);
  }, [formApi]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) {
        throw new Error("缺少 celery.manage 权限");
      }

      const values = await formApi.validateFields();

      // 只允许更新 cron_expression 和 enabled 字段
      const response = await fetchWithAuth(`/api/v1/admin/scheduled-tasks/${editingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cron_expression: values.cron_expression.trim(),
          enabled: values.enabled,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "updated" as const;
    },
    onSuccess: async () => {
      setError("");
      setSuccess("定时任务已更新");
      closeEditor();
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "保存失败");
    },
  });

  const runMutation = useMutation({
    mutationFn: async (item: ScheduledTaskSummary) => {
      const response = await fetchWithAuth(`/api/v1/admin/scheduled-tasks/${item.id}/run`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ScheduledTaskRunResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(payload.celery_task_id ? `任务已触发，Celery ID: ${payload.celery_task_id}` : "任务已触发");
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "执行失败");
    },
  });

  const runTask = useCallback(async (item: ScheduledTaskSummary) => {
    setRunningId(item.id);
    try {
      await runMutation.mutateAsync(item);
    } finally {
      setRunningId(null);
    }
  }, [runMutation]);

  useToastFeedback({
    errorMessage: error || (listQuery.error instanceof Error ? listQuery.error.message : ""),
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const items = listQuery.data?.items ?? [];

  const columns = useMemo<TableColumnsType<ScheduledTaskSummary>>(() => {
    const baseColumns: TableColumnsType<ScheduledTaskSummary> = [
      {
        title: "任务",
        key: "name",
        width: 260,
        render: (_, record) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{record.name}</Typography.Text>
            <Typography.Text type="secondary" className="font-mono text-xs">
              {record.task_key}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: "类型",
        dataIndex: "task_type",
        key: "task_type",
        width: 140,
        render: (value: ScheduledTaskSummary["task_type"]) => renderTaskType(value),
      },
      {
        title: "Cron / 时区",
        key: "cron",
        width: 220,
        render: (_, record) => (
          <Space direction="vertical" size={0}>
            <Typography.Text className="font-mono text-xs">{record.cron_expression}</Typography.Text>
            <Typography.Text type="secondary">{record.timezone}</Typography.Text>
          </Space>
        ),
      },
      {
        title: "状态",
        key: "status",
        width: 160,
        render: (_, record) => (
          <Space direction="vertical" size={4}>
            {renderStatus(record.status)}
            <Tag color={record.enabled ? "green" : "default"}>{record.enabled ? "已启用" : "已禁用"}</Tag>
          </Space>
        ),
      },
      {
        title: "最近执行 / 下次执行",
        key: "runtime",
        width: 260,
        render: (_, record) => (
          <Space direction="vertical" size={0}>
            <Typography.Text>{formatDateTime(record.last_run_at)}</Typography.Text>
            <Typography.Text type="secondary">{formatDateTime(record.next_run_at)}</Typography.Text>
          </Space>
        ),
      },
      {
        title: "结果",
        key: "result",
        width: 320,
        render: (_, record) => (
          <Space direction="vertical" size={0}>
            <Typography.Text type="secondary">
              最近成功：{formatDateTime(record.last_success_at)}
            </Typography.Text>
            <Typography.Text type={record.last_error_message ? "danger" : "secondary"}>
              {record.last_error_message || `已累计执行 ${record.run_count} 次`}
            </Typography.Text>
          </Space>
        ),
      },
    ];

    if (canManage) {
      baseColumns.push({
        title: "操作",
        key: "actions",
        fixed: "right",
        width: 180,
        render: (_, record) => (
          <Space size="small">
            <Button size="small" onClick={() => startEdit(record)}>
              编辑
            </Button>
            <Button
              size="small"
              type="primary"
              loading={runningId === record.id}
              onClick={() => void runTask(record)}
            >
              立即执行
            </Button>
          </Space>
        ),
      });
    }

    return baseColumns;
  }, [canManage, runTask, runningId, startEdit]);

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    updateTableScrollY();
  }, [items.length, listQuery.isFetching, error, success, updateTableScrollY]);

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
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin tip="初始化中..." />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问定时任务管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `celery.read`）。</p>
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
    <div className="flex flex-1 flex-col space-y-6">
      <AntCard
        title="定时任务管理"
        style={{ height: '100%' }}
        extra={(
          <Space>
            {listQuery.isFetching && <Spin size="small" />}
          </Space>
        )}
      >
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="关键词" className="admin-filter-keyword-item">
              <Input
                value={keyword}
                allowClear
                onChange={(event) => setKeyword(event.currentTarget.value)}
                placeholder="按任务键/名称/Cron 筛选"
                onPressEnter={() => void refreshList()}
              />
            </Form.Item>

            <Form.Item label="状态" className="admin-filter-keyword-item">
              <Select<StatusFilter>
                value={statusFilter}
                options={[...STATUS_FILTER_OPTIONS]}
                onChange={(value) => setStatusFilter(value)}
              />
            </Form.Item>

            <Form.Item>
              <Button
                icon={<SearchOutlined />}
                onClick={() => void refreshList()}
                className="admin-search-btn"
              >
                查询
              </Button>
            </Form.Item>
          </Form>
        </div>

        <div
          ref={tableScrollAnchorRef}
          className="admin-scheduled-tasks-table-anchor"
          style={{ "--admin-scheduled-tasks-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
        >
          <Table<ScheduledTaskSummary>
            rowKey="id"
            loading={listQuery.isFetching}
            dataSource={items}
            columns={columns}
            scroll={{ x: 1480, y: tableScrollY }}
            pagination={{
              pageSize: 20,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (total) => `共 ${total} 条`,
              hideOnSinglePage: false,
              style: { marginBottom: 0 },
            }}
            locale={{
              emptyText: <Empty description="暂无定时任务。" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
            }}
          />
        </div>
      </AntCard>

      {canManage ? (
        <Modal
          title="编辑定时任务"
          open={editorOpen}
          onCancel={closeEditor}
          width={760}
          destroyOnClose
          footer={(
            <Space>
              <Button type="primary" loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
                {saveMutation.isPending ? "提交中..." : "保存"}
              </Button>
            </Space>
          )}
        >
          <Form<FormState> form={formApi} layout="vertical">
            <div className="grid gap-4 md:grid-cols-2">
              <Form.Item
                name="task_key"
                label="任务键"
                extra="由系统代码定义，不可修改"
              >
                <Input disabled placeholder="syslog.cleanup.default" />
              </Form.Item>
              <Form.Item name="name" label="任务名称">
                <Input disabled placeholder="系统日志定时清理" />
              </Form.Item>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Form.Item
                name="cron_expression"
                label="Cron 表达式"
                rules={[{ required: true, message: "请输入 Cron 表达式" }]}
                extra="格式：分钟 小时 日 月 周，例如 `0 3 * * *`。"
              >
                <Input placeholder="0 3 * * *" />
              </Form.Item>
              <Form.Item name="timezone" label="时区" rules={[{ required: true, message: "请选择时区" }]}>
                <Select options={[...TIMEZONE_OPTIONS]} disabled />
              </Form.Item>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Form.Item
                name="retain_days"
                label="日志保留天数"
                rules={[{ required: true, message: "请输入日志保留天数" }]}
              >
                <InputNumber min={1} max={3650} className="w-full" disabled />
              </Form.Item>
              <Form.Item name="enabled" label="启用状态" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
            </div>

            <Form.Item name="description" label="说明">
              <Input.TextArea rows={4} placeholder="说明任务用途、影响范围和运行窗口。" disabled />
            </Form.Item>
          </Form>
        </Modal>
      ) : null}
    </div>
  );
}
