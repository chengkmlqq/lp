"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
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
  Tooltip,
  Typography,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  DatabaseOutlined,
  DownloadOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import {
  WindDetailHero,
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

// file_1 / file_4 / P0.abc 的内容已并入概览，仅剩两个产物 Tab（file_2 / file_3）。
const FILES = [
  { name: "file2", label: "风机清单" },
  { name: "file3", label: "网格编号" },
];

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

/** 与 file_1.txt 的序列化口径一致：保留指定精度但去掉末尾多余的 0。 */
function formatFile1Number(value: number | null | undefined, digits = 6): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits).replace(/\.?0+$/, "") || "0";
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ── 产物文件文本解析（与后端 file_2 / file_3 / file_4 序列化口径一致） ──

type File2Row = {
  seq: number;
  turbine_no: string;
  lon_d: string;
  lon_m: string;
  lon_s: string;
  lat_d: string;
  lat_m: string;
  lat_s: string;
  input_elev: string;
  height: string;
  blade: string;
  motion: string;
  circuit: string;
};

/** file_2.txt：每行 11 列（经度 度/分/秒、纬度 度/分/秒、输入高程、风机高度、叶片长度、动静状态、回路号）。 */
function parseFile2(text: string, turbineNos: string[]): File2Row[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const c = line.split(/\s+/);
      return {
        seq: index + 1,
        turbine_no: turbineNos[index] || "-",
        lon_d: c[0] ?? "-",
        lon_m: c[1] ?? "-",
        lon_s: c[2] ?? "-",
        lat_d: c[3] ?? "-",
        lat_m: c[4] ?? "-",
        lat_s: c[5] ?? "-",
        input_elev: c[6] ?? "-",
        height: c[7] ?? "-",
        blade: c[8] ?? "-",
        motion: c[9] ?? "-",
        circuit: c[10] ?? "-",
      };
    });
}

type File3Row = {
  seq: number;
  grid_id: string;
  polarity: string;
  p1: string;
  p2: string;
  p3: string;
  p4: string;
  p5: string;
  p6: string;
};

/** file_3.txt：网格编号 + 极性标志 + 6 个雷电流概率参数，共 8 列。 */
function parseFile3(text: string): File3Row[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const c = line.split(/\s+/);
      return {
        seq: index + 1,
        grid_id: c[0] ?? "-",
        polarity: c[1] ?? "-",
        p1: c[2] ?? "-",
        p2: c[3] ?? "-",
        p3: c[4] ?? "-",
        p4: c[5] ?? "-",
        p5: c[6] ?? "-",
        p6: c[7] ?? "-",
      };
    });
}

type File4Row = {
  seq: number;
  nl: string;
  turbine_no: string;
};

/** file_4.txt：每行一个 Nl，按行序对应风机。 */
function parseFile4(text: string, turbineNos: string[]): File4Row[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => ({
      seq: index + 1,
      nl: line,
      turbine_no: turbineNos[index] || "-",
    }));
}

/** 按需（Tab 激活且任务完成后）用 preview=1 接口取纯文本。 */
function useFileText(batchId: string, name: string, enabled: boolean) {
  const { user, fetchWithAuth } = useAuth();
  return useQuery({
    queryKey: ["wind-data-prep-file-content", batchId, name],
    enabled: enabled && Boolean(user),
    queryFn: async () => {
      const response = await fetchWithAuth(`${API_BASE}/${batchId}/files/${name}?preview=1`);
      if (!response.ok) throw new Error(await readApiError(response));
      return response.text();
    },
  });
}

/** 产物表格 Tab 共用的加载 / 错误 / 未完成外壳。 */
function FileQueryBoundary({
  query,
  enabled,
  children,
}: {
  query: UseQueryResult<string>;
  enabled: boolean;
  children: (text: string) => ReactNode;
}) {
  const { t } = useI18n();
  if (!enabled) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("任务完成后显示文件内容")} />
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
  return <>{children(query.data || "")}</>;
}

