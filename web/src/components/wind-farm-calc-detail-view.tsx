"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  CloseOutlined,
  DownloadOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindFarmCalcJobDetail,
  WindFarmCalcLogInfo,
  WindFarmCalcResultListResponse,
  WindFarmCalcResultRow,
} from "@/types/wind-farm-calc";
import { RISK_COLORS, RISK_LABELS } from "@/types/wind-farm-calc";

const { Text, Paragraph } = Typography;
const API_BASE = "/api/v1/wind-farm-calc";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

const RISK_COUNT_KEYS: Record<number, keyof WindFarmCalcJobDetail> = {
  1: "risk_I_count",
  2: "risk_II_count",
  3: "risk_III_count",
  4: "risk_IV_count",
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0 ? `${hours}h ${minutes}m ${secs}s` : `${minutes}m ${secs}s`;
}

function formatNumber(value: number | null | undefined, digits = 5): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

/**
 * 风电场计算详情视图。
 * 独立路由页与列表页的动态详情标签共用此组件，避免复制详情页逻辑；
 * 顶部「引擎 MD5」等状态字段保持不变。
 */
export function WindFarmCalcDetailView({
  jobId,
  onClose,
}: {
  jobId: string;
  onClose?: () => void;
}) {
  const { message } = App.useApp();
  const { user, fetchWithAuth } = useAuth();
  const { t } = useI18n();

  const [riskFilter, setRiskFilter] = useState<number | undefined>();
  const [suggestionFilter, setSuggestionFilter] = useState<number | undefined>();
  const [sortBy, setSortBy] = useState("seq");
  const [order, setOrder] = useState("asc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [logOpen, setLogOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const [rawText, setRawText] = useState("");
  const [rawLoading, setRawLoading] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["wind-farm-calc", "detail", jobId],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: () => getJson<WindFarmCalcJobDetail>(`${API_BASE}/${jobId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "processing" || status === "pending" ? 4000 : false;
    },
  });

  const logQuery = useQuery({
    queryKey: ["wind-farm-calc", "log", jobId],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: () => getJson<WindFarmCalcLogInfo>(`${API_BASE}/${jobId}/log`),
  });

  const resultsQuery = useQuery({
    queryKey: ["wind-farm-calc", "results", jobId, riskFilter, suggestionFilter, sortBy, order, page, pageSize],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", String(pageSize));
      query.set("offset", String((page - 1) * pageSize));
      query.set("sort_by", sortBy);
      query.set("order", order);
      if (riskFilter) query.set("risk_level", String(riskFilter));
      if (suggestionFilter) query.set("suggestion_code", String(suggestionFilter));
      return getJson<WindFarmCalcResultListResponse>(`${API_BASE}/${jobId}/results?${query.toString()}`);
    },
  });

  const detail = detailQuery.data;
  const statusMeta = STATUS_META[detail?.status ?? "pending"] ?? STATUS_META.pending;

  const showRaw = useCallback(async () => {
    setRawLoading(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/${jobId}/output?preview=true`);
      if (!response.ok) throw new Error(await readApiError(response));
      setRawText(await response.text());
      setRawOpen(true);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setRawLoading(false);
    }
  }, [fetchWithAuth, jobId, message]);

  const topRiskQuery = useQuery({
    queryKey: ["wind-farm-calc", "top-risk", jobId],
    enabled: Boolean(user) && Boolean(jobId) && detail?.status === "completed",
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", "5");
      query.set("sort_by", "value_v");
      query.set("order", "desc");
      return getJson<WindFarmCalcResultListResponse>(`${API_BASE}/${jobId}/results?${query.toString()}`);
    },
  });

  const resultColumns = useMemo<TableColumnsType<WindFarmCalcResultRow>>(
    () => [
      { title: t("序号"), dataIndex: "seq", key: "seq", width: 70, sorter: true },
      { title: t("风机编号"), dataIndex: "turbine_no", key: "turbine_no", width: 120, render: (v: string | null) => v || "-" },
      {
        title: t("经纬度"),
        key: "lonlat",
        width: 190,
        render: (_value, row) => `${formatNumber(row.lon, 4)}, ${formatNumber(row.lat, 4)}`,
      },
      {
        title: t("计算值 V"),
        dataIndex: "value_v",
        key: "value_v",
        width: 120,
        render: (v: number) => <Text strong>{formatNumber(v, 5)}</Text>,
        sorter: true,
      },
      {
        title: t("风险等级"),
        dataIndex: "risk_level",
        key: "risk_level",
        width: 110,
        render: (level: number) => <Tag color={RISK_COLORS[level]}>{RISK_LABELS[level] || level}</Tag>,
        sorter: true,
      },
      { title: t("停运建议"), dataIndex: "suggestion_text", key: "suggestion_text", width: 130 },
      { title: t("回路号"), dataIndex: "circuit_no", key: "circuit_no", width: 90, render: (v: number | null) => v ?? "-" },
    ],
    [t],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col" style={{ gap: 12, paddingBottom: 24 }}>
      <div>
        {onClose ? (
          <Button type="link" icon={<CloseOutlined />} onClick={onClose} style={{ paddingLeft: 0 }}>
            {t("关闭")}
          </Button>
        ) : (
          <Link href="/admin/wind-farm-calc">{t("返回列表")}</Link>
        )}
      </div>

      <Card size="small" title={t("状态卡")} extra={<Button icon={<ReloadOutlined />} size="small" onClick={() => void detailQuery.refetch()}>{t("刷新")}</Button>}>
        <Descriptions column={3} size="small" bordered>
          <Descriptions.Item label={t("任务名称")}>{detail?.name || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("状态")}>
            <Space direction="vertical" size={2}>
              <Tag color={statusMeta.color}>{t(statusMeta.label)}</Tag>
              {(detail?.status === "processing" || detail?.status === "pending") ? (
                <Progress percent={detail?.progress ?? 0} size="small" />
              ) : null}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label={t("阶段")}>{detail?.stage || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("风机数")}>{detail?.turbine_count ?? 0}</Descriptions.Item>
          <Descriptions.Item label={t("耗时")}>{formatDuration(detail?.duration_seconds)}</Descriptions.Item>
          <Descriptions.Item label={t("任务 ID")}>{detail?.task_id || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("开始时间")}>{formatDateTime(detail?.started_at)}</Descriptions.Item>
          <Descriptions.Item label={t("结束时间")}>{formatDateTime(detail?.finished_at)}</Descriptions.Item>
          <Descriptions.Item label={t("引擎 MD5")}>{detail?.engine_md5 || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("来源批次")} span={3}>{detail?.prep_batch_id || "-"}</Descriptions.Item>
          {detail?.error_message ? (
            <Descriptions.Item label={t("失败原因")} span={3}>
              <Text type="danger">{detail.error_message}</Text>
            </Descriptions.Item>
          ) : null}
        </Descriptions>
      </Card>

      {detail?.status === "completed" ? (
        <Card size="small" title={t("统计卡")}>
          <Row gutter={[12, 12]}>
            {[1, 2, 3, 4].map((level) => (
              <Col key={level} xs={12} sm={6} md={4}>
                <Card size="small">
                  <Statistic
                    title={`${t("风险")} ${RISK_LABELS[level]}`}
                    value={(detail[RISK_COUNT_KEYS[level]] as number) ?? 0}
                    valueStyle={{ color: RISK_COLORS[level] === "red" ? "#cf1322" : undefined }}
                  />
                </Card>
              </Col>
            ))}
            <Col xs={12} sm={6} md={4}>
              <Card size="small">
                <Statistic title={t("需停运")} value={detail.shutdown_count ?? 0} />
              </Card>
            </Col>
            <Col xs={12} sm={6} md={4}>
              <Card size="small">
                <Statistic title={t("集电线停运")} value={detail.circuit_shutdown_count ?? 0} />
              </Card>
            </Col>
            <Col xs={12} sm={6} md={4}>
              <Card size="small">
                <Statistic title={t("全场停运")} value={detail.farm_shutdown_count ?? 0} />
              </Card>
            </Col>
          </Row>
          {topRiskQuery.data?.items?.length ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message={t("风险最高的风机")}
              description={topRiskQuery.data.items
                .map((row) => `${row.turbine_no || `#${row.seq}`}  V=${formatNumber(row.value_v, 5)}  风险 ${RISK_LABELS[row.risk_level]}`)
                .join("；")}
            />
          ) : null}
          {detail.risk_mismatch_count > 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message={t("GBK 风险列与后端重算不一致")}
              description={t("以后端按 V 与 S 重算的风险等级为准，GBK 原文保留在结果表 raw_line 列。")}
            />
          ) : null}
        </Card>
      ) : null}

      <Card
        size="small"
        title={t("逐台结果")}
        extra={
          <Space>
            <Button size="small" icon={<FileTextOutlined />} loading={rawLoading} onClick={() => void showRaw()}>
              {t("原始输出预览")}
            </Button>
            <Button
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => void downloadFileWithAuth(`${API_BASE}/${jobId}/output`, "file_out.txt")}
            >
              {t("下载 file_out.txt")}
            </Button>
            {detail?.status === "completed" ? (
              <Button
                size="small"
                type="primary"
                icon={<DownloadOutlined />}
                onClick={() => void downloadFileWithAuth(`${API_BASE}/${jobId}/export`, `${detail.name || "wind-farm-calc"}-results.xlsx`)}
              >
                {t("导出 Excel")}
              </Button>
            ) : null}
            <Button size="small" onClick={() => setLogOpen(true)}>{t("运行日志")}</Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <span>{t("风险等级")}:</span>
          <Select
            allowClear
            style={{ width: 120 }}
            placeholder={t("全部")}
            value={riskFilter}
            onChange={(v) => { setRiskFilter(v); setPage(1); }}
            options={[1, 2, 3, 4].map((level) => ({ value: level, label: `${t("风险")} ${RISK_LABELS[level]}` }))}
          />
          <span>{t("停运建议")}:</span>
          <Select
            allowClear
            style={{ width: 140 }}
            placeholder={t("全部")}
            value={suggestionFilter}
            onChange={(v) => { setSuggestionFilter(v); setPage(1); }}
            options={[
              { value: 1, label: t("无") },
              { value: 2, label: t("停运") },
              { value: 3, label: t("停运(集电线)") },
              { value: 4, label: t("停运(风电场)") },
            ]}
          />
        </Space>
        <Table<WindFarmCalcResultRow>
          rowKey="seq"
          size="small"
          loading={resultsQuery.isLoading}
          columns={resultColumns}
          dataSource={resultsQuery.data?.items ?? []}
          pagination={false}
          scroll={{ x: 900 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无结果")} /> }}
          onChange={(_pagination, _filters, sorter) => {
            const s = Array.isArray(sorter) ? sorter[0] : sorter;
            if (!s || !s.columnKey) return;
            setSortBy(String(s.columnKey));
            setOrder(s.order === "descend" ? "desc" : "asc");
            setPage(1);
          }}
          footer={() => (
            <ModoPagination
              current={page}
              pageSize={pageSize}
              total={resultsQuery.data?.total ?? 0}
              showSizeChanger
              pageSizeOptions={[20, 50, 100]}
              onChange={(nextPage, nextSize) => {
                setPage(nextPage);
                if (nextSize && nextSize !== pageSize) {
                  setPageSize(nextSize);
                  setPage(1);
                }
              }}
              style={{ marginTop: 0 }}
            />
          )}
        />
      </Card>

      {detail?.preflight_json ? (
        <Card size="small" title={t("预检结果")}>
          <Paragraph style={{ marginBottom: 4 }}>
            {t("结果行数")}: {detail.preflight_json.grid_rows ?? "-"} · {t("网格")}:{" "}
            {detail.preflight_json.params?.nx}×{detail.preflight_json.params?.ny} · S: {detail.preflight_json.params?.s}
          </Paragraph>
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            {(detail.preflight_json.checks ?? []).map((check) => (
              <div key={check.code}>
                <Tag color={check.passed ? "green" : "red"}>{check.passed ? t("通过") : t("失败")}</Tag>
                {t(check.label)}：{t(check.message)}
              </div>
            ))}
          </Space>
        </Card>
      ) : null}

      <TaskLogViewerDrawer taskId={logQuery.data?.task_id ?? detail?.task_id ?? null} title={t("运行日志")} open={logOpen} onClose={() => setLogOpen(false)} />

      <Modal
        title={t("原始 file_out.txt 预览（GBK 已转 UTF-8）")}
        width={800}
        open={rawOpen}
        onCancel={() => setRawOpen(false)}
        footer={<Button onClick={() => setRawOpen(false)}>{t("关闭")}</Button>}
      >
        <pre style={{ maxHeight: 500, overflow: "auto", fontSize: 12 }}>{rawText || t("(空)")}</pre>
      </Modal>
    </div>
  );
}
