"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Modal,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  CloudDownloadOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { useI18n } from "@/lib/i18n";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import type {
  WindDataPrepBatchDetail,
  WindDataPrepTurbineListResponse,
  WindDataPrepTurbineRow,
} from "@/types/wind-data-prep";

const { Text, Paragraph } = Typography;
const API_BASE = "/api/v1/wind-data-prep";

const FILES = [
  { name: "file1", label: "file_1.txt（区域参数）" },
  { name: "file2", label: "file_2.txt（风机清单）" },
  { name: "file3", label: "file_3.txt（网格编号）" },
  { name: "file4", label: "file_4.txt（落雷次数 Nl）" },
  { name: "p0abc", label: "P0.abc（地形高程）" },
];

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

export default function WindDataPrepDetailPage() {
  const params = useParams<{ id: string }>();
  const batchId = params?.id ?? "";
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("wind_data_prep.manage");
  const [turbinePage, setTurbinePage] = useState(1);
  const [turbinePageSize, setTurbinePageSize] = useState(20);
  const [logOpen, setLogOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewText, setPreviewText] = useState("");

  const detailQuery = useQuery({
    queryKey: ["wind-data-prep", batchId],
    enabled: Boolean(user) && Boolean(batchId),
    queryFn: async () => getJson<WindDataPrepBatchDetail>(`${API_BASE}/${batchId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });
  const detail = detailQuery.data;

  const turbineQuery = useQuery({
    queryKey: ["wind-data-prep", batchId, "turbines", turbinePage, turbinePageSize],
    enabled: Boolean(user) && Boolean(batchId) && detail?.status === "completed",
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", String(turbinePageSize));
      query.set("offset", String((turbinePage - 1) * turbinePageSize));
      return getJson<WindDataPrepTurbineListResponse>(`${API_BASE}/${batchId}/turbines?${query.toString()}`);
    },
  });

  const handlePreview = useCallback(
    async (name: string, label: string) => {
      try {
        const response = await fetchWithAuth(`${API_BASE}/${batchId}/files/${name}?preview=1`);
        if (!response.ok) throw new Error(await readApiError(response));
        setPreviewTitle(`${t("预览")} · ${label}`);
        setPreviewText(await response.text());
        setPreviewOpen(true);
      } catch (error) {
        message.error((error as Error).message);
      }
    },
    [batchId, fetchWithAuth, message, t],
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

  const handleReport = useCallback(
    async (format: "json" | "excel") => {
      try {
        await downloadFileWithAuth(
          `${API_BASE}/${batchId}/report?format=${format}`,
          `${detail?.name || "wind-data-prep"}-report.${format === "json" ? "json" : "xlsx"}`,
        );
      } catch (error) {
        message.error((error as Error).message);
      }
    },
    [batchId, detail?.name, message],
  );

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
        render: (value: number, record) => <Text strong>{value}</Text>,
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

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <Card size="small">
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Space wrap>
            <Link href="/admin/wind-data-prep">{t("返回列表")}</Link>
            <Divider type="vertical" />
            <Text strong style={{ fontSize: 16 }}>
              {detail?.name || batchId}
            </Text>
            {detail?.status ? (
              <Tag color={{ pending: "default", processing: "processing", completed: "success", failed: "error" }[detail.status] ?? "default"}>
                {t({ pending: "待处理", processing: "处理中", completed: "已完成", failed: "失败" }[detail.status] ?? detail.status)}
              </Tag>
            ) : null}
          </Space>
          {detail && (detail.status === "pending" || detail.status === "processing") ? (
            <Progress percent={detail.progress} size="small" />
          ) : null}
          {detail?.status === "failed" && detail.error_message ? (
            <Alert type="error" showIcon message={t("数据准备失败")} description={detail.error_message} />
          ) : null}
          <Space wrap>
            <Button icon={<CloudDownloadOutlined />} type="primary" disabled={detail?.status !== "completed"} onClick={() => void downloadFileWithAuth(`${API_BASE}/${batchId}/package`, `${detail?.name || "wind-data-prep"}-five-files.zip`)}>
              {t("下载五文件 zip")}
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => void handleReport("json")} disabled={!detail?.has_report}>
              {t("校验报告 JSON")}
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => void handleReport("excel")} disabled={!detail?.has_report}>
              {t("校验报告 Excel")}
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => setLogOpen(true)} disabled={!detail?.task_id}>
              {t("运行日志")}
            </Button>
            {canManage ? (
              <Button icon={<ReloadOutlined />} onClick={handleRecompute}>
                {t("重跑")}
              </Button>
            ) : null}
          </Space>
        </Space>
      </Card>

      <Card size="small" title={t("参数卡")}>
        <Descriptions size="small" column={4} bordered>
          <Descriptions.Item label={t("风电场")}>{detail?.wind_farm_name || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("风机文件")}>{detail?.turbine_file_name || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("雷电文件")}>{detail?.lightning_file_name || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("地形文件")}>{detail?.terrain_file_name || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("起始经度")}>{formatNumber(detail?.start_lon, 6)}</Descriptions.Item>
          <Descriptions.Item label={t("起始纬度")}>{formatNumber(detail?.start_lat, 6)}</Descriptions.Item>
          <Descriptions.Item label={t("网格 nx × ny")}>{detail ? `${detail.grid_nx} × ${detail.grid_ny}` : "-"}</Descriptions.Item>
          <Descriptions.Item label={t("网格步长")}>{detail?.grid_step_deg ?? "-"}</Descriptions.Item>
          <Descriptions.Item label={t("风险基准 S")}>{formatNumber(detail?.risk_base_s, 4)}</Descriptions.Item>
          <Descriptions.Item label={t("统计年限")}>{t("固定 6 年")}</Descriptions.Item>
          <Descriptions.Item label={t("地形模式")}>{detail?.terrain_mode === "tif" ? t("上传 tif") : t("零高程")}</Descriptions.Item>
          <Descriptions.Item label={t("创建时间")}>{formatDateTime(detail?.create_date)}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Row gutter={[12, 12]}>
        {[
          { title: t("风机数"), value: detail?.turbine_count ?? 0 },
          { title: t("范围内落雷数"), value: detail?.lightning_in_scope ?? 0 },
          { title: t("非零网格数"), value: detail?.nonzero_cell_count ?? 0 },
          { title: t("零 Nl 风机数"), value: detail?.zero_nl_turbine_count ?? 0 },
          { title: t("Nl 最大"), value: formatNumber(detail?.nl_max, 4) },
          { title: t("Nl 最小"), value: formatNumber(detail?.nl_min, 4) },
          { title: t("Nl 均值"), value: formatNumber(detail?.nl_avg, 4) },
          { title: t("数据时间跨度"), value: (detail?.stats_json?.time_span as string) || "-" },
        ].map((item) => (
          <Col key={item.title} xs={24} sm={12} md={8} lg={6}>
            <Card size="small">
              <Statistic title={item.title} value={item.value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card size="small" title={t("五文件清单与校验状态")} extra={<Tag color={detail?.files_ready === 5 ? "success" : "warning"}>{detail?.files_ready ?? 0}/5</Tag>}>
        <Table
          rowKey="name"
          size="small"
          pagination={false}
          dataSource={FILES}
          columns={[
            { title: t("文件"), dataIndex: "label", key: "label" },
            {
              title: t("状态"),
              key: "status",
              width: 120,
              render: (_value, record) => (
                <Tag color={detail && detail.files_ready === 5 ? "success" : "processing"}>
                  {detail && detail.files_ready === 5 ? t("已生成") : t("生成中")}
                </Tag>
              ),
            },
            {
              title: t("操作"),
              key: "actions",
              width: 220,
              render: (_value, record) => (
                <Space size={4}>
                  <Button size="small" type="link" icon={<EyeOutlined />} disabled={detail?.status !== "completed"} onClick={() => void handlePreview(record.name, record.label)}>
                    {t("预览")}
                  </Button>
                  <Button size="small" type="link" icon={<DownloadOutlined />} disabled={detail?.status !== "completed"} onClick={() => void handleDownload(record.name, record.label)}>
                    {t("下载")}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
        {detail?.p0abc_header && Object.keys(detail.p0abc_header).length ? (
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            message={t("P0.abc 头部（6 个 uint16 大端数值）")}
            description={<Paragraph style={{ margin: 0 }}>{JSON.stringify(detail.p0abc_header)}</Paragraph>}
          />
        ) : null}
      </Card>

      <Card size="small" title={t("校验报告")}>
        {detail?.report_json?.checks?.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {detail.report_json.checks.map((check, index) => (
              <li key={`${check.code}-${index}`} style={{ marginBottom: 4 }}>
                <Tag color={check.passed ? (check.level === "warning" ? "orange" : check.level === "info" ? "blue" : "green") : "red"}>
                  {check.passed ? (check.level === "warning" ? t("警告") : t("通过")) : t("错误阻断")}
                </Tag>
                <Text strong>{t(check.label)}</Text>：{t(check.message)}
              </li>
            ))}
          </ul>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("任务完成后显示逐项校验结果")} />
        )}
      </Card>

      <Card size="small" title={t("风机明细（本格 vs 东邻格对照）")} extra={<Text type="secondary">{t("东邻格一列仅供解释修正前后差异，不作为验收基准")}</Text>}>
        <Table<WindDataPrepTurbineRow>
          rowKey="seq"
          size="small"
          loading={turbineQuery.isLoading}
          columns={turbineColumns}
          dataSource={turbineQuery.data?.items ?? []}
          pagination={false}
          scroll={{ x: 1500 }}
          footer={() => (
            <ModoPagination
              current={turbinePage}
              pageSize={turbinePageSize}
              total={turbineQuery.data?.total ?? 0}
              showSizeChanger
              pageSizeOptions={[20, 50, 100, 500]}
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

      <Modal title={previewTitle} open={previewOpen} onCancel={() => setPreviewOpen(false)} footer={null} width={720}>
        <pre style={{ maxHeight: 520, overflow: "auto", background: "#fafafa", padding: 12, whiteSpace: "pre-wrap" }}>
          {previewText}
        </pre>
      </Modal>

      <TaskLogViewerDrawer taskId={detail?.task_id ?? null} title={t("运行日志")} open={logOpen} onClose={() => setLogOpen(false)} />
    </div>
  );
}
