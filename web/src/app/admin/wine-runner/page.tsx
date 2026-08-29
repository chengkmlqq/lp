"use client";

import { PlayCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card as AntdCard,
  Form,
  Input,
  InputNumber,
  Popover,
  Space,
  Tag,
  Typography,
  type CardProps,
} from "antd";
import type { ComponentType, RefAttributes } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";

type WineStatusResponse = {
  wine_binary: string;
  resolved_binary: string | null;
  available: boolean;
  version: string | null;
  allowed_root: string;
  default_timeout_seconds: number;
  max_timeout_seconds: number;
  error: string | null;
};

type WineRunFormValues = {
  exe_path: string;
  arguments_text?: string;
  working_dir?: string;
  timeout_seconds?: number | null;
};

type WineRunDetail = {
  id: string;
  task_id: string | null;
  status: "pending" | "running" | "success" | "failed";
  exe_path: string;
  arguments: string[];
  working_dir: string;
  timeout_seconds: number;
  command_text: string | null;
  resolved_binary: string | null;
  exit_code: number | null;
  timed_out: boolean;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  stdout_text: string | null;
  stderr_text: string | null;
};

const DEFAULT_FORM_VALUES: WineRunFormValues = {
  exe_path: "ATP/tpbig.exe",
  arguments_text: "templates/fanji/work.atp",
  working_dir: "",
  timeout_seconds: 300,
};

const AntCard = AntdCard as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

function parseArguments(value: string | undefined): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatLogText(run: WineRunDetail | null | undefined): string {
  if (!run) {
    return "等待执行...";
  }

  const parts = [
    `状态: ${run.status}`,
    `Task ID: ${run.task_id ?? "-"}`,
    `命令: ${run.command_text ?? "-"}`,
    `工作目录: ${run.working_dir}`,
    `超时: ${run.timeout_seconds}s`,
    `退出码: ${run.exit_code ?? "-"}`,
    `是否超时: ${run.timed_out ? "true" : "false"}`,
    "",
    "[STDOUT]",
    run.stdout_text ?? "",
    "",
    "[STDERR]",
    run.stderr_text ?? "",
  ];
  return parts.join("\n");
}

function formatStatusTag(status: WineRunDetail["status"] | null | undefined) {
  if (status === "success") return <Tag color="success">成功</Tag>;
  if (status === "running") return <Tag color="processing">运行中</Tag>;
  if (status === "failed") return <Tag color="error">失败</Tag>;
  if (status === "pending") return <Tag color="blue">排队中</Tag>;
  return <Tag>-</Tag>;
}

function WineStatusPopoverContent({ status }: { status: WineStatusResponse | null }) {
  if (!status) {
    return <Typography.Text type="secondary">尚未检测</Typography.Text>;
  }
  return (
    <Space direction="vertical" size={4} style={{ minWidth: 220 }}>
      <Typography.Text strong>Wine 详情</Typography.Text>
      <Typography.Text copyable>{status.resolved_binary ?? status.wine_binary ?? "wine"}</Typography.Text>
      <Typography.Text type="secondary">{status.version ?? status.error ?? "尚未检测"}</Typography.Text>
      <Typography.Text type="secondary">允许目录：{status.allowed_root ?? "-"}</Typography.Text>
      <Typography.Text type="secondary">
        超时范围：{status.default_timeout_seconds ?? "-"} / {status.max_timeout_seconds ?? "-"} 秒
      </Typography.Text>
    </Space>
  );
}

