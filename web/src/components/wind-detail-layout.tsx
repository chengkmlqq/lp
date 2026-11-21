"use client";

import { Fragment, type ReactNode } from "react";
import { Button, Dropdown, Space } from "antd";
import { MoreOutlined } from "@ant-design/icons";

import { ModoPagination } from "@/components/biz/modo-pagination";

/**
 * 风电四个详情页的共用版式零件（LP-49）。
 *
 * 全部复用 ATP 模型详情页的类名与 CSS 变量，保证概览带 / 状态 chip /
 * 副行 / 无边框属性网格与 ATP 模型详情完全一致；四个页面只传内容，
 * 不在各自文件里复制样式或状态映射。
 */

/** 状态 → ATP 同款状态 chip 样式类（与 `.admin-atp-models-state-chip.is-*` 对齐）。 */
const STATUS_CHIP_CLASS: Record<string, string> = {
  completed: "is-active",
  processing: "is-processing",
  pending: "is-muted",
  failed: "is-danger",
  cancelled: "is-warning",
};

/** ATP 同款小状态 chip：小圆点 + 文案。 */
export function WindStatusChip({
  status,
  label,
  dot = true,
}: {
  status: string;
  label: string;
  dot?: boolean;
}) {
  return (
    <span className={`admin-atp-models-state-chip ${STATUS_CHIP_CLASS[status] ?? "is-muted"}`}>
      {dot ? <span className="admin-atp-models-state-chip-dot" /> : null}
      {label}
    </span>
  );
}

/** ATP 同款副行：多个关键标识以「·」分隔，自动跳过空项。 */
export function WindDetailSubline({ items }: { items: ReactNode[] }) {
  const visible = items.filter((item) => item !== null && item !== undefined && item !== "");
  return (
    <>
      {visible.map((item, index) => (
        <Fragment key={index}>
          {index > 0 ? <span className="admin-atp-models-detail-subline-dot">·</span> : null}
          {item}
        </Fragment>
      ))}
    </>
  );
}

/**
 * 概览带：图标锚点 + 标题（批次/任务名）+ 状态 chip + 副行 + 右侧操作区。
 * 由 `.wind-detail-pane` 约束为固定不滚动，仅 Tab 内容区滚动。
 */
export function WindDetailHero({
  icon,
  title,
  titleTooltip,
  statusChip,
  subline,
  actions,
}: {
  icon: ReactNode;
  title: ReactNode;
  titleTooltip?: string;
  statusChip?: ReactNode;
  subline?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="admin-atp-models-detail-hero wind-detail-hero">
      <div className="admin-atp-models-detail-hero-head">
        <span className="admin-atp-models-card-tile admin-atp-models-detail-tile" aria-hidden>
          {icon}
        </span>
        <div className="admin-atp-models-detail-headline">
          <div className="admin-atp-models-detail-name">
            <span className="admin-atp-models-detail-name-text" title={titleTooltip}>
              {title}
            </span>
            {statusChip}
          </div>
          {subline ? <div className="admin-atp-models-detail-subline">{subline}</div> : null}
        </div>
        {actions ? (
          <Space size={6} wrap className="shrink-0 wind-detail-hero-actions">
            {actions}
          </Space>
        ) : null}
      </div>
    </div>
  );
}

export type WindDetailMetaItem = {
  label: ReactNode;
  value: ReactNode;
  /** 长字段（统计范围、失败原因等）跨两列。 */
  span?: 1 | 2;
};

/** 基本信息：ATP 同款无边框四列属性网格（窄屏两列）。 */
export function WindDetailMeta({ items }: { items: WindDetailMetaItem[] }) {
  return (
    <dl className="admin-atp-models-detail-meta wind-detail-meta">
      {items.map((item, index) => (
        <div
          key={index}
          className={item.span === 2 ? "wind-detail-meta-span-2" : undefined}
        >
          <dt>{item.label}</dt>
          <dd>{item.value ?? "-"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 关键指标条条目：大数字 + 小灰标签，复用 ATP 统计行视觉。 */
export type WindDetailMetricItem = {
  label: ReactNode;
  value: ReactNode;
  tone?: "success" | "danger" | "running" | "muted";
  suffix?: ReactNode;
};

/**
 * 统一关键指标条（LP-59）：最多 6 项，6/3/2 列自适应，因列数整除 6 不会出现单个孤项。
 * 放在 Hero 与基本信息之间的固定区域，四个页面只传数据，不再各自拼 Row/Col/Statistic。
 */
export function WindDetailMetricStrip({
  items,
  max = 6,
}: {
  items: WindDetailMetricItem[];
  max?: number;
}) {
  const visible = items.slice(0, max);
  if (!visible.length) return null;
  return (
    <div className="wind-detail-metric-strip">
      {visible.map((item, index) => (
        <div className="admin-atp-models-detail-stat" key={index}>
          <span
            className={`admin-atp-models-detail-stat-value${item.tone ? ` is-${item.tone}` : ""}`}
          >
            {item.value}
            {item.suffix ? <span className="wind-detail-metric-suffix">{item.suffix}</span> : null}
          </span>
          <span className="admin-atp-models-detail-stat-label">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

/** 常驻分页底栏配置：由当前激活 Tab 的表格状态驱动。 */
export type WindDetailPaginationConfig = {
  current: number;
  pageSize: number;
  total: number;
  pageSizeOptions?: number[];
  onChange: (page: number, pageSize: number) => void;
};

/**
 * 常驻分页底栏（LP-59）：作为 .wind-detail-pane 的直接子节点渲染，
 * 位于 Tabs 之后、flex:0 0 auto，因此固定在面板右下角，Tab 内容滚动/切换时都不移动。
 * 没有可分页表格（total<=0）时整体不渲染，不留空条。
 */
export function WindDetailPaginationFooter({
  pagination,
}: {
  pagination: WindDetailPaginationConfig | null | undefined;
}) {
  if (!pagination || !pagination.total) return null;
  return (
    <ModoPagination
      current={pagination.current}
      pageSize={pagination.pageSize}
      total={pagination.total}
      showSizeChanger
      pageSizeOptions={pagination.pageSizeOptions ?? [10, 20, 50, 100]}
      onChange={pagination.onChange}
      containerClassName="wind-detail-pagination"
    />
  );
}

/** 次要操作条目：收进 Hero 右侧的「更多」下拉。 */
export type WindDetailAction = {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  onClick: () => void;
  danger?: boolean;
  disabled?: boolean;
};

/** 收敛后的次要操作区（LP-59）：主操作直接平铺，次要操作传入此组件。 */
export function WindDetailMoreActions({
  items,
  label,
}: {
  items: WindDetailAction[];
  label: ReactNode;
}) {
  if (!items.length) return null;
  return (
    <Dropdown
      trigger={["click"]}
      menu={{
        items: items.map((item) => ({
          key: item.key,
          label: item.label,
          icon: item.icon,
          onClick: item.onClick,
          danger: item.danger,
          disabled: item.disabled,
        })),
      }}
    >
      <Button size="small" icon={<MoreOutlined />}>
        {label}
      </Button>
    </Dropdown>
  );
}
