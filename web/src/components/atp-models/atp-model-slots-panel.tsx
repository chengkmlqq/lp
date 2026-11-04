"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Descriptions, Empty, Space, Spin, Table, Tag, Typography } from "antd";
import { Card as ThemeCard } from "@/components/ui-antd";
import { ReloadOutlined, ScanOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

interface AtpModelSlotsPanelProps {
  assetId: string;
}

type GeometryView = {
  conductor_start: number;
  conductor_count: number;
  col_x?: number;
  col_y?: number;
  col_z?: number;
  span_rows: number[];
  span_col?: number;
  span_width?: number;
};

type SlotsView = {
  asset_id: string;
  scanned_at: string | null;
  work_atp: { slots: Record<string, string>; count: number };
  geometry: Record<string, GeometryView>;
  slot_names: string[];
  geometry_models: string[];
  /** 异步分析状态（2026-11-03）：pending/running 时扫描还没回写，面板要轮询 */
  analysis_status?: "pending" | "running" | "success" | "failed" | null;
  analysis_error?: string | null;
};

type CoverageView = {
  asset_id: string;
  template_id: string | null;
  templates_used: { id: string; name: string }[];
  model_slots: string[];
  template_slots: string[];
  missing: string[];
  unused: string[];
  covered: string[];
  coverage_rate: number;
};

function formatScannedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

const SLOT_TAG_COLORS: Record<string, string> = {
  covered: "green",
  missing: "red",
  unused: "orange",
};

export function AtpModelSlotsPanel({ assetId }: AtpModelSlotsPanelProps) {
  const { t } = useI18n();
  const { fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  // 走全局 AntApp 上下文，避免局部 useMessage 渲染到主题容器外（气泡样式缺失）。
  const { message: messageApi } = App.useApp();
  const [scanning, setScanning] = useState(false);

  const canManage = hasPermission("atp.manage");

  const slotsQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "slots"],
    enabled: Boolean(assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/slots`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as SlotsView;
    },
    // 后台分析进行中（扫描任务在读 OSS）时轮询，出终态自动停
    refetchInterval: (query) => {
      const status = (query.state.data as SlotsView | undefined)?.analysis_status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });

  const coverageQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "coverage"],
    enabled: Boolean(assetId) && (slotsQuery.data?.work_atp.count ?? 0) > 0,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/coverage`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as CoverageView;
    },
  });

  const scanMutation = useMutation({
    mutationFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/scan-slots`, { method: "POST" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as SlotsView;
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["/api/v1/atp/assets", assetId, "slots"] });
      void queryClient.invalidateQueries({ queryKey: ["/api/v1/atp/assets", assetId, "coverage"] });
      // 2026-11-03：扫描改为后台任务（读 OSS 要 1~3 秒），接口先返回 pending；
      // 面板按 analysis_status 轮询，结果回写后自动出现。
      if (data.analysis_status === "failed") {
        void messageApi.error(data.analysis_error || t("槽位扫描任务入队失败，请稍后重试"));
        return;
      }
      void messageApi.success(t("已提交槽位扫描，完成后自动刷新"));
    },
    onError: (error: Error) => {
      void messageApi.error(error.message || t("槽位扫描失败"));
    },
  });

  const slotRows = Object.entries(slotsQuery.data?.work_atp.slots ?? {}).map(([name, value]) => ({
    key: name,
    name,
    value,
  }));

  const coverage = coverageQuery.data;
  const groups: { key: "covered" | "missing" | "unused"; label: string; items: string[] }[] = [
    { key: "covered", label: t("已覆盖"), items: coverage?.covered ?? [] },
    { key: "missing", label: t("缺失（模型有·模板未映射）"), items: coverage?.missing ?? [] },
    { key: "unused", label: t("冗余（模板映射·模型无）"), items: coverage?.unused ?? [] },
  ];

  return (
    <ThemeCard
      className="admin-atp-models-slots-card"
      title={
        <Space>
          <Typography.Text strong>{t("模型槽位")}</Typography.Text>
          {slotsQuery.data?.scanned_at ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t("扫描时间")}: {formatScannedAt(slotsQuery.data.scanned_at)}
            </Typography.Text>
          ) : null}
          {/* 后台分析进行中：扫描结果还没回写，明确告诉人工在等什么 */}
          {slotsQuery.data?.analysis_status === "pending" || slotsQuery.data?.analysis_status === "running" ? (
            <Tag color="processing" icon={<Spin size="small" />}>
              {t("扫描中")}
            </Tag>
          ) : null}
          {slotsQuery.data?.analysis_status === "failed" ? (
            <Tag color="red">{t("扫描失败")}</Tag>
          ) : null}
        </Space>
      }
      extra={
        canManage ? (
          <Button
            size="small"
            icon={<ScanOutlined />}
            loading={scanMutation.isPending || scanning}
            onClick={() => void scanMutation.mutateAsync()}
          >
            {slotsQuery.data?.scanned_at ? t("重新扫描") : t("扫描槽位")}
          </Button>
        ) : null
      }
      styles={{ body: { paddingTop: 8 } }}
    >
      {slotsQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <Spin />
        </div>
      ) : slotsQuery.isError ? (
        <Alert type="error" showIcon message={t("加载槽位失败")} description={slotsQuery.error instanceof Error ? slotsQuery.error.message : ""} />
      ) : (slotsQuery.data?.work_atp.count ?? 0) === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("尚未扫描，槽位表为空")} />
      ) : (
        <>
          <Space size={16} style={{ marginBottom: 12 }} wrap>
            <Typography.Text>
              {t("槽位总数")}: <Tag color="blue">{slotsQuery.data?.work_atp.count ?? 0}</Tag>
            </Typography.Text>
            <Typography.Text>
              {t("几何模型")}: <Tag color="geekblue">{slotsQuery.data?.geometry_models.join(" / ") || "-"}</Tag>
            </Typography.Text>
          </Space>
          <Typography.Title level={5} style={{ marginTop: 8, fontSize: 14 }}>
            work.atp
          </Typography.Title>
          <Table
            rowKey="key"
            size="small"
            dataSource={slotRows}
            pagination={false}
            className="admin-atp-models-slots-table"
            columns={[
              { title: t("槽位名"), dataIndex: "name", key: "name" },
              { title: t("当前展示值"), dataIndex: "value", key: "value", ellipsis: true },
            ]}
          />
          {Object.keys(slotsQuery.data?.geometry ?? {}).length > 0 ? (
            <>
              <Typography.Title level={5} style={{ marginTop: 16, fontSize: 14 }}>
                {t("几何坐标")}
              </Typography.Title>
              <Space size={12} wrap>
                {Object.entries(slotsQuery.data?.geometry ?? {}).map(([name, geo]) => (
                  <ThemeCard key={name} size="small" className="admin-atp-models-geo-card" styles={{ body: { padding: "8px 16px" } }}>
                    <Descriptions
                      size="small"
                      column={1}
                      style={{ minWidth: 220 }}
                      items={[
                        { key: "start", label: t("导体起始行"), children: geo.conductor_start },
                        { key: "count", label: t("导体数"), children: geo.conductor_count },
                        { key: "cols", label: t("列位 (X/Y/Z)"), children: `${geo.col_x ?? "-"} / ${geo.col_y ?? "-"} / ${geo.col_z ?? "-"}` },
                        { key: "span", label: t("档距行"), children: geo.span_rows.join(", ") || "-" },
                      ]}
                    />
                  </ThemeCard>
                ))}
              </Space>
            </>
          ) : null}
          <Typography.Title level={5} style={{ marginTop: 16, fontSize: 14 }}>
            {t("槽位覆盖检测")}
            {coverage ? <Tag color="blue" style={{ marginLeft: 8 }}>{t("覆盖率")}: {coverage.coverage_rate}%</Tag> : null}
          </Typography.Title>
          {coverageQuery.isLoading ? (
            <Spin size="small" />
          ) : coverageQuery.isError ? (
            <Typography.Text type="secondary">{coverageQuery.error instanceof Error ? coverageQuery.error.message : t("覆盖检测失败")}</Typography.Text>
          ) : coverage ? (
            <>
              {coverage.templates_used.length > 0 ? (
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                  {t("参与检测的模板")}: {coverage.templates_used.map((tm) => tm.name).join("、")}
                </Typography.Paragraph>
              ) : null}
              <Space size={8} wrap>
                {groups.map((group) => (
                  <span key={group.key}>
                    <Tag color={SLOT_TAG_COLORS[group.key]}>{group.label}</Tag>
                    {group.items.length === 0 ? (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>-</Typography.Text>
                    ) : (
                      group.items.slice(0, 30).map((name) => (
                        <Tag key={name} style={{ fontSize: 12 }}>
                          {name}
                        </Tag>
                      ))
                    )}
                    {group.items.length > 30 ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>+{group.items.length - 30}</Typography.Text> : null}
                  </span>
                ))}
              </Space>
            </>
          ) : null}
        </>
      )}
    </ThemeCard>
  );
}