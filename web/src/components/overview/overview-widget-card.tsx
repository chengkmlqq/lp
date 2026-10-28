"use client";

// 系统总览 —— 可配置卡片渲染器
// 卡片类型与后端 overview_config_service.WIDGET_TYPES 一一对应；
// 数据全部来自 GET /api/v1/admin/overview（前端按配置过滤/拼装，不再新增后端统计接口）。

import { useI18n } from "@/lib/i18n";
import Link from "next/link";
import { Card, Col, Row, Statistic, Tag, Typography } from "antd";

import type { ComponentType, ReactNode, RefAttributes } from "react";
import type { CardProps } from "antd";

const { Text } = Typography;

export type OverviewWidgetType = "asset_stats" | "task_summary" | "task_states" | "quick_links";

export type OverviewWidget = {
  type: OverviewWidgetType;
  title?: string | null;
  span: number;
  props: Record<string, unknown>;
};

export type OverviewAssetStat = {
  key: string;
  label: string;
  count: number;
  route: string | null;
};

export type OverviewStateBucket = {
  key: string;
  label: string;
  count: number;
};

export type OverviewData = {
  generated_at: string;
  assets: OverviewAssetStat[];
  tasks: {
    total: number;
    queue_pending_total: number;
    scheduled_tasks: number;
    state_buckets: OverviewStateBucket[];
  };
};

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const STATE_COLORS: Record<string, string> = {
  SUCCESS: "green",
  FAILURE: "red",
  STARTED: "processing",
  PENDING: "default",
  RECEIVED: "default",
  RETRY: "orange",
  REVOKED: "default",
};

export const WIDGET_TYPE_META: Record<OverviewWidgetType, { label: string; defaultTitle: string; hint: string }> = {
  asset_stats: { label: "资产统计", defaultTitle: "系统资产统计", hint: "各业务对象的数量，可勾选要展示的类别" },
  task_summary: { label: "任务总览", defaultTitle: "任务总览", hint: "历史任务总数 / 队列积压 / 定时任务" },
  task_states: { label: "任务状态", defaultTitle: "任务状态分布", hint: "任务状态标签墙" },
  quick_links: { label: "快捷入口", defaultTitle: "快捷入口", hint: "自定义常用页面链接" },
};

export function widgetDefaultTitle(type: OverviewWidgetType, t: (s: string) => string = (s) => s): string {
  const meta = WIDGET_TYPE_META[type];
  return meta ? t(meta.defaultTitle) : t("卡片");
}

function AssetStatsCard({ widget, data }: { widget: OverviewWidget; data: OverviewData }) {
  const { t } = useI18n();
  const selectedKeys = Array.isArray(widget.props.asset_keys)
    ? (widget.props.asset_keys as string[])
    : data.assets.map((item) => item.key);
  const items = data.assets.filter((item) => selectedKeys.includes(item.key));

  return (
    <Row gutter={[16, 16]}>
      {items.map((item) => {
        const stat = <Statistic title={item.label} value={item.count} valueStyle={{ fontSize: 22 }} />;
        return (
          <Col key={item.key} xs={12} sm={8} md={6} lg={6}>
            {item.route ? (
              <Link href={item.route} className="block !text-inherit no-underline" prefetch={false}>
                <div className="rounded-lg border border-solid border-[var(--ant-color-border-secondary)] p-3 transition-colors hover:bg-[var(--ant-color-fill-tertiary)]">
                  {stat}
                </div>
              </Link>
            ) : (
              <div className="rounded-lg border border-solid border-[var(--ant-color-border-secondary)] p-3">
                {stat}
              </div>
            )}
          </Col>
        );
      })}
      {items.length === 0 ? <Text type="secondary">{t("未选择任何资产类别")}</Text> : null}
    </Row>
  );
}

function TaskSummaryCard({ data }: { data: OverviewData }) {
  const { t } = useI18n();
  return (
    <Row gutter={[16, 16]}>
      <Col xs={12} sm={8} md={4}>
        <Statistic title={t("历史任务总数")} value={data.tasks.total} />
      </Col>
      <Col xs={12} sm={8} md={4}>
        <Statistic title={t("队列积压任务数")} value={data.tasks.queue_pending_total} />
      </Col>
      <Col xs={12} sm={8} md={4}>
        <Statistic title={t("定时任务数")} value={data.tasks.scheduled_tasks} />
      </Col>
    </Row>
  );
}

function TaskStatesCard({ data }: { data: OverviewData }) {
  const { t } = useI18n();
  if (data.tasks.state_buckets.length === 0) {
    return <Text type="secondary">{t("暂无任务历史记录")}</Text>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {data.tasks.state_buckets.map((bucket) => (
        <Tag key={bucket.key} color={STATE_COLORS[bucket.key] ?? "default"}>
          {bucket.label} · {bucket.count}
        </Tag>
      ))}
    </div>
  );
}

interface QuickLinkItem {
  label: string;
  href: string;
}

function QuickLinksCard({ widget }: { widget: OverviewWidget }) {
  const { t } = useI18n();
  const links = (Array.isArray(widget.props.links) ? widget.props.links : []) as QuickLinkItem[];
  if (links.length === 0) {
    return <Text type="secondary">{t("尚未配置快捷入口")}</Text>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {links.map((link, index) => (
        <Link
          key={`${link.href}-${index}`}
          href={link.href}
          prefetch={false}
          className="no-underline"
        >
          <Tag color="blue" style={{ cursor: "pointer", padding: "4px 10px", fontSize: 13 }}>
            {link.label}
          </Tag>
        </Link>
      ))}
    </div>
  );
}

/** 渲染单张配置卡片；未知类型返回 null（前端兜底，不白屏）。 */
export function OverviewWidgetCard({ widget, data }: { widget: OverviewWidget; data: OverviewData }) {
  const { t } = useI18n();
  const title = widget.title?.trim() || widgetDefaultTitle(widget.type);
  let body: ReactNode = null;
  switch (widget.type) {
    case "asset_stats":
      body = <AssetStatsCard widget={widget} data={data} />;
      break;
    case "task_summary":
      body = <TaskSummaryCard data={data} />;
      break;
    case "task_states":
      body = <TaskStatesCard data={data} />;
      break;
    case "quick_links":
      body = <QuickLinksCard widget={widget} />;
      break;
    default:
      body = null;
  }
  if (body === null) return null;
  return (
    <AntCard title={title} size="small" style={{ height: "100%" }}>
      {body}
    </AntCard>
  );
}