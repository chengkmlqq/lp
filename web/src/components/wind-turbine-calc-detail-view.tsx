"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Table,
  Tabs,
  Tooltip,
  Typography,
  type DescriptionsProps,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  DownloadOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import {
  WindDetailHero,
  WindDetailPaginationFooter,
  WindDetailSubline,
  type WindDetailPaginationConfig,
} from "@/components/wind-detail-layout";
import { downloadFileWithAuth, getJson } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcJobDetail,
  WindTurbineCalcResultListResponse,
  WindTurbineCalcResultRow,
} from "@/types/wind-turbine-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";

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

/** 表头显式渲染灰色问号图标，悬浮显示解释文案；不依赖 antd Table 的 column.tooltip。 */
function columnTitle(label: string, tip: string) {
  return (
    <span className="inline-flex items-center gap-1">
      {label}
      <Tooltip title={tip}>
        <QuestionCircleOutlined className="text-gray-400" />
      </Tooltip>
    </span>
  );
}

/**
 * 单风机计算详情视图。
 * 独立路由页与列表页的动态详情标签共用此组件，避免复制详情页逻辑。
 */
export function WindTurbineCalcDetailView({ jobId }: { jobId: string }) {
  const { message } = App.useApp();
  const { user, fetchWithAuth } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();

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

  const handleExport = useCallback(async () => {
    try {
      await downloadFileWithAuth(`${API_BASE}/${jobId}/export?type=all`, `wind-turbine-${jobId}.zip`);
    } catch (error) {
      message.error((error as Error).message);
    }
  }, [jobId, message]);

  const columns = useMemo<TableColumnsType<WindTurbineCalcResultRow>>(
    () => [
      {
        title: columnTitle(t("旋转角 θ (deg)"), t("风轮旋转角度，单位为度（°）")),
        dataIndex: "theta_deg",
        key: "theta_deg",
        width: 160,
        render: (v: number) => v.toFixed(2),
      },
      {
        title: columnTitle(t("屏蔽失效率"), t("该旋转角度下计算得到的屏蔽失效率")),
        dataIndex: "failure_rate",
        key: "failure_rate",
        render: (v: number) => v.toExponential(12),
      },
      {
        title: columnTitle(t("失效率 (%)"), t("屏蔽失效率换算成百分比（%）")),
        dataIndex: "failure_rate_pct",
        key: "failure_rate_pct",
        render: (v: number) => `${v.toFixed(9)}%`,
      },
    ],
    [t],
  );

  const completedAngles = detail ? Math.round((detail.progress / 100) * detail.angle_count) : 0;
  const engineVersion = detail?.engine_version_tag || detail?.engine_version_hash?.slice(0, 12);

  // 基本信息统一汇入带边框的 key-value 表格（参考地闪密度详情页概览范式），
  // 原基本字段与三个失效率指标并列展示，失效率数值沿用 formatRate。
  const overviewItems: DescriptionsProps["items"] = detail
    ? [
        {
          key: "hub_height",
          label: t("轮毂高度 h"),
          children: detail.hub_height != null ? `${detail.hub_height} m` : "-",
        },
        {
          key: "blade_length",
          label: t("叶片长度 R"),
          children: detail.blade_length != null ? `${detail.blade_length} m` : "-",
        },
        {
          key: "start_current",
          label: t("起始雷电流 Ic"),
          children: detail.start_current != null ? `${detail.start_current} kA` : "-",
        },
        { key: "receptor_radii", label: t("接闪器径向位置"), children: detail.receptor_radii?.join(", ") || "-" },
        { key: "angle_list", label: t("旋转角列表"), children: detail.angle_list?.join(", ") || "-" },
        {
          key: "engine_version",
          label: t("引擎版本"),
          children: engineVersion
            ? `${engineVersion}${detail.runtime_version ? ` (${detail.runtime_version})` : ""}`
            : "-",
        },
        { key: "mean_failure_rate", label: t("平均失效率"), children: formatRate(detail.mean_failure_rate) },
        {
          key: "min_failure_rate",
          label: t("最小失效率"),
          children: (
            <>
              {formatRate(detail.min_failure_rate)}
              <span className="wind-detail-metric-suffix">{t("对应角度")} {detail.min_failure_rate_theta ?? "-"}</span>
            </>
          ),
        },
        {
          key: "max_failure_rate",
          label: t("最大失效率"),
          children: (
            <>
              {formatRate(detail.max_failure_rate)}
              <span className="wind-detail-metric-suffix">{t("对应角度")} {detail.max_failure_rate_theta ?? "-"}</span>
            </>
          ),
        },
        ...(detail.error_message
          ? [
              {
                key: "error_message",
                label: t("错误信息"),
                span: 2,
                children: <Text type="danger">{detail.error_message}</Text>,
              },
            ]
          : []),
      ]
    : [];

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
          {detail ? (
            <Card size="small" title={t("基本信息")}>
              <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={overviewItems} />
            </Card>
          ) : null}
        </div>
      ),
    },
    {
      key: "chart",
      label: t("失效率曲线"),
      children: (
        <div className="wind-detail-tab-content">
          {chartQuery.data ? (
            <Card size="small">
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
            label: t("逐角度结果"),
            children: (
              <Card size="small" className="wind-turbine-table-tab-card">
                <Table<WindTurbineCalcResultRow>
                  rowKey="theta_deg"
                  columns={columns}
                  dataSource={resultsQuery.data?.items ?? []}
                  loading={resultsQuery.isLoading}
                  sticky
                  pagination={false}
                  scroll={{ x: "max-content", y: "55vh" }}
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
        subline={
          <WindDetailSubline
            items={[
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
          detail?.status === "completed" ? (
            <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={handleExport}>
              {t("导出结果包")}
            </Button>
          ) : (
            <Button size="small" type="primary" icon={<ReloadOutlined />} onClick={refresh}>
              {t("刷新")}
            </Button>
          )
        }
      />

      <Tabs
        className="admin-atp-models-detail-tabs wind-detail-tabs wind-turbine-detail-tabs"
        items={tabItems}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key)}
      />

      <WindDetailPaginationFooter pagination={activePagination} />
    </div>
  );
}

export default WindTurbineCalcDetailView;