/** file_2 风机清单：11 列拆分成结构化表格（经纬度各自展开为 度/分/秒）。 */
function File2Table({
  batchId,
  enabled,
  turbineNos,
}: {
  batchId: string;
  enabled: boolean;
  turbineNos: string[];
}) {
  const { t } = useI18n();
  const query = useFileText(batchId, "file2", enabled);
  const columns = useMemo<TableColumnsType<File2Row>>(
    () => [
      {
        title: columnTitle(t("风机编号"), t("风机点位文件中的顺序编号")),
        dataIndex: "turbine_no",
        key: "turbine_no",
        width: 100,
      },
      {
        title: columnTitle(t("经度"), t("风机经度的度/分/秒，来自风机点位文件")),
        key: "lon",
        children: [
          { title: columnTitle(t("度"), t("经度的度部分")), dataIndex: "lon_d", key: "lon_d", width: 64 },
          { title: columnTitle(t("分"), t("经度的分部分")), dataIndex: "lon_m", key: "lon_m", width: 64 },
          { title: columnTitle(t("秒"), t("经度的秒部分")), dataIndex: "lon_s", key: "lon_s", width: 72 },
        ],
      },
      {
        title: columnTitle(t("纬度"), t("风机纬度的度/分/秒，来自风机点位文件")),
        key: "lat",
        children: [
          { title: columnTitle(t("度"), t("纬度的度部分")), dataIndex: "lat_d", key: "lat_d", width: 64 },
          { title: columnTitle(t("分"), t("纬度的分部分")), dataIndex: "lat_m", key: "lat_m", width: 64 },
          { title: columnTitle(t("秒"), t("纬度的秒部分")), dataIndex: "lat_s", key: "lat_s", width: 72 },
        ],
      },
      {
        title: columnTitle(t("输入高程"), t("风机点位文件提供的地面高程（米），生成 P0.abc 时由地形高程覆盖")),
        dataIndex: "input_elev",
        key: "input_elev",
        width: 90,
      },
      {
        title: columnTitle(t("风机高度"), t("风机轮毂高度（米）")),
        dataIndex: "height",
        key: "height",
        width: 90,
      },
      {
        title: columnTitle(t("叶片长度"), t("风机叶片长度（米）")),
        dataIndex: "blade",
        key: "blade",
        width: 90,
      },
      {
        title: columnTitle(t("动静状态"), t("风机动/静状态标识，来自风机点位文件")),
        dataIndex: "motion",
        key: "motion",
        width: 90,
      },
      {
        title: columnTitle(t("回路号"), t("风机所属回路编号，核心程序据此索引回路参数")),
        dataIndex: "circuit",
        key: "circuit",
        width: 80,
      },
    ],
    [t],
  );
  return (
    <FileQueryBoundary query={query} enabled={enabled}>
      {(text) => (
        <Table<File2Row>
          rowKey="seq"
          size="small"
          columns={columns}
          dataSource={parseFile2(text, turbineNos)}
          sticky
          pagination={false}
          scroll={{ x: 980, y: "55vh" }}
        />
      )}
    </FileQueryBoundary>
  );
}

/** file_3 网格编号：网格编号 + 极性标志 + 6 个雷电流概率参数（共 8 列）。 */
function File3Table({ batchId, enabled }: { batchId: string; enabled: boolean }) {
  const { t } = useI18n();
  const query = useFileText(batchId, "file3", enabled);
  const columns = useMemo<TableColumnsType<File3Row>>(
    () => [
      {
        title: columnTitle(t("网格编号"), t("风机所在网格的编号，由行列号按核心程序口径生成")),
        dataIndex: "grid_id",
        key: "grid_id",
        width: 110,
      },
      {
        title: columnTitle(t("极性标志"), t("雷电流极性标志，来自 file_3 固定序列化口径")),
        dataIndex: "polarity",
        key: "polarity",
        width: 100,
      },
      {
        title: columnTitle(t("雷电流概率参数"), t("核心程序使用的 6 个雷电流概率参数，按顺序写入 file_3")),
        key: "prob",
        children: [1, 2, 3, 4, 5, 6].map((i) => ({
          title: columnTitle(`${t("概率")} ${i}`, t(`第 ${i} 个雷电流概率参数，来自 file_3 固定序列化口径`)),
          dataIndex: `p${i}` as keyof File3Row,
          key: `p${i}`,
          width: 90,
        })),
      },
    ],
    [t],
  );
  return (
    <FileQueryBoundary query={query} enabled={enabled}>
      {(text) => (
        <Table<File3Row>
          rowKey="seq"
          size="small"
          columns={columns}
          dataSource={parseFile3(text)}
          sticky
          pagination={false}
          scroll={{ x: 850, y: "55vh" }}
        />
      )}
    </FileQueryBoundary>
  );
}

