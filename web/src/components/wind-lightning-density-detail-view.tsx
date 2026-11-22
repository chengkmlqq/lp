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
  Skeleton,
  Table,
  Tabs,
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

/** LP-83：统计任务预生成的 4 种组合；与后端 IMAGE_VARIANT_COMBOS 一一对应。 */
const DENSITY_VARIANTS = [
  { key: "bilinear-km2", unit: "km2", interpolation: "bilinear", label: "平滑 bilinear · 次/(km²·年)" },
  { key: "bilinear-cell", unit: "cell", interpolation: "bilinear", label: "平滑 bilinear · 次/(格·年)" },
  { key: "nearest-km2", unit: "km2", interpolation: "nearest", label: "网格 nearest · 次/(km²·年)" },
  { key: "nearest-cell", unit: "cell", interpolation: "nearest", label: "网格 nearest · 次/(格·年)" },
] as const;

type DensityVariant = (typeof DENSITY_VARIANTS)[number];

/** 单张密度图：直接请求已存图片，支持点击预览与单独下载。 */
function DensityImageCard({
  batchId,
  batchName,
  variant,
}: {
  batchId: string;
  batchName: string;
  variant: DensityVariant;
}) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { fetchWithAuth: authFetch } = useAuth();
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);

  const imagePath = `${API_BASE}/${batchId}/image?unit=${variant.unit}&interpolation=${variant.interpolation}`;
  const label = t(variant.label);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    setImageLoading(true);
    setImageError(null);
    const load = async () => {
      try {
        const response = await authFetch(imagePath);
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
  }, [authFetch, imagePath]);

  const handleDownload = async () => {
    try {
      await downloadFileWithAuth(
        imagePath,
        `${batchName || "wind-lightning-density"}-${variant.key}.png`,
      );
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  return (
    <div className="wind-density-image-card">
      <div className="wind-density-image-card-header">
        <span>{label}</span>
        <Button
          size="small"
          type="text"
          icon={<DownloadOutlined />}
          title={t("下载该图")}
          aria-label={t("下载该图")}
          onClick={() => void handleDownload()}
        />
      </div>
      <div className="wind-density-image-card-body">
        {imageLoading ? (
          <Skeleton.Image active />
        ) : imageError ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={imageError} />
        ) : imageUrl ? (
          <Image
            src={imageUrl}
            alt={label}
            style={{ maxWidth: "100%", borderRadius: 6 }}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无密度图")} />
        )}
      </div>
    </div>
  );
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
  const { user, hasPermission } = useAuth();
  const canRead = hasPermission("wind_lightning_density.read") || hasPermission("wind_lightning_density.manage");

  const [activeTab, setActiveTab] = useState("overview");
  const [cellPage, setCellPage] = useState(1);
  const [cellPageSize, setCellPageSize] = useState(20);
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
    queryKey: ["wind-lightning-density-cells", batchId, cellPage, cellPageSize],
    enabled: Boolean(user) && canRead && detail?.status === "completed",
    queryFn: async () => {
      const search = new URLSearchParams();
      search.set("limit", String(cellPageSize));
      search.set("offset", String((cellPage - 1) * cellPageSize));
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

  const cellColumns = useMemo<TableColumnsType<WindLightningDensityCellRow>>(
    () => [
      {
        title: t("列号 i"),
        tooltip: t("经度方向网格编号，从 1 起；以统计范围左下角为起点，按网格步长切分"),
        dataIndex: "cell_i",
        key: "cell_i",
        width: 90,
      },
      {
        title: t("行号 j"),
        tooltip: t("纬度方向网格编号，从 1 起；以统计范围左下角为起点，按网格步长切分"),
        dataIndex: "cell_j",
        key: "cell_j",
        width: 90,
      },
      {
        title: t("中心经度"),
        tooltip: t("该网格中心的经度，十进制度"),
        dataIndex: "center_lon",
        key: "center_lon",
        width: 120,
        render: (value: number) => value.toFixed(4),
      },
      {
        title: t("中心纬度"),
        tooltip: t("该网格中心的纬度，十进制度"),
        dataIndex: "center_lat",
        key: "center_lat",
        width: 120,
        render: (value: number) => value.toFixed(4),
      },
      {
        title: t("落雷次数"),
        tooltip: t("统计年限内落入该网格的有效雷电定位记录条数"),
        dataIndex: "strike_count",
        key: "strike_count",
        width: 110,
      },
      {
        title: t("密度(次/(格·年))"),
        tooltip: t("落雷次数除以统计年限，即该网格每年平均落雷次数"),
        dataIndex: "density_per_cell_year",
        key: "density_per_cell_year",
        width: 160,
        render: (value: number) => formatNumber(value, 4),
      },
      {
        title: t("密度(次/(km²·年))"),
        tooltip: t("每格年密度除以单格面积(km²)；默认 0.01° 网格约 1 km²，数值与每格年密度相同"),
        dataIndex: "density_per_km2_year",
        key: "density_per_km2_year",
        width: 170,
        render: (value: number) => formatNumber(value, 4),
      },
      {
        title: t("风机数"),
        tooltip: t("落在该网格内的风机数量"),
        dataIndex: "turbine_count",
        key: "turbine_count",
        width: 100,
      },
    ],
    [t],
  );

  const turbineColumns = useMemo<TableColumnsType<WindLightningDensityTurbineRow>>(
    () => [
      {
        title: t("风机编号"),
        tooltip: t("风机点位文件中的顺序编号"),
        dataIndex: "turbine_no",
        key: "turbine_no",
        width: 120,
      },
      {
        title: t("经度"),
        tooltip: t("风机经度坐标，十进制度，保留 6 位小数"),
        dataIndex: "lon",
        key: "lon",
        width: 120,
        render: (value: number) => value.toFixed(6),
      },
      {
        title: t("纬度"),
        tooltip: t("风机纬度坐标，十进制度，保留 6 位小数"),
        dataIndex: "lat",
        key: "lat",
        width: 120,
        render: (value: number) => value.toFixed(6),
      },
      {
        title: t("网格列号 i"),
        tooltip: t("该风机落入网格的列号（经度方向，从 1 起）"),
        dataIndex: "cell_i",
        key: "cell_i",
        width: 110,
      },
      {
        title: t("网格行号 j"),
        tooltip: t("该风机落入网格的行号（纬度方向，从 1 起）"),
        dataIndex: "cell_j",
        key: "cell_j",
        width: 110,
      },
      {
        title: t("网格密度(次/(km²·年))"),
        tooltip: t("该风机所在网格的地闪密度，单位次/(km²·年)"),
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

  // 概览信息按来源 / 范围与网格分组，渲染在同一张无标题 Card 内，用细线区分。
  const sourceMetaItems: WindDetailMetaItem[] = detail
    ? [
        { label: t("风电场"), value: detail.wind_farm_name || "-" },
        { label: t("风机文件"), value: detail.turbine_source_file_name || "-" },
        { label: t("雷电文件"), value: detail.lightning_source_file_name || "-" },
      ]
    : [];

  const gridMetaItems: WindDetailMetaItem[] = detail
    ? [
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
    {
      key: "overview",
      label: t("概览"),
      children: (
        <div className="wind-detail-tab-content">
          {detail ? (
            <Card size="small" className="wind-detail-overview-card">
              <WindDetailMeta items={sourceMetaItems} />
              <div className="wind-detail-overview-divider" />
              <WindDetailMeta items={gridMetaItems} />
              <div className="wind-detail-overview-divider" />
              <WindDetailMetricStrip items={metricItems} />
            </Card>
          ) : null}
        </div>
      ),
    },
    {
      key: "image",
      label: t("地闪密度图"),
      children: (
        <div className="wind-detail-tab-content">
          <Card size="small">
            {completed ? (
              <div className="wind-density-image-grid">
                {DENSITY_VARIANTS.map((variant) => (
                  <DensityImageCard
                    key={variant.key}
                    batchId={batchId}
                    batchName={detail?.batch_name || ""}
                    variant={variant}
                  />
                ))}
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("统计完成后可查看密度图")}
              />
            )}
          </Card>
        </div>
      ),
    },
    {
      key: "cells",
      label: `${t("网格密度表")} (${cellsQuery.data?.total ?? 0})`,
      children: (
        <Card size="small">
          <Table<WindLightningDensityCellRow>
            rowKey={(record) => `${record.cell_i}-${record.cell_j}`}
            size="small"
            columns={cellColumns}
            dataSource={cellsQuery.data?.items ?? []}
            loading={cellsQuery.isLoading}
            pagination={false}
            scroll={{ x: 1000 }}
          />
        </Card>
      ),
    },
    {
      key: "turbines",
      label: `${t("风机明细")} (${detail?.turbine_count ?? 0})`,
      children: (
        <Card size="small">
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
