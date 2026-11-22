"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Spin,
  Table,
  Tabs,
  Typography,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  ArrowLeftOutlined,
  CloseOutlined,
  CloudDownloadOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import {
  WindDetailHero,
  WindDetailMeta,
  WindDetailMetricStrip,
  WindDetailMoreActions,
  WindDetailPaginationFooter,
  WindDetailSubline,
  type WindDetailMetaItem,
  type WindDetailMetricItem,
  type WindDetailPaginationConfig,
} from "@/components/wind-detail-layout";
import { useI18n } from "@/lib/i18n";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import type {
  WindDataPrepBatchDetail,
  WindDataPrepTurbineListResponse,
  WindDataPrepTurbineRow,
} from "@/types/wind-data-prep";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-data-prep";

const FILES = [
  { name: "file1", label: "file_1.txt（区域参数）" },
  { name: "file2", label: "file_2.txt（风机清单）" },
  { name: "file3", label: "file_3.txt（网格编号）" },
  { name: "file4", label: "file_4.txt（落雷次数 Nl）" },
  { name: "p0abc", label: "P0.abc（地形高程）" },
];

// 等宽文件内容区：限制高度并允许滚动，窄屏下也不会撑破页面。
const FILE_CONTENT_STYLE: CSSProperties = {
  margin: 0,
  padding: 12,
  minHeight: 320,
  maxHeight: "60vh",
  overflow: "auto",
  background: "#fafafa",
  whiteSpace: "pre",
  wordBreak: "normal",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  fontSize: 12,
  lineHeight: "18px",
  borderRadius: 4,
};

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * 文本文件 Tab 内容：按需（Tab 激活且任务完成后）用 preview=1 接口取纯文本，等宽展示。
 */
function FileTextPreview({
  batchId,
  name,
  enabled,
}: {
  batchId: string;
  name: string;
  enabled: boolean;
}) {
  const { t } = useI18n();
  const { user, fetchWithAuth } = useAuth();
  const query = useQuery({
    queryKey: ["wind-data-prep-file-content", batchId, name],
    enabled: enabled && Boolean(user),
    queryFn: async () => {
      const response = await fetchWithAuth(`${API_BASE}/${batchId}/files/${name}?preview=1`);
      if (!response.ok) throw new Error(await readApiError(response));
      return response.text();
    },
  });

  if (!enabled) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("任务完成后显示文件内容")}
      />
    );
  }
  if (query.isLoading) {
    return (
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin />
      </div>
    );
  }
  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("读取文件失败")}
        description={(query.error as Error)?.message}
      />
    );
  }
  return <pre style={FILE_CONTENT_STYLE}>{query.data || t("（空文件）")}</pre>;
}

/**
 * P0.abc 是二进制：不展示 raw 内容，只展示已有的头部 6 个 uint16 数值与字节数/校验信息。
 */
function P0abcHeaderView({
  header,
}: {
  header: WindDataPrepBatchDetail["p0abc_header"] | undefined;
}) {
  const { t } = useI18n();
  if (!header || !Object.keys(header).length) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("任务完成后显示 P0.abc 头部信息")}
      />
    );
  }

  const items = [
    { key: "left", label: t("左边界 left"), value: String(header.left ?? "-") },
    { key: "right", label: t("右边界 right"), value: String(header.right ?? "-") },
    { key: "bottom", label: t("下边界 bottom"), value: String(header.bottom ?? "-") },
    { key: "top", label: t("上边界 top"), value: String(header.top ?? "-") },
    { key: "width", label: t("格数 width"), value: String(header.width ?? "-") },
    { key: "height", label: t("格数 height"), value: String(header.height ?? "-") },
    { key: "byte_size", label: t("字节数"), value: String(header.byte_size ?? "-") },
    { key: "expected_byte_size", label: t("预期字节数"), value: String(header.expected_byte_size ?? "-") },
    { key: "row_order", label: t("行序"), value: header.row_order || "-" },
  ].map(({ key, label, value }) => ({ key, label, children: value }));

  const matched =
    typeof header.byte_size === "number" &&
    typeof header.expected_byte_size === "number" &&
    header.byte_size === header.expected_byte_size;

  return (
    <Card size="small" title={t("P0.abc 头部（6 个 uint16 大端数值）")}>
      <Descriptions size="small" bordered column={{ xs: 1, sm: 2, md: 3 }} items={items} />
      <Alert
        style={{ marginTop: 12 }}
        type={matched ? "success" : "warning"}
        showIcon
        message={matched ? t("字节数校验通过") : t("字节数与预期不一致")}
      />
    </Card>
  );
}

/**
 * 风电场数据准备详情视图。
 * 独立路由页与列表页的动态详情标签共用此组件，避免复制详情页逻辑。
 */
