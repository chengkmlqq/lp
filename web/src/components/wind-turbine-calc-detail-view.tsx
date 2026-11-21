"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Table,
  Tabs,
  Typography,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  ArrowLeftOutlined,
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ReloadOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import {
  WindDetailHero,
  WindDetailMeta,
  WindDetailMetricStrip,
  WindDetailMoreActions,
  WindDetailPaginationFooter,
  WindDetailSubline,
  WindStatusChip,
  type WindDetailMetaItem,
  type WindDetailMetricItem,
  type WindDetailPaginationConfig,
} from "@/components/wind-detail-layout";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcJobDetail,
  WindTurbineCalcResultListResponse,
  WindTurbineCalcResultRow,
} from "@/types/wind-turbine-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toExponential(9);
}

/**
 * 单风机计算详情视图。
 * 独立路由页与列表页的动态详情标签共用此组件，避免复制详情页逻辑。
 */
export function WindTurbineCalcDetailView({
  jobId,
  onClose,
}: {
  jobId: string;
  onClose?: () => void;
}) {
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const { t } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canManage = hasPermission("wind_turbine_calc.manage");

  const [activeTab, setActiveTab] = useState("overview");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const detailQuery = useQuery({
    queryKey: ["wind-turbine-calc", "detail", jobId],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: () => getJson<WindTurbineCalcJobDetail>(`${API_BASE}/${jobId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "processing" || status === "pending" ? 4000 : false;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ["wind-turbine-calc", "results", jobId, page, pageSize],
    enabled: Boolean(user) && Boolean(jobId) && detailQuery.data?.status === "completed",
    queryFn: async () => {
      const q = new URLSearchParams();
      q.set("limit", String(pageSize));
      q.set("offset", String((page - 1) * pageSize));
      return getJson<WindTurbineCalcResultListResponse>(`${API_BASE}/${jobId}/results?${q.toString()}`);
    },
  });

  const detail = detailQuery.data;
  const statusMeta = STATUS_META[detail?.status ?? "pending"] ?? STATUS_META.pending;

  // 曲线图带鉴权拉取，转成 blob URL 展示；gcTime: 0 保证关闭标签后重开必定重新请求，
  // 避免命中已 revoke 的死 URL。
  const chartQuery = useQuery({
    queryKey: ["wind-turbine-calc", "chart", jobId],
    enabled: Boolean(user) && Boolean(jobId) && detail?.status === "completed",
    gcTime: 0,
    staleTime: 0,
    queryFn: async () => {
      const response = await fetchWithAuth(`${API_BASE}/${jobId}/chart`);
      if (!response.ok) return null;
      const blob = await response.blob();
      if (blob.size === 0) return null;
      return URL.createObjectURL(blob);
    },
  });

  useEffect(() => {
    const objectUrl = chartQuery.data;
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [chartQuery.data]);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-turbine-calc"] });
  }, [queryClient]);

  const handleExport = useCallback(
    async (type: "csv" | "all") => {
      try {
        await downloadFileWithAuth(`${API_BASE}/${jobId}/export?type=${type}`, `wind-turbine-${jobId}.${type === "csv" ? "csv" : "zip"}`);
      } catch (error) {
        message.error((error as Error).message);
      }
    },
    [jobId, message],
  );

  const handleCancel = useCallback(() => {
    modal.confirm({
      title: t("取消该计算任务？"),
      content: t("取消会真正终止 MATLAB Runtime 进程组。"),
      okText: t("取消任务"),
      okButtonProps: { danger: true },
      cancelText: t("返回"),
      onOk: async () => {
        const response = await fetchWithAuth(`${API_BASE}/${jobId}/cancel`, { method: "POST" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已发送取消请求"));
        refresh();
      },
    });
  }, [fetchWithAuth, jobId, message, modal, refresh, t]);

  const handleDelete = useCallback(() => {
    modal.confirm({
      title: t("删除该计算任务？"),
      okText: t("删除"),
      okButtonProps: { danger: true },
      cancelText: t("返回"),
      onOk: async () => {
        const response = await fetchWithAuth(`${API_BASE}/${jobId}`, { method: "DELETE" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已删除"));
        refresh();
        onClose?.();
      },
    });
  }, [fetchWithAuth, jobId, message, modal, refresh, onClose, t]);

  const columns = useMemo<TableColumnsType<WindTurbineCalcResultRow>>(
    () => [
      { title: t("旋转角 θ (deg)"), dataIndex: "theta_deg", key: "theta_deg", width: 160, render: (v: number) => v.toFixed(2) },
      { title: t("屏蔽失效率"), dataIndex: "failure_rate", key: "failure_rate", render: (v: number) => v.toExponential(12) },
      {
        title: t("失效率 (%)"),
        dataIndex: "failure_rate_pct",
        key: "failure_rate_pct",
        render: (v: number) => `${v.toFixed(9)}%`,
      },
    ],
    [t],
  );

  const completedAngles = detail ? Math.round((detail.progress / 100) * detail.angle_count) : 0;
  const running = detail?.status === "processing" || detail?.status === "pending";
  const engineVersion = detail?.engine_version_tag || detail?.engine_version_hash?.slice(0, 12);

  // 状态/阶段/进度/耗时/时间已在 Hero（chip + 副行），属性网格不再重复。
  const metaItems: WindDetailMetaItem[] = [
    { label: t("轮毂高度 h"), value: detail?.hub_height != null ? `${detail.hub_height} m` : "-" },
    { label: t("叶片长度 R"), value: detail?.blade_length != null ? `${detail.blade_length} m` : "-" },
    { label: t("起始雷电流 Ic"), value: detail?.start_current != null ? `${detail.start_current} kA` : "-" },
    { label: t("接闪器径向位置"), value: detail?.receptor_radii?.join(", ") || "-" },
    { label: t("旋转角列表"), value: detail?.angle_list?.join(", ") || "-" },
    {
      label: t("引擎版本"),
      value: engineVersion
        ? `${engineVersion}${detail?.runtime_version ? ` (${detail.runtime_version})` : ""}`
        : "-",
    },
    ...(detail?.error_message
      ? [{ label: t("错误信息"), span: 2 as const, value: <Text type="danger">{detail.error_message}</Text> }]
      : []),
  ];

  // 关键指标条：Tab 内原 3 张统计卡上移，对应角度作为后缀保留，不再一处信息三处展示。
  const metricItems: WindDetailMetricItem[] = [
    { label: t("平均失效率"), value: formatRate(detail?.mean_failure_rate) },
    {
      label: t("最小失效率"),
      value: formatRate(detail?.min_failure_rate),
      suffix: `${t("对应角度")} ${detail?.min_failure_rate_theta ?? "-"}`,
    },
    {
      label: t("最大失效率"),
      value: formatRate(detail?.max_failure_rate),
      suffix: `${t("对应角度")} ${detail?.max_failure_rate_theta ?? "-"}`,
    },
  ];

  // 分页底栏由当前激活 Tab 驱动，仅逐角度结果 Tab 需要分页。
  const activePagination: WindDetailPaginationConfig | null =
    detail?.status === "completed" && activeTab === "angles"
      ? {
          current: page,
          pageSize,
          total: resultsQuery.data?.total ?? 0,
          pageSizeOptions: [20, 50, 100],
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            if (nextSize && nextSize !== pageSize) {
              setPageSize(nextSize);
              setPage(1);
            }
          },
        }
      : null;

  const tabItems: NonNullable<TabsProps["items"]> = [
    {
      key: "overview",
      label: t("概览"),
      children: (
        <div className="wind-detail-tab-content">
          {chartQuery.data ? (
            <Card size="small" title={t("失效率曲线")}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={chartQuery.data} alt="failure rate chart" style={{ maxWidth: "100%", width: 900 }} />
            </Card>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无曲线")} />
          )}
        </div>
      ),
    },
    ...(detail?.status === "completed"
      ? [
          {
            key: "angles",
            label: `${t("逐角度结果")} (${detail.angle_count})`,
            children: (
              <Card size="small" title={t("逐角度结果")}>
                <Table<WindTurbineCalcResultRow>
                  rowKey="theta_deg"
                  columns={columns}
                  dataSource={resultsQuery.data?.items ?? []}
                  loading={resultsQuery.isLoading}
                  pagination={false}
                  locale={{ emptyText: <Empty description={t("暂无结果")} /> }}
                />
              </Card>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="wind-detail-pane">
      <WindDetailHero
        icon={<ThunderboltOutlined />}
        title={detail?.name || t("单风机计算详情")}
        titleTooltip={detail?.name}
        statusChip={<WindStatusChip status={detail?.status ?? "pending"} label={t(statusMeta.label)} />}
        subline={
          <WindDetailSubline
            items={[
              <span key="task">{t("任务 ID")} {jobId}</span>,
              <span key="stage">{t("阶段")} {detail?.stage || "-"}</span>,
              <span key="start">{t("开始时间")} {formatDateTime(detail?.started_at)}</span>,
              <span key="duration">{t("耗时")} {formatDuration(detail?.duration_seconds)}</span>,
              detail?.engine_version_tag ? <span key="engine">{detail.engine_version_tag}</span> : null,
              detail ? (
                <span key="progress">
                  {t("进度（已完成角度）")} {completedAngles}/{detail.angle_count}
                </span>
              ) : null,
            ]}
          />
        }
        actions={
          <>
            {detail?.status === "completed" ? (
              <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => handleExport("all")}>
                {t("导出结果包")}
              </Button>
            ) : (
              <Button size="small" type="primary" icon={<ReloadOutlined />} onClick={refresh}>
                {t("刷新")}
              </Button>
            )}
            <WindDetailMoreActions
              label={t("更多")}
              items={[
                {
                  key: "csv",
                  label: t("导出 CSV"),
                  icon: <DownloadOutlined />,
                  disabled: detail?.status !== "completed",
                  onClick: () => void handleExport("csv"),
                },
                ...(detail?.status === "completed"
                  ? [{ key: "refresh", label: t("刷新"), icon: <ReloadOutlined />, onClick: refresh }]
                  : []),
                ...(canManage && running
                  ? [{ key: "cancel", label: t("取消任务"), icon: <StopOutlined />, danger: true, onClick: handleCancel }]
                  : []),
                ...(canManage && detail && !running
                  ? [{ key: "delete", label: t("删除"), icon: <DeleteOutlined />, danger: true, onClick: handleDelete }]
                  : []),
                onClose
                  ? { key: "close", label: t("关闭"), icon: <CloseOutlined />, onClick: onClose }
                  : {
                      key: "back",
                      label: t("返回列表"),
                      icon: <ArrowLeftOutlined />,
                      onClick: () => router.push("/admin/wind-turbine-calc"),
                    },
              ]}
            />
          </>
        }
      />

      <Alert
        className="wind-detail-alert wind-detail-hint-alert"
        type="warning"
        showIcon
        message={t("角度公式外推提示")}
        description={t("角度击距公式只在 0–90° 范围内拟合，超过 90° 的旋转角按外推计算，结果仅供参考。")}
      />

      {detail ? <WindDetailMetricStrip items={metricItems} /> : null}

      {detail ? <WindDetailMeta items={metaItems} /> : null}

      <Tabs
        className="admin-atp-models-detail-tabs wind-detail-tabs"
        items={tabItems}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key)}
      />

      <WindDetailPaginationFooter pagination={activePagination} />
    </div>
  );
}

export default WindTurbineCalcDetailView;
