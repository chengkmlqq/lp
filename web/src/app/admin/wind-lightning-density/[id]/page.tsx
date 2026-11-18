"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Image,
  Modal,
  Progress,
  Row,
  Segmented,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { ArrowLeftOutlined, DownloadOutlined, FileTextOutlined, ReloadOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { ModoPagination } from "@/components/biz/modo-pagination";
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

const STATUS_COLORS: Record<string, string> = {
  pending: "default",
  processing: "processing",
  completed: "success",
  failed: "error",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};

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

export default function WindLightningDensityDetailPage() {
  const params = useParams();
  const batchId = String(params?.id ?? "");
  const { t } = useI18n();
  const { message } = App.useApp();
  const { user, fetchWithAuth: authFetch, hasPermission } = useAuth();
  const canRead = hasPermission("wind_lightning_density.read") || hasPermission("wind_lightning_density.manage");
  const canManage = hasPermission("wind_lightning_density.manage");

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
  const [coreModalOpen, setCoreModalOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);

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

  const handleExport = async (path: string, fallbackName: string) => {
    try {
      await downloadFileWithAuth(path, fallbackName);
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const handleRecompute = async () => {
    const response = await authFetch(`${API_BASE}/${batchId}/recompute`, { method: "POST" });
    if (!response.ok) {
      message.error(await readApiError(response));
      return;
    }
    message.success(t("已提交重算任务"));
    void detailQuery.refetch();
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

  const warnings = (detail?.stats_json?.warnings as string[] | undefined) ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="modo-page-card">
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Space wrap>
            <Link href="/admin/wind-lightning-density">
              <Button icon={<ArrowLeftOutlined />}>{t("返回列表")}</Button>
            </Link>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {detail?.batch_name || batchId}
            </Typography.Title>
            {detail ? (
              <Tag color={STATUS_COLORS[detail.status] ?? "default"}>
                {t(STATUS_LABELS[detail.status] ?? detail.status)}
              </Tag>
            ) : null}
            {detail?.status === "processing" || detail?.status === "pending" ? (
              <Progress percent={detail.progress} size="small" style={{ width: 160 }} />
            ) : null}
            <Button icon={<FileTextOutlined />} onClick={() => setLogOpen(true)} disabled={!detail?.task_id}>
              {t("运行日志")}
            </Button>
            {canManage ? (
              <Button icon={<ReloadOutlined />} onClick={handleRecompute} disabled={detail?.status === "processing"}>
                {t("重算")}
              </Button>
            ) : null}
            {detail?.status === "completed" ? (
              <Space>
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() =>
                    void handleExport(
                      `${API_BASE}/${batchId}/export?type=all`,
                      `${detail.batch_name || "wind-lightning-density"}-all.xlsx`,
                    )
                  }
                >
                  {t("数据导出")}
                </Button>
                <Button icon={<DownloadOutlined />} onClick={() => setCoreModalOpen(true)}>
                  {t("核心程序文件（file_3/file_4）")}
                </Button>
              </Space>
            ) : null}
          </Space>

          {detail ? (
            <Descriptions size="small" column={4} bordered>
              <Descriptions.Item label={t("风电场")}>{detail.wind_farm_name || "-"}</Descriptions.Item>
              <Descriptions.Item label={t("风机文件")}>{detail.turbine_source_file_name || "-"}</Descriptions.Item>
              <Descriptions.Item label={t("雷电文件")}>{detail.lightning_source_file_name || "-"}</Descriptions.Item>
              <Descriptions.Item label={t("创建时间")}>{formatDateTime(detail.create_date)}</Descriptions.Item>
              <Descriptions.Item label={t("统计范围")} span={2}>
                {formatNumber(detail.bbox_min_lon, 4)} ~ {formatNumber(detail.bbox_max_lon, 4)}（{t("经度")}）
                {" / "}
                {formatNumber(detail.bbox_min_lat, 4)} ~ {formatNumber(detail.bbox_max_lat, 4)}（{t("纬度")}）
              </Descriptions.Item>
              <Descriptions.Item label={t("网格数")}>
                {detail.grid_x_count} × {detail.grid_y_count}
              </Descriptions.Item>
              <Descriptions.Item label={t("网格步长 / 边距")}>
                {detail.grid_step_deg}° / {detail.margin_deg}°
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {detail?.status === "failed" ? (
            <Alert type="error" showIcon message={t("统计失败")} description={detail.error_message} />
          ) : null}
          {warnings.length ? (
            <Alert
              type="warning"
              showIcon
              message={t("提示")}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {warnings.map((warning) => (
                    <li key={warning}>{t(warning)}</li>
                  ))}
                </ul>
              }
            />
          ) : null}

          <Row gutter={16}>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic title={t("风机数")} value={detail?.turbine_count ?? 0} />
              </Card>
            </Col>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic title={t("有效落雷")} value={detail?.valid_records ?? 0} />
              </Card>
            </Col>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic
                  title={t("范围面积 (km²)")}
                  value={formatNumber(detail?.area_km2, 2)}
                />
              </Card>
            </Col>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic
                  title={t("平均密度 次/(km²·年)")}
                  value={formatNumber(detail?.overall_density, 4)}
                />
              </Card>
            </Col>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic
                  title={t("峰值密度 次/(km²·年)")}
                  value={formatNumber(detail?.peak_density, 4)}
                />
              </Card>
            </Col>
            <Col xs={12} md={8} lg={4}>
              <Card size="small">
                <Statistic
                  title={t("统计年限")}
                  value={detail?.data_years ?? "-"}
                  suffix={t("年")}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {detail
                    ? detail.years_source === "fixed"
                      ? t("固定 6 年")
                      : detail.stats_json?.years_inferred
                        ? t("自动推断（雷电数据实际覆盖年份）")
                        : t("默认 6 年（无法从时间列推断）")
                    : "-"}
                </Text>
              </Card>
            </Col>
          </Row>

          <Card
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
                <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadImage}>
                  {t("下载图片")}
                </Button>
              </Space>
            }
          >
            {detail?.status !== "completed" ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  detail?.status === "failed" ? t("统计失败，暂无密度图") : t("统计完成后可查看密度图")
                }
              />
            ) : imageLoading ? (
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

          <Card size="small" title={t("网格密度表")} extra={<Text type="secondary">{t("仅展示有落雷或有风机的网格")}</Text>}>
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
              footer={() => (
                <ModoPagination
                  current={cellPage}
                  pageSize={cellPageSize}
                  total={cellsQuery.data?.total ?? 0}
                  pageSizeOptions={[10, 20, 50, 100]}
                  onChange={(nextPage, nextSize) => {
                    setCellPage(nextPage);
                    if (nextSize && nextSize !== cellPageSize) {
                      setCellPageSize(nextSize);
                      setCellPage(1);
                    }
                  }}
                  style={{ marginTop: 0 }}
                />
              )}
            />
          </Card>

          <Card size="small" title={t("风机明细")}>
            <Table<WindLightningDensityTurbineRow>
              rowKey={(record) => String(record.seq)}
              size="small"
              columns={turbineColumns}
              dataSource={turbinesQuery.data?.items ?? []}
              loading={turbinesQuery.isLoading}
              pagination={false}
              scroll={{ x: 900 }}
              footer={() => (
                <ModoPagination
                  current={turbinePage}
                  pageSize={turbinePageSize}
                  total={turbinesQuery.data?.total ?? 0}
                  pageSizeOptions={[10, 20, 50, 100]}
                  onChange={(nextPage, nextSize) => {
                    setTurbinePage(nextPage);
                    if (nextSize && nextSize !== turbinePageSize) {
                      setTurbinePageSize(nextSize);
                      setTurbinePage(1);
                    }
                  }}
                  style={{ marginTop: 0 }}
                />
              )}
            />
          </Card>
        </Space>
      </div>

      <Modal
        title={t("核心程序文件（file_3 / file_4）")}
        open={coreModalOpen}
        onCancel={() => setCoreModalOpen(false)}
        onOk={() => {
          void handleExport(
            `${API_BASE}/${batchId}/export-core`,
            `${detail?.batch_name || "wind-lightning-density"}-file_3-file_4.zip`,
          );
          setCoreModalOpen(false);
        }}
        okText={t("下载 zip")}
        cancelText={t("取消")}
      >
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Text type="secondary">
            {t(
              "按风电场研究区域网格（与核心程序 file_1.txt 一致）导出：file_3 为风机所在网格编号，file_4 为对应网格地闪密度（次/(km²·年)）。",
            )}
          </Text>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label={t("起始经度")}>{detail?.core_grid?.start_lon ?? "-"}</Descriptions.Item>
            <Descriptions.Item label={t("起始纬度")}>{detail?.core_grid?.start_lat ?? "-"}</Descriptions.Item>
            <Descriptions.Item label={t("网格列数 x_count")}>{detail?.core_grid?.x_count ?? "-"}</Descriptions.Item>
            <Descriptions.Item label={t("网格行数 y_count")}>{detail?.core_grid?.y_count ?? "-"}</Descriptions.Item>
            <Descriptions.Item label={t("风机数（行数校验）")} span={2}>
              {detail?.turbine_count ?? 0}
            </Descriptions.Item>
          </Descriptions>
        </Space>
      </Modal>

      <TaskLogViewerDrawer
        taskId={detail?.task_id ?? null}
        title={t("运行日志")}
        open={logOpen}
        onClose={() => setLogOpen(false)}
      />
    </div>
  );
}