export function WindDataPrepDetailView({
  batchId,
  onClose,
}: {
  batchId: string;
  onClose?: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("wind_data_prep.manage");
  const [activeTab, setActiveTab] = useState("overview");
  const [turbinePage, setTurbinePage] = useState(1);
  const [turbinePageSize, setTurbinePageSize] = useState(20);

  const detailQuery = useQuery({
    queryKey: ["wind-data-prep-detail", batchId],
    enabled: Boolean(user) && Boolean(batchId),
    queryFn: async () => getJson<WindDataPrepBatchDetail>(`${API_BASE}/${batchId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });
  const detail = detailQuery.data;

  const turbineQuery = useQuery({
    queryKey: ["wind-data-prep-detail", batchId, "turbines", turbinePage, turbinePageSize],
    enabled: Boolean(user) && Boolean(batchId) && detail?.status === "completed",
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", String(turbinePageSize));
      query.set("offset", String((turbinePage - 1) * turbinePageSize));
      return getJson<WindDataPrepTurbineListResponse>(`${API_BASE}/${batchId}/turbines?${query.toString()}`);
    },
  });

  const handleDownload = useCallback(
    async (name: string, label: string) => {
      try {
        await downloadFileWithAuth(`${API_BASE}/${batchId}/files/${name}`, label.replace(/（.*/, "").trim());
      } catch (error) {
        message.error((error as Error).message);
      }
    },
    [batchId, message],
  );

  const handleRecompute = useCallback(() => {
    modal.confirm({
      title: t("用原文件按当前参数重跑？"),
      content: t("旧的风机明细与五个产物文件将被清空并重新生成。"),
      okText: t("重跑"),
      cancelText: t("取消"),
      onOk: async () => {
        const response = await fetchWithAuth(`${API_BASE}/${batchId}/recompute`, { method: "POST" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已提交重跑任务"));
        void detailQuery.refetch();
      },
    });
  }, [batchId, detailQuery, fetchWithAuth, message, modal, t]);

  const turbineColumns = useMemo<TableColumnsType<WindDataPrepTurbineRow>>(
    () => [
      { title: t("序号"), dataIndex: "seq", key: "seq", width: 70 },
      { title: t("风机编号"), dataIndex: "turbine_no", key: "turbine_no", width: 100 },
      {
        title: t("经纬度"),
        key: "coord",
        width: 180,
        render: (_value, record) => `${formatNumber(record.lon, 6)}, ${formatNumber(record.lat, 6)}`,
      },
      { title: t("cell_i"), dataIndex: "cell_i", key: "cell_i", width: 80 },
      { title: t("cell_j"), dataIndex: "cell_j", key: "cell_j", width: 80 },
      { title: t("grid_id"), dataIndex: "grid_id", key: "grid_id", width: 90 },
      {
        title: t("本格落雷"),
        dataIndex: "flash_count",
        key: "flash_count",
        width: 100,
        render: (value: number) => <Text strong>{value}</Text>,
      },
      {
        title: t("东邻格（错位对照）"),
        dataIndex: "flash_count_east",
        key: "flash_count_east",
        width: 140,
        render: (value: number, record) =>
          value === record.flash_count ? (
            <Text type="secondary">{value}</Text>
          ) : (
            <Text type="warning">{value}</Text>
          ),
      },
      {
        title: t("Nl（次/(格·年)）"),
        dataIndex: "nl",
        key: "nl",
        width: 130,
        render: (value: number) => formatNumber(value, 6),
      },
      { title: t("风机高度"), dataIndex: "height", key: "height", width: 100, render: (v: number | null) => formatNumber(v, 2) },
      { title: t("叶片长度"), dataIndex: "blade", key: "blade", width: 100, render: (v: number | null) => formatNumber(v, 2) },
      { title: t("动静状态"), dataIndex: "motion", key: "motion", width: 90 },
      { title: t("回路号"), dataIndex: "circuit", key: "circuit", width: 80 },
    ],
    [t],
  );

  if (initializing) return null;

  const titleText = detail?.name || batchId;
  // 基本信息全部收进「概览」Tab，顶部不再单列属性网格。
  const metaItems: WindDetailMetaItem[] = [
    { label: t("风电场"), value: detail?.wind_farm_name || "-" },
    { label: t("风机文件"), value: detail?.turbine_file_name || "-" },
    { label: t("雷电文件"), value: detail?.lightning_file_name || "-" },
    { label: t("地形文件"), value: detail?.terrain_file_name || "-" },
    { label: t("起始经度"), value: formatNumber(detail?.start_lon, 6) },
    { label: t("起始纬度"), value: formatNumber(detail?.start_lat, 6) },
    { label: t("网格 nx × ny"), value: detail ? `${detail.grid_nx} × ${detail.grid_ny}` : "-" },
    { label: t("网格步长"), value: detail?.grid_step_deg ?? "-" },
    { label: t("风险基准 S"), value: formatNumber(detail?.risk_base_s, 4) },
    { label: t("统计年限"), value: t("固定 6 年") },
    { label: t("地形模式"), value: detail?.terrain_mode === "tif" ? t("上传 tif") : t("零高程") },
    // 原「文件清单」Tab 删除后，文件齐全度改在概览展示（需求：5/5）。
    { label: t("五文件齐全度"), value: detail ? `${detail.files_ready ?? 0}/5` : "-" },
  ];

  const completed = detail?.status === "completed";

  // 关键指标条：8 项全部放进「概览」Tab，顶部不再常驻。
  const metricItems: WindDetailMetricItem[] = [
    { label: t("风机数"), value: detail?.turbine_count ?? 0 },
    { label: t("范围内落雷数"), value: detail?.lightning_in_scope ?? 0 },
    { label: t("非零网格数"), value: detail?.nonzero_cell_count ?? 0 },
    { label: t("零 Nl 风机数"), value: detail?.zero_nl_turbine_count ?? 0 },
    { label: t("Nl 最大"), value: formatNumber(detail?.nl_max, 4) },
    { label: t("Nl 最小"), value: formatNumber(detail?.nl_min, 4) },
    { label: t("Nl 均值"), value: formatNumber(detail?.nl_avg, 4) },
    { label: t("数据时间跨度"), value: (detail?.stats_json?.time_span as string) || "-" },
  ];

  // 分页底栏由当前激活 Tab 驱动，仅风机明细 Tab 需要分页。
  const activePagination: WindDetailPaginationConfig | null =
    completed && activeTab === "turbines"
      ? {
          current: turbinePage,
          pageSize: turbinePageSize,
          total: turbineQuery.data?.total ?? 0,
          pageSizeOptions: [20, 50, 100, 500],
          onChange: (nextPage, nextSize) => {
            setTurbinePage(nextPage);
            if (nextSize && nextSize !== turbinePageSize) {
              setTurbinePageSize(nextSize);
              setTurbinePage(1);
            }
          },
        }
      : null;

  // 五个产物各占一个 Tab，排在「概览」「风机明细」之后。
  const fileTabs = FILES.map((file) => ({
    key: `file-${file.name}`,
    label: t(file.label),
    children: (
      <div className="wind-detail-tab-content">
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            disabled={detail?.status !== "completed"}
            onClick={() => void handleDownload(file.name, file.label)}
          >
            {t("下载")}
          </Button>
        </div>
        {file.name === "p0abc" ? (
          <P0abcHeaderView header={detail?.p0abc_header} />
        ) : (
          <FileTextPreview
            batchId={batchId}
            name={file.name}
            enabled={completed && activeTab === `file-${file.name}`}
          />
        )}
      </div>
    ),
  }));

  const tabItems: NonNullable<TabsProps["items"]> = [
    {
      key: "overview",
      label: t("概览"),
      children: (
        <div className="wind-detail-tab-content">
          {detail ? <WindDetailMetricStrip items={metricItems} /> : null}
          {detail ? (
            <Card size="small" title={t("基本信息")}>
              <WindDetailMeta items={metaItems} />
            </Card>
          ) : null}
        </div>
      ),
    },
    ...(completed
      ? [
          {
            key: "turbines",
            label: `${t("风机明细")} (${detail?.turbine_count ?? 0})`,
            children: (
              <Card size="small">
                <Table<WindDataPrepTurbineRow>
                  rowKey="seq"
                  size="small"
                  loading={turbineQuery.isLoading}
                  columns={turbineColumns}
                  dataSource={turbineQuery.data?.items ?? []}
                  pagination={false}
                  scroll={{ x: 1500 }}
                />
              </Card>
            ),
          },
        ]
      : []),
    ...fileTabs,
  ];

  return (
    <>
      <div className="wind-detail-pane">
        <WindDetailHero
          icon={<DatabaseOutlined />}
          title={titleText}
          titleTooltip={titleText}
          subline={
            <WindDetailSubline
              items={[
                detail ? (
                  <span key="created">
                    {t("创建时间")} {formatDateTime(detail.create_date)}
                  </span>
                ) : null,
              ]}
            />
          }
          actions={
            <>
              <Button
                size="small"
                type="primary"
                icon={<CloudDownloadOutlined />}
                disabled={detail?.status !== "completed"}
                onClick={() => void downloadFileWithAuth(`${API_BASE}/${batchId}/package`, `${detail?.name || "wind-data-prep"}-five-files.zip`)}
              >
                {t("下载五文件 zip")}
              </Button>
              <WindDetailMoreActions
                label={t("更多")}
                items={[
                  ...(canManage
                    ? [{ key: "recompute", label: t("重跑"), icon: <ReloadOutlined />, onClick: handleRecompute }]
                    : []),
                  onClose
                    ? { key: "close", label: t("关闭"), icon: <CloseOutlined />, onClick: onClose }
                    : {
                        key: "back",
                        label: t("返回列表"),
                        icon: <ArrowLeftOutlined />,
                        onClick: () => router.push("/admin/wind-data-prep"),
                      },
                ]}
              />
            </>
          }
        />

        {detail?.status === "failed" && detail.error_message ? (
          <Alert
            className="wind-detail-alert"
            type="error"
            showIcon
            message={t("数据准备失败")}
            description={detail.error_message}
          />
        ) : null}

        <Tabs
          className="admin-atp-models-detail-tabs wind-detail-tabs"
          items={tabItems}
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key)}
        />

        <WindDetailPaginationFooter pagination={activePagination} />
      </div>
    </>
  );
}
