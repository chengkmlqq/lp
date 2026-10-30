"use client";

// 系统总览 —— 可配置仪表盘
// 布局（卡片/排序/宽度/标题）按用户配置渲染（GET/PUT /api/v1/admin/overview/config）；
// 数据来自 GET /api/v1/admin/overview。无配置时回落默认布局（资产统计 + 任务总览）。

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Col, Empty, Row, Space, Spin, Typography, message } from "antd";
import { AppstoreOutlined, SettingOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import { OverviewConfigModal } from "@/components/overview/overview-config-modal";
import {
  OverviewWidgetCard,
  type OverviewData,
  type OverviewWidget,
} from "@/components/overview/overview-widget-card";

const { Text, Title } = Typography;

const OVERVIEW_QUERY_KEY = ["/api/v1/admin/overview"] as const;
const OVERVIEW_CONFIG_QUERY_KEY = ["/api/v1/admin/overview/config"] as const;

// 与后端 overview_config_service.default_widgets() 保持一致（恢复默认用）。
const DEFAULT_WIDGETS: OverviewWidget[] = [
  { type: "asset_stats", title: "系统资产统计", span: 24, props: {} },
  { type: "task_summary", title: "任务总览", span: 24, props: {} },
];

export default function AdminOverviewPage() {
  const { t } = useI18n();
  const { fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const [configOpen, setConfigOpen] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  const overviewQuery = useQuery({
    queryKey: [...OVERVIEW_QUERY_KEY],
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/overview");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as OverviewData;
    },
  });

  const configQuery = useQuery({
    queryKey: [...OVERVIEW_CONFIG_QUERY_KEY],
    enabled: Boolean(overviewQuery.data),
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/overview/config");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { widgets: OverviewWidget[] };
    },
  });

  const saveMutation = useMutation({
    mutationFn: async (widgets: OverviewWidget[]) => {
      const response = await fetchWithAuth("/api/v1/admin/overview/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ widgets }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { widgets: OverviewWidget[] };
    },
    onSuccess: (data) => {
      queryClient.setQueryData([...OVERVIEW_CONFIG_QUERY_KEY], data);
      setConfigOpen(false);
      void messageApi.success(t("总览布局已保存"));
    },
    onError: (error) => {
      void messageApi.error(`${t("保存失败：")}${error instanceof Error ? error.message : t("未知错误")}`);
    },
  });

  if (overviewQuery.isLoading || (configQuery.isLoading && !configQuery.data)) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Spin size="large" />
      </div>
    );
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("系统总览加载失败")}
        description={overviewQuery.error instanceof Error ? overviewQuery.error.message : t("请稍后重试")}
      />
    );
  }

  const overview = overviewQuery.data;
  const widgets = configQuery.data?.widgets ?? DEFAULT_WIDGETS;

  return (
    <div className="modo-page-card">
      {contextHolder}
      <div className="modo-page-head">
        <span className="modo-page-title">
          <AppstoreOutlined />
          {t("系统总览")}
        </span>
        <Button size="small" icon={<SettingOutlined />} onClick={() => setConfigOpen(true)}>
          {t("配置布局")}
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto pt-3">
      {widgets.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("未配置卡片，点击「配置布局」添加")} />
      ) : (
        <Row gutter={[16, 16]}>
          {widgets.map((widget, index) => (
            <Col key={`${widget.type}-${index}`} xs={24} sm={widget.span >= 12 ? 24 : widget.span} md={widget.span}>
              <OverviewWidgetCard widget={widget} data={overview} />
            </Col>
          ))}
        </Row>
      )}
      </div>

      <OverviewConfigModal
        key={configOpen ? "config-open" : "config-closed"}
        open={configOpen}
        widgets={widgets}
        assets={overview.assets}
        saving={saveMutation.isPending}
        onCancel={() => setConfigOpen(false)}
        onSave={(nextWidgets) => saveMutation.mutate(nextWidgets)}
        onReset={() => saveMutation.mutate(DEFAULT_WIDGETS)}
      />
    </div>
  );
}