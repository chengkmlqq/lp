"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Empty,
  Progress,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  type TableColumnsType,
  type TabsProps,
} from "antd";
import {
  CalculatorOutlined,
  DownloadOutlined,
  QuestionCircleOutlined,
  ReloadOutlined,
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
import { downloadFileWithAuth, getJson } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindFarmCalcJobDetail,
  WindFarmCalcResultListResponse,
  WindFarmCalcResultRow,
} from "@/types/wind-farm-calc";
import { RISK_COLORS, RISK_LABELS } from "@/types/wind-farm-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-farm-calc";
// 排序固定为后端默认值；前端表格不再提供排序入口。
const RESULT_SORT_BY = "seq";
const RESULT_ORDER = "asc";

const RISK_COUNT_KEYS: Record<number, keyof WindFarmCalcJobDetail> = {
  1: "risk_I_count",
  2: "risk_II_count",
  3: "risk_III_count",
  4: "risk_IV_count",
};

/** 表头显式渲染灰色问号图标，悬浮显示解释文案；与地闪密度详情页表格范式一致。 */
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
}: {
  jobId: string;
  // 保留 prop 以兼容列表页 Tab 调用；关闭入口已随「更多」菜单一并移除。
  onClose?: () => void;
}) {
  const { user } = useAuth();
  const { t } = useI18n();

  const [activeTab, setActiveTab] = useState("overview");
  const [riskFilter, setRiskFilter] = useState<number | undefined>();
  const [suggestionFilter, setSuggestionFilter] = useState<number | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const detailQuery = useQuery({
    queryKey: ["wind-farm-calc", "detail", jobId],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: () => getJson<WindFarmCalcJobDetail>(`${API_BASE}/${jobId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "processing" || status === "pending" ? 4000 : false;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ["wind-farm-calc", "results", jobId, riskFilter, suggestionFilter, RESULT_SORT_BY, RESULT_ORDER, page, pageSize],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: async () => {
      const query = new URLSearchParams();
      query.set("limit", String(pageSize));
      query.set("offset", String((page - 1) * pageSize));
      query.set("sort_by", RESULT_SORT_BY);
      query.set("order", RESULT_ORDER);
      if (riskFilter) query.set("risk_level", String(riskFilter));
      if (suggestionFilter) query.set("suggestion_code", String(suggestionFilter));
      return getJson<WindFarmCalcResultListResponse>(`${API_BASE}/${jobId}/results?${query.toString()}`);
    },
  });

  const detail = detailQuery.data;

  const resultColumns = useMemo<TableColumnsType<WindFarmCalcResultRow>>(
    () => [
      {
        title: columnTitle(t("风机编号"), t("风机点位文件中的顺序编号，用于标识每台风机")),
        dataIndex: "turbine_no",
        key: "turbine_no",
        width: 130,
        render: (v: string | null) => v || "-",
      },
      {
        title: columnTitle(t("经纬度"), t("风机所在位置的经度与纬度，十进制度；经度在前、纬度在后")),
        key: "lonlat",
        width: 190,
        render: (_value, row) => `${formatNumber(row.lon, 4)}, ${formatNumber(row.lat, 4)}`,
      },
      {
        title: columnTitle(t("计算值 V"), t("后端按规程重算得到的风险判定值 V，与 S 共同参与风险等级判定")),
        dataIndex: "value_v",
        key: "value_v",
        width: 130,
        render: (v: number) => <Text strong>{formatNumber(v, 5)}</Text>,
      },
      {
        title: columnTitle(t("风险等级"), t("后端依据计算值 V 与 S 重算得到的风险等级（I~IV），以服务端结果为准；与 GBK 原文的差异见概览提示")),
        dataIndex: "risk_level",
        key: "risk_level",
        width: 110,
        render: (level: number) => <Tag color={RISK_COLORS[level]}>{RISK_LABELS[level] || level}</Tag>,
      },
      {
        title: columnTitle(t("停运建议"), t("依据该风机风险等级给出的处置建议：无 / 停运 / 集电线停运 / 风电场停运")),
        dataIndex: "suggestion_text",
        key: "suggestion_text",
        width: 150,
      },
      {
        title: columnTitle(t("回路号"), t("该风机所在的集电回路编号；为空表示未分配回路")),
        dataIndex: "circuit_no",
        key: "circuit_no",
        width: 100,
        render: (v: number | null) => v ?? "-",
      },
    ],
    [t],
  );

  const titleText = detail?.name || jobId;
  // 任务名称已在 Hero；开始/结束时间已在副行，属性网格只留真正的基本属性。
  const metaItems: WindDetailMetaItem[] = [
    { label: t("阶段"), value: detail?.stage || "-" },
    { label: t("风机数"), value: detail?.turbine_count ?? 0 },
    { label: t("耗时"), value: formatDuration(detail?.duration_seconds) },
    { label: t("集电线停运"), value: detail?.circuit_shutdown_count ?? 0 },
    { label: t("引擎 MD5"), value: detail?.engine_md5 || "-" },
    { label: t("来源批次"), span: 2, value: detail?.prep_batch_id || "-" },
    ...(detail?.error_message
      ? [{ label: t("失败原因"), span: 2 as const, value: <Text type="danger">{detail.error_message}</Text> }]
      : []),
  ];

  const completed = detail?.status === "completed";

  // 关键指标条：风险 I~IV + 需停运 + 全场停运，6 项一组无孤项；
  // 全部放进「概览」Tab，顶部不再常驻。
  const metricItems: WindDetailMetricItem[] = [
    ...[1, 2, 3, 4].map((level) => ({
      label: `${t("风险")} ${RISK_LABELS[level]}`,
      value: (detail?.[RISK_COUNT_KEYS[level]] as number) ?? 0,
      tone: (RISK_COLORS[level] === "red" ? "danger" : undefined) as WindDetailMetricItem["tone"],
    })),
    { label: t("需停运"), value: detail?.shutdown_count ?? 0 },
    { label: t("全场停运"), value: detail?.farm_shutdown_count ?? 0 },
  ];

  // 分页底栏由当前激活 Tab 驱动，仅逐台结果 Tab 需要分页。
  const activePagination: WindDetailPaginationConfig | null =
    activeTab === "results"
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
          {detail ? <WindDetailMetricStrip items={metricItems} /> : null}
          {detail ? (
            <Card size="small" title={t("基本信息")}>
              <WindDetailMeta items={metaItems} />
            </Card>
          ) : null}
        </div>
      ),
    },
    {
      key: "results",
      label: t("逐台结果"),
      children: (
        <Card size="small">
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
            rowKey={(record) => String(record.seq)}
            size="small"
            loading={resultsQuery.isLoading}
            columns={resultColumns}
            dataSource={resultsQuery.data?.items ?? []}
            pagination={false}
            sticky
            scroll={{ x: 820, y: "calc(100vh - 400px)" }}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无结果")} /> }}
          />
        </Card>
      ),
    },
  ];

  return (
    <div className="wind-detail-pane">
      <WindDetailHero
        icon={<CalculatorOutlined />}
        title={titleText}
        titleTooltip={titleText}
        subline={
          <WindDetailSubline
            items={[
              <span key="start">{t("开始时间")} {formatDateTime(detail?.started_at)}</span>,
              <span key="finish">{t("结束时间")} {formatDateTime(detail?.finished_at)}</span>,
              detail && (detail.status === "processing" || detail.status === "pending") ? (
                <Progress key="progress" percent={detail.progress} size="small" style={{ width: 140 }} />
              ) : null,
            ]}
          />
        }
        actions={
          completed ? (
            <Button
              size="small"
              type="primary"
              icon={<DownloadOutlined />}
              onClick={() => void downloadFileWithAuth(`${API_BASE}/${jobId}/export`, `${detail.name || "wind-farm-calc"}-results.xlsx`)}
            >
              {t("导出 Excel")}
            </Button>
          ) : (
            <Button size="small" type="primary" icon={<ReloadOutlined />} onClick={() => void detailQuery.refetch()}>
              {t("刷新")}
            </Button>
          )
        }
      />

      {detail?.error_message ? (
        <Alert
          className="wind-detail-alert"
          type="error"
          showIcon
          message={t("失败原因")}
          description={detail.error_message}
        />
      ) : null}

      {detail && detail.risk_mismatch_count > 0 ? (
        <Alert
          className="wind-detail-alert"
          type="info"
          showIcon
          message={t("GBK 风险列与后端重算不一致")}
          description={t("以后端按 V 与 S 重算的风险等级为准，GBK 原文保留在结果表 raw_line 列。")}
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
  );
}
