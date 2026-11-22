"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Image,
  Progress,
  Segmented,
  Skeleton,
  Space,
  Table,
  Tabs,
  Typography,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  CloudOutlined,
  DownloadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import {
  WindDetailHero,
  WindDetailMeta,
  WindDetailMetricStrip,
  WindDetailPaginationFooter,
  WindDetailSubline,
  type WindDetailMetaItem,
  type WindDetailMetricItem,
  type WindDetailPaginationConfig,
} from "@/components/wind-detail-layout";
import { useI18n } from "@/lib/i18n";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import type {
  WindLightningDensityBatchDetail,
  WindLightningDensityCellListResponse,
  WindLightningDensityCellRow,
  WindLightningDensityTurbineListResponse,
  WindLightningDensityTurbineRow,
} from "@/types/wind-lightning-density";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-lightning-density";

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

/**
 * 风电场地闪密度统计详情视图。
 * 独立路由页与列表页的动态详情标签共用此组件，避免复制详情页逻辑。
 */
export function WindLightningDensityDetailView({
  batchId,
}: {
  batchId: string;
  onClose?: () => void;
}) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { user, fetchWithAuth: authFetch, hasPermission } = useAuth();
  const canRead = hasPermission("wind_lightning_density.read") || hasPermission("wind_lightning_density.manage");

  const [activeTab, setActiveTab] = useState("image");
  const [interpolation, setInterpolation] = useState<"bilinear" | "nearest">("bilinear");
  const [unit, setUnit] = useState<"km2" | "cell">("km2");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [cellPage, setCellPage] = useState(1);
  const [cellPageSize, setCellPageSize] = useState(20);
  const [cellSort, setCellSort] = useState<{ field: string; order: "asc" | "desc" }>({
    field: "density_per_km2_year",
    order: "desc",
  });
  const [turbinePage, setTurbinePage] = useState(1);
  const [turbinePageSize, setTurbinePageSize] = useState(20);

  const detailQuery = useQuery({
    queryKey: ["wind-lightning-density-detail", batchId],
    enabled: Boolean(user) && canRead && Boolean(batchId),
    queryFn: async () => getJson<WindLightningDensityBatchDetail>(`${API_BASE}/${batchId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });

  const detail = detailQuery.data;

  const cellsQuery = useQuery({
    queryKey: ["wind-lightning-density-cells", batchId, cellPage, cellPageSize, cellSort],
    enabled: Boolean(user) && canRead && detail?.status === "completed",
    queryFn: async () => {
      const search = new URLSearchParams();
      search.set("limit", String(cellPageSize));
      search.set("offset", String((cellPage - 1) * cellPageSize));
      search.set("sort_by", cellSort.field);
      search.set("sort_order", cellSort.order);
      return getJson<WindLightningDensityCellListResponse>(`${API_BASE}/${batchId}/cells?${search.toString()}`);
    },
  });

  const turbinesQuery = useQuery({
    queryKey: ["wind-lightning-density-turbines", batchId, turbinePage, turbinePageSize],
    enabled: Boolean(user) && canRead && detail?.status === "completed",
    queryFn: async () => {
      const search = new URLSearchParams();
      search.set("limit", String(turbinePageSize));
      search.set("offset", String((turbinePage - 1) * turbinePageSize));
      return getJson<WindLightningDensityTurbineListResponse>(
        `${API_BASE}/${batchId}/turbines?${search.toString()}`,
      );
    },
  });

  useEffect(() => {
    if (!detail || detail.status !== "completed" || !canRead) {
      setImageUrl(null);
      return;
    }
    let revoked: string | null = null;
    let cancelled = false;
    setImageLoading(true);
    setImageError(null);
    const load = async () => {
      try {
        const response = await authFetch(
          `${API_BASE}/${batchId}/image?unit=${unit}&interpolation=${interpolation}`,
        );
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const blob = await response.blob();
        if (cancelled) {
          return;
        }
        const url = URL.createObjectURL(blob);
        revoked = url;
        setImageUrl(url);
      } catch (error) {
        if (!cancelled) {
          setImageError((error as Error).message);
        }
      } finally {
        if (!cancelled) {
          setImageLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (revoked) {
        URL.revokeObjectURL(revoked);
      }
    };
  }, [authFetch, batchId, canRead, detail, interpolation, unit]);

  const handleDownloadImage = async () => {
    try {
      await downloadFileWithAuth(
        `${API_BASE}/${batchId}/image?unit=${unit}&interpolation=${interpolation}`,
        `${detail?.batch_name || "wind-lightning-density"}.png`,
      );
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const cellColumns = useMemo<TableColumnsType<WindLightningDensityCellRow>>(
    () => [
      { title: t("列号 i"), dataIndex: "cell_i", key: "cell_i", width: 90, sorter: true },
      { title: t("行号 j"), dataIndex: "cell_j", key: "cell_j", width: 90, sorter: true },
      {
        title: t("中心经度"),
        dataIndex: "center_lon",
        key: "center_lon",
        width: 120,
        render: (value: number) => value.toFixed(4),
      },
      {
        title: t("中心纬度"),
        dataIndex: "center_lat",
        key: "center_lat",
        width: 120,
        render: (value: number) => value.toFixed(4),
      },
      { title: t("落雷次数"), dataIndex: "strike_count", key: "strike_count", width: 110, sorter: true },
      {
        title: t("密度(次/(格·年))"),
        dataIndex: "density_per_cell_year",
        key: "density_per_cell_year",
        width: 160,
        sorter: true,
        render: (value: number) => formatNumber(value, 4),
      },
      {
        title: t("密度(次/(km²·年))"),
        dataIndex: "density_per_km2_year",
        key: "density_per_km2_year",
        width: 170,
        sorter: true,
        render: (value: number) => formatNumber(value, 4),
      },
      { title: t("风机数"), dataIndex: "turbine_count", key: "turbine_count", width: 100, sorter: true },
    ],
    [t],
  );

  const turbineColumns = useMemo<TableColumnsType<WindLightningDensityTurbineRow>>(
    () => [
      { title: t("序号"), dataIndex: "seq", key: "seq", width: 80 },
      { title: t("风机编号"), dataIndex: "turbine_no", key: "turbine_no", width: 120 },
      {
        title: t("经度"),
        dataIndex: "lon",
        key: "lon",
        width: 120,
        render: (value: number) => value.toFixed(6),
      },
      {
        title: t("纬度"),
        dataIndex: "lat",
        key: "lat",
        width: 120,
        render: (value: number) => value.toFixed(6),
      },
      { title: t("网格列号 i"), dataIndex: "cell_i", key: "cell_i", width: 110 },
      { title: t("网格行号 j"), dataIndex: "cell_j", key: "cell_j", width: 110 },
      {
        title: t("网格密度(次/(km²·年))"),
        dataIndex: "cell_density",
        key: "cell_density",
        width: 190,
        render: (value: number) => formatNumber(value, 4),
      },
    ],
    [t],
  );

  if (!canRead) {
    return (
      <div className="modo-page-card">
        <Empty description={t("当前账号没有风电场地闪密度统计的访问权限")} />
      </div>
    );
  }

  const metaItems: WindDetailMetaItem[] = detail
    ? [
        { label: t("风电场"), value: detail.wind_farm_name || "-" },
        { label: t("风机文件"), value: detail.turbine_source_file_name || "-" },
        { label: t("雷电文件"), value: detail.lightning_source_file_name || "-" },
        {
          label: t("统计范围"),
          span: 2,
          value: (
            <>
              {formatNumber(detail.bbox_min_lon, 4)} ~ {formatNumber(detail.bbox_max_lon, 4)}（{t("经度")}）
              {" / "}
              {formatNumber(detail.bbox_min_lat, 4)} ~ {formatNumber(detail.bbox_max_lat, 4)}（{t("纬度")}）
            </>
          ),
        },
        { label: t("网格数"), value: `${detail.grid_x_count} × ${detail.grid_y_count}` },
        { label: t("网格步长 / 边距"), value: `${detail.grid_step_deg}° / ${detail.margin_deg}°` },
      ]
    : [];

  const completed = detail?.status === "completed";

  // 关键指标条：最多 6 项，统一走共用组件，不再各页自己拼 Statistic 卡片。
  const metricItems: WindDetailMetricItem[] = [
    { label: t("风机数"), value: detail?.turbine_count ?? 0 },
    { label: t("有效落雷"), value: detail?.valid_records ?? 0 },
    { label: t("范围面积 (km²)"), value: formatNumber(detail?.area_km2, 2) },
    { label: t("平均密度 次/(km²·年)"), value: formatNumber(detail?.overall_density, 4) },
    { label: t("峰值密度 次/(km²·年)"), value: formatNumber(detail?.peak_density, 4) },
    { label: t("统计年限"), value: detail?.data_years ?? "-", suffix: t("年") },
  ];

  // 分页底栏由当前激活 Tab 的表格状态驱动；无表格的 Tab 不渲染底栏。
  const activePagination: WindDetailPaginationConfig | null =
    completed && activeTab === "cells"
      ? {
          current: cellPage,
          pageSize: cellPageSize,
          total: cellsQuery.data?.total ?? 0,
          pageSizeOptions: [10, 20, 50, 100],
          onChange: (nextPage, nextSize) => {
            setCellPage(nextPage);
            if (nextSize && nextSize !== cellPageSize) {
              setCellPageSize(nextSize);
              setCellPage(1);
            }
          },
        }
      : completed && activeTab === "turbines"
        ? {
            current: turbinePage,
            pageSize: turbinePageSize,
            total: turbinesQuery.data?.total ?? 0,
            pageSizeOptions: [10, 20, 50, 100],
            onChange: (nextPage, nextSize) => {
              setTurbinePage(nextPage);
              if (nextSize && nextSize !== turbinePageSize) {
                setTurbinePageSize(nextSize);
                setTurbinePage(1);
              }
            },
          }
        : null;

  const tabItems: NonNullable<TabsProps["items"]> = [
    ...(completed
      ? [
          {
            key: "image",
            label: t("地闪密度图"),
            children: (
              <div className="wind-detail-tab-content wind-density-image-layout">
                <Card
                  className="wind-density-image-card"
                  size="small"
                  title={t("地闪密度图")}
                  extra={
                    <Space wrap>
                      <Segmented
                        value={interpolation}
                        onChange={(value) => setInterpolation(value as "bilinear" | "nearest")}
                        options={[
                          { label: t("平滑 bilinear"), value: "bilinear" },
                          { label: t("网格 nearest"), value: "nearest" },
                        ]}
                      />
                      <Segmented
                        value={unit}
                        onChange={(value) => setUnit(value as "km2" | "cell")}
                        options={[
                          { label: t("次/(km²·年)"), value: "km2" },
                          { label: t("次/(格·年)"), value: "cell" },
                        ]}
                      />
                    </Space>
                  }
                >
                  {imageLoading ? (
                    <Skeleton.Image active style={{ width: 640, height: 420 }} />
                  ) : imageError ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={imageError} />
                  ) : imageUrl ? (
                    <Image
                      src={imageUrl}
                      alt={t("地闪密度图")}
                      preview={false}
                      style={{ maxWidth: "100%", borderRadius: 6, border: "1px solid #f0f0f0" }}
                    />
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无密度图")} />
                  )}
                </Card>
                {detail ? (
                  <div className="wind-density-meta-panel">
                    <WindDetailMeta items={metaItems} />
                  </div>
                ) : null}
              </div>
            ),
          },
        ]
      : []),
    ...(completed
      ? [
          {
            key: "cells",
            label: `${t("网格密度表")} (${cellsQuery.data?.total ?? 0})`,
            children: (
              <Card
                size="small"
                title={t("网格密度表")}
                extra={<Text type="secondary">{t("仅展示有落雷或有风机的网格")}</Text>}
              >
                <Table<WindLightningDensityCellRow>
                  rowKey={(record) => `${record.cell_i}-${record.cell_j}`}
                  size="small"
                  columns={cellColumns}
                  dataSource={cellsQuery.data?.items ?? []}
                  loading={cellsQuery.isLoading}
                  pagination={false}
                  scroll={{ x: 1000 }}
                  onChange={(_pagination, _filters, sorter, extra) => {
                    if (extra.action !== "sort") {
                      return;
                    }
                    const current = Array.isArray(sorter) ? sorter[0] : sorter;
                    const field = String(current?.field ?? "density_per_km2_year");
                    const order = current?.order === "ascend" ? "asc" : "desc";
                    setCellSort({ field, order });
                    setCellPage(1);
                  }}
                />
              </Card>
            ),
          },
        ]
      : []),
    ...(completed
      ? [
          {
            key: "turbines",
            label: `${t("风机明细")} (${detail?.turbine_count ?? 0})`,
            children: (
              <Card size="small" title={t("风机明细")}>
                <Table<WindLightningDensityTurbineRow>
                  rowKey={(record) => String(record.seq)}
                  size="small"
                  columns={turbineColumns}
                  dataSource={turbinesQuery.data?.items ?? []}
                  loading={turbinesQuery.isLoading}
                  pagination={false}
                  scroll={{ x: 900 }}
                />
              </Card>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="wind-detail-pane wind-density-detail-pane">
      <WindDetailHero
        icon={<CloudOutlined />}
        title={detail?.batch_name || batchId}
        titleTooltip={detail?.batch_name || batchId}
        subline={
          <WindDetailSubline
            items={[
              detail?.wind_farm_name ? (
                <span key="farm">{detail.wind_farm_name}</span>
              ) : null,
              detail ? (
                <span key="created">
                  {t("创建时间")} {formatDateTime(detail.create_date)}
                </span>
              ) : null,
              detail && (detail.status === "pending" || detail.status === "processing") ? (
                <Progress key="progress" percent={detail.progress} size="small" style={{ width: 140 }} />
              ) : null,
            ]}
          />
        }
        actions={
          <>
            <Button
              size="small"
              type="primary"
              icon={<DownloadOutlined />}
              disabled={!completed}
              onClick={() => void handleDownloadImage()}
            >
              {t("下载密度图")}
            </Button>
          </>
        }
      />

      {detail?.status === "failed" ? (
        <Alert
          className="wind-detail-alert"
          type="error"
          showIcon
          message={t("统计失败")}
          description={detail.error_message}
        />
      ) : null}

      {detail ? <WindDetailMetricStrip items={metricItems} /> : null}

      <Tabs
        className="admin-atp-models-detail-tabs wind-detail-tabs wind-density-detail-tabs"
        items={tabItems}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key)}
      />

      <WindDetailPaginationFooter pagination={activePagination} />
    </div>
  );
}

export default WindLightningDensityDetailView;