/** file_4 落雷次数：概览内的紧凑表格，行多时内部滚动。 */
function File4Table({
  batchId,
  enabled,
  turbineNos,
}: {
  batchId: string;
  enabled: boolean;
  turbineNos: string[];
}) {
  const { t } = useI18n();
  const query = useFileText(batchId, "file4", enabled);
  const columns = useMemo<TableColumnsType<File4Row>>(
    () => [
      { title: t("序号"), dataIndex: "seq", key: "seq", width: 64 },
      { title: "Nl", dataIndex: "nl", key: "nl", width: 120 },
      { title: t("对应风机编号"), dataIndex: "turbine_no", key: "turbine_no", width: 130 },
    ],
    [t],
  );
  return (
    <FileQueryBoundary query={query} enabled={enabled}>
      {(text) => (
        <Table<File4Row>
          rowKey="seq"
          size="small"
          columns={columns}
          dataSource={parseFile4(text, turbineNos)}
          pagination={false}
          scroll={{ y: 200 }}
        />
      )}
    </FileQueryBoundary>
  );
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
export function WindDataPrepDetailView(props: {
  batchId: string;
  onClose?: () => void;
}) {
  const { batchId } = props;
  const { t } = useI18n();
  const { message } = App.useApp();
  const { user, initializing } = useAuth();
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
  const completed = detail?.status === "completed";

  const turbineQuery = useQuery({
    queryKey: ["wind-data-prep-detail", batchId, "turbines", turbinePage, turbinePageSize],
    enabled: Boolean(user) && Boolean(batchId) && completed,
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", String(turbinePageSize));
      query.set("offset", String((turbinePage - 1) * turbinePageSize));
      return getJson<WindDataPrepTurbineListResponse>(`${API_BASE}/${batchId}/turbines?${query.toString()}`);
    },
  });

  // 概览 file_4 与 file_2 表格需要按行序对应风机编号，取一页上限内的全部风机。
  const allTurbinesQuery = useQuery({
    queryKey: ["wind-data-prep-detail", batchId, "turbines", "all"],
    enabled: Boolean(user) && Boolean(batchId) && completed,
    queryFn: () => getJson<WindDataPrepTurbineListResponse>(`${API_BASE}/${batchId}/turbines?limit=500`),
  });
  const turbineNos = useMemo(
    () => (allTurbinesQuery.data?.items ?? []).map((row) => row.turbine_no || "-"),
    [allTurbinesQuery.data],
  );

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

  const turbineColumns = useMemo<TableColumnsType<WindDataPrepTurbineRow>>(
    () => [
      {
        title: columnTitle(t("风机编号"), t("风机点位文件中的顺序编号")),
        dataIndex: "turbine_no",
        key: "turbine_no",
        width: 100,
      },
      {
        title: columnTitle(t("经纬度"), t("风机经度、纬度坐标（十进制度），经度在前、纬度在后")),
        key: "coord",
        width: 180,
        render: (_value, record) => `${formatNumber(record.lon, 6)}, ${formatNumber(record.lat, 6)}`,
      },
      {
        title: columnTitle(t("风机网格列号"), t("风机所在网格的列号（经度方向，从 1 起）")),
        dataIndex: "cell_i",
        key: "cell_i",
        width: 80,
      },
      {
        title: columnTitle(t("风机网格行号"), t("风机所在网格的行号（纬度方向，从 1 起）")),
        dataIndex: "cell_j",
        key: "cell_j",
        width: 80,
      },
      {
        title: columnTitle(t("风机网格编号"), t("风机所在网格的编号，由行列号按核心程序口径生成")),
        dataIndex: "grid_id",
        key: "grid_id",
        width: 90,
      },
      {
        title: columnTitle(t("本格落雷"), t("统计年限内落入风机所在网格的有效雷电定位记录条数")),
        dataIndex: "flash_count",
        key: "flash_count",
        width: 100,
        render: (value: number) => <Text strong>{value}</Text>,
      },
      {
        title: columnTitle(t("东邻格（错位对照）"), t("风机所在网格东侧相邻网格的落雷次数，用于错位对照；与本格相同显示灰色，不同显示橙色")),
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
        title: columnTitle(t("Nl（次/(格·年)）"), t("本格落雷次数除以统计年限（6 年），即每年每格的平均落雷次数")),
        dataIndex: "nl",
        key: "nl",
        width: 130,
        render: (value: number) => formatNumber(value, 6),
      },
      {
        title: columnTitle(t("风机高度"), t("风机轮毂高度，单位米")),
        dataIndex: "height",
        key: "height",
        width: 100,
        render: (v: number | null) => formatNumber(v, 2),
      },
      {
        title: columnTitle(t("叶片长度"), t("风机叶片长度，单位米")),
        dataIndex: "blade",
        key: "blade",
        width: 100,
        render: (v: number | null) => formatNumber(v, 2),
      },
      {
        title: columnTitle(t("动静状态"), t("风机动/静状态标识，来自风机点位文件")),
        dataIndex: "motion",
        key: "motion",
        width: 90,
      },
      {
        title: columnTitle(t("回路号"), t("风机所属回路编号，核心程序据此索引回路参数")),
        dataIndex: "circuit",
        key: "circuit",
        width: 80,
      },
    ],
    [t],
  );

  if (initializing) return null;

  const titleText = detail?.name || batchId;
  // 概览第一块：非区域参数的基本信息（区域参数已移入第二块）。
  const basicMetaItems: WindDetailMetaItem[] = [
    { label: t("风电场"), value: detail?.wind_farm_name || "-" },
    { label: t("风机文件"), value: detail?.turbine_file_name || "-" },
    { label: t("雷电文件"), value: detail?.lightning_file_name || "-" },
    { label: t("地形文件"), value: detail?.terrain_file_name || "-" },
    { label: t("网格步长"), value: detail?.grid_step_deg ?? "-" },
    { label: t("统计年限"), value: t("固定 6 年") },
    { label: t("地形模式"), value: detail?.terrain_mode === "tif" ? t("上传 tif") : t("零高程") },
    { label: t("五文件齐全度"), value: detail ? `${detail.files_ready ?? 0}/5` : "-" },
  ];

  // 概览第二块：把 file_1.txt 的 6 个数值「翻译」成带中文标签的 key-value。
  const regionMetaItems: WindDetailMetaItem[] = [
    { label: t("风机数 N"), value: detail?.turbine_count ?? 0 },
    { label: t("风险基准 S"), value: formatFile1Number(detail?.risk_base_s, 10) },
    { label: t("起始经度"), value: formatFile1Number(detail?.start_lon, 6) },
    { label: t("起始纬度"), value: formatFile1Number(detail?.start_lat, 6) },
    { label: t("经向网格数 nx"), value: detail?.grid_nx ?? "-" },
    { label: t("纬向网格数 ny"), value: detail?.grid_ny ?? "-" },
  ];

  // 关键指标：8 项以表格形式放进「概览」Tab 的「统计结果 / 关键指标」区块。
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

  // 剩余两个产物各占一个 Tab，排在「概览」「风机明细」之后；P0.abc 已并入概览。
  const fileTabs = FILES.map((file) => ({
    key: `file-${file.name}`,
    label: t(file.label),
    children: (
      <div className="wind-detail-tab-content wind-data-prep-table-tab-card">
        {file.name === "file2" ? (
          <File2Table
            batchId={batchId}
            enabled={completed && activeTab === "file-file2"}
            turbineNos={turbineNos}
          />
        ) : (
          <File3Table batchId={batchId} enabled={completed && activeTab === "file-file3"} />
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
          {detail ? (
            <>
              <section className="fl-create-form-block">
                <div className="fl-create-form-block-title">{t("基本信息 / 数据来源")}</div>
                <Descriptions bordered size="small" column={2}>
                  {basicMetaItems.map((item, index) => (
                    <Descriptions.Item key={index} label={item.label}>
                      {item.value ?? "-"}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </section>
              <section className="fl-create-form-block">
                <div className="fl-create-form-block-title">{t("区域参数（来自 file_1）")}</div>
                <Descriptions bordered size="small" column={2}>
                  {regionMetaItems.map((item, index) => (
                    <Descriptions.Item key={index} label={item.label}>
                      {item.value ?? "-"}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </section>
              <section className="fl-create-form-block">
                <div className="fl-create-form-block-title">{t("统计结果 / 关键指标")}</div>
                <Descriptions bordered size="small" column={2}>
                  {metricItems.map((item, index) => (
                    <Descriptions.Item key={index} label={item.label}>
                      {item.value ?? "-"}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </section>
            </>
          ) : null}
          <section className="fl-create-form-block">
            <div className="fl-create-form-block-title">{t("落雷次数（来自 file_4）")}</div>
            <File4Table batchId={batchId} enabled={completed} turbineNos={turbineNos} />
          </section>
          <section className="fl-create-form-block">
            <div
              className="fl-create-form-block-title"
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
            >
              <span>{t("P0.abc 头部（地形高程）")}</span>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                disabled={!completed}
                onClick={() => void handleDownload("p0abc", "P0.abc（地形高程）")}
              >
                {t("下载")}
              </Button>
            </div>
            <P0abcHeaderView header={detail?.p0abc_header} />
          </section>
        </div>
      ),
    },
    ...(completed
      ? [
          {
            key: "turbines",
            label: t("风机明细"),
            children: (
              <Card size="small" className="wind-data-prep-table-tab-card">
                <Table<WindDataPrepTurbineRow>
                  rowKey="seq"
                  size="small"
                  loading={turbineQuery.isLoading}
                  columns={turbineColumns}
                  dataSource={turbineQuery.data?.items ?? []}
                  sticky
                  pagination={false}
                  scroll={{ x: 1500, y: "55vh" }}
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
          className="admin-atp-models-detail-tabs wind-detail-tabs wind-data-prep-detail-tabs"
          items={tabItems}
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key)}
        />

        <WindDetailPaginationFooter pagination={activePagination} />
      </div>
    </>
  );
}
