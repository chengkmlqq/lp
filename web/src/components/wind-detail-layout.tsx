"use client";

import { Fragment, type ReactNode } from "react";
import { Space } from "antd";

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