export default function AdminWineRunnerPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [form] = Form.useForm<WineRunFormValues>();
  const [status, setStatus] = useState<WineStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const canRead = hasPermission("wine.read") || hasPermission("wine.manage");
  const canManage = hasPermission("wine.manage");

  useToastFeedback({
    errorMessage: error,
    successMessage: success,
    errorTitle: "执行失败",
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const loadStatus = useCallback(async () => {
    if (!user || !canRead) {
      return;
    }
    setStatusLoading(true);
    setError("");
    try {
      const response = await fetchWithAuth("/api/v1/wine/status");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const payload = (await response.json()) as WineStatusResponse;
      setStatus(payload);
      form.setFieldsValue({
        timeout_seconds: payload.default_timeout_seconds,
      });
    } catch (candidate) {
      setError(candidate instanceof Error ? candidate.message : "Wine 状态检测失败");
    } finally {
      setStatusLoading(false);
    }
  }, [canRead, fetchWithAuth, form, user]);

  useEffect(() => {
    queueMicrotask(() => {
      void loadStatus();
    });
  }, [loadStatus]);

  const runMutation = useMutation({
    mutationFn: async (values: WineRunFormValues) => {
      const response = await fetchWithAuth("/api/v1/wine/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          exe_path: values.exe_path.trim(),
          arguments: parseArguments(values.arguments_text),
          working_dir: values.working_dir?.trim() || null,
          timeout_seconds: values.timeout_seconds ?? null,
          environment: {},
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as WineRunDetail;
    },
    onSuccess: (payload) => {
      setActiveRunId(payload.id);
      setError("");
      setSuccess(
        payload.status === "success"
          ? "执行完成"
          : payload.status === "failed"
            ? "执行失败"
            : "执行任务已提交，等待 Worker 处理",
      );
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "执行失败");
    },
  });

  const runDetailQuery = useQuery({
    queryKey: ["wine-run-detail", activeRunId],
    enabled: Boolean(activeRunId) && canRead,
    queryFn: async () => {
      if (!activeRunId) {
        throw new Error("运行记录不存在");
      }
      const response = await fetchWithAuth(`/api/v1/wine/runs/${activeRunId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as WineRunDetail;
    },
    refetchInterval: (query) => {
      const detail = query.state.data as WineRunDetail | undefined;
      return detail && (detail.status === "pending" || detail.status === "running") ? 2000 : false;
    },
  });

  const handleRun = async (values: WineRunFormValues) => {
    if (!canManage) {
      setError("缺少 wine.manage 权限");
      return;
    }
    setError("");
    setSuccess("");
    await runMutation.mutateAsync(values);
  };

  const logText = useMemo(() => formatLogText(runDetailQuery.data), [runDetailQuery.data]);

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <AntCard title="Wine 测试">
        <Typography.Text type="secondary">
          {!user ? "请先登录后访问 Wine 执行器。" : "当前账号无 Wine 模块权限（需要 wine.read）。"}
        </Typography.Text>
      </AntCard>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-wine-runner-page-card"
        title="Wine 测试"
        extra={
          <Space>
            <Popover
              content={<WineStatusPopoverContent status={status} />}
              trigger="click"
            >
              <Tag
                color={status?.available ? "success" : "error"}
                style={{ cursor: "pointer" }}
              >
                {status?.available ? "可用" : "不可用"}
              </Tag>
            </Popover>
            <Button icon={<ReloadOutlined />} loading={statusLoading} onClick={() => void loadStatus()}>
              检测
            </Button>
          </Space>
        }
      >
        <div className="admin-wine-runner-layout">
          <div className="admin-wine-runner-config">
            <Typography.Title level={5} style={{ marginTop: 0 }}>测试执行</Typography.Title>
            <Form<WineRunFormValues>
              form={form}
              layout="vertical"
              initialValues={DEFAULT_FORM_VALUES}
              onFinish={(values) => {
                void handleRun(values);
              }}
            >
              <Form.Item name="exe_path" label="EXE 路径" rules={[{ required: true, message: "请输入 EXE 路径" }]}>
                <Input placeholder="ATP/tpbig.exe （相对 wine_allowed_root 的路径）" />
              </Form.Item>
              <Form.Item name="timeout_seconds" label="超时秒数">
                <InputNumber min={1} max={status?.max_timeout_seconds ?? 1800} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="working_dir" label="工作目录">
                <Input placeholder="留空时使用 EXE 所在目录" />
              </Form.Item>
              <Form.Item name="arguments_text" label="执行参数">
                <Input.TextArea rows={4} placeholder="每行一个参数" />
              </Form.Item>
              <Space wrap>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<PlayCircleOutlined />}
                  disabled={!canManage || runMutation.isPending}
                  loading={runMutation.isPending}
                >
                  执行测试
                </Button>
                {activeRunId && (
                  <Typography.Text type="secondary">当前运行 ID: {activeRunId}</Typography.Text>
                )}
              </Space>
            </Form>
          </div>

          <div className="admin-wine-runner-status">
            <Typography.Title level={5} style={{ marginTop: 0 }}>运行状态</Typography.Title>
            {runDetailQuery.isLoading ? (
              <Typography.Text type="secondary">正在加载运行详情...</Typography.Text>
            ) : runDetailQuery.error instanceof Error ? (
              <Alert type="error" showIcon message="运行详情加载失败" description={runDetailQuery.error.message} />
            ) : (
              <div className="admin-wine-runner-status-body">
                <div className="admin-wine-runner-status-line">
                  <Typography.Text strong>状态</Typography.Text>
                  {formatStatusTag(runDetailQuery.data?.status)}
                  <Typography.Text type="secondary">Task ID: {runDetailQuery.data?.task_id ?? "-"}</Typography.Text>
                </div>
                <div className="admin-wine-runner-status-line">
                  <Typography.Text type="secondary">开始: {runDetailQuery.data?.started_at ?? "-"}</Typography.Text>
                  <Typography.Text type="secondary">结束: {runDetailQuery.data?.finished_at ?? "-"}</Typography.Text>
                </div>
                {runDetailQuery.data?.error_message ? (
                  <Alert type="error" showIcon message={runDetailQuery.data.error_message} />
                ) : null}
                <Typography.Text strong className="admin-wine-runner-log-label">执行日志</Typography.Text>
                <pre className="admin-wine-runner-log">
                  {logText}
                </pre>
              </div>
            )}
          </div>
        </div>
      </AntCard>
    </div>
  );
}
