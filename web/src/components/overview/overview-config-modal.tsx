"use client";

// 系统总览 —— 配置弹窗：增删卡片、排序、调宽度、编辑标题与卡片专属参数。

import { useI18n } from "@/lib/i18n";
import {
  Button,
  Checkbox,
  Divider,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import {
  WIDGET_TYPE_META,
  widgetDefaultTitle,
  type OverviewAssetStat,
  type OverviewWidget,
  type OverviewWidgetType,
} from "./overview-widget-card";

const { Text } = Typography;

const SPAN_OPTIONS = [
  { value: 24, label: "整行" },
  { value: 12, label: "半行" },
  { value: 8, label: "1/3 行" },
  { value: 6, label: "1/4 行" },
];

const DEFAULT_SPAN: Record<OverviewWidgetType, number> = {
  asset_stats: 24,
  task_summary: 12,
  task_states: 8,
  quick_links: 6,
};

interface OverviewConfigModalProps {
  open: boolean;
  widgets: OverviewWidget[];
  assets: OverviewAssetStat[];
  saving?: boolean;
  onCancel: () => void;
  onSave: (widgets: OverviewWidget[]) => void;
  onReset: () => void;
}

export function OverviewConfigModal({
  open,
  widgets,
  assets,
  saving,
  onCancel,
  onSave,
  onReset,
}: OverviewConfigModalProps) {
  const { t } = useI18n();
  // 草稿状态：惰性初始化自当前配置。
  // 打开时同步由父组件通过 key 重挂载实现（见 page.tsx：<OverviewConfigModal key={...}>），
  // React 19 lint 不允许在 effect 内同步 setState。
  const [draft, setDraft] = useState<OverviewWidget[]>(() =>
    widgets.map((widget) => ({
      ...widget,
      props: { ...widget.props },
    })),
  );

  const updateDraft = (next: OverviewWidget[]) => setDraft(next);

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= draft.length) return;
    const next = [...draft];
    [next[index], next[target]] = [next[target], next[index]];
    updateDraft(next);
  };

  const removeAt = (index: number) => {
    updateDraft(draft.filter((_, i) => i !== index));
  };

  const addWidget = (type: OverviewWidgetType) => {
    const widget: OverviewWidget = {
      type,
      title: null,
      span: DEFAULT_SPAN[type],
      props: type === "asset_stats" ? { asset_keys: assets.map((item) => item.key) } : type === "quick_links" ? { links: [] } : {},
    };
    updateDraft([...draft, widget]);
  };

  const patchWidget = (index: number, patch: Partial<OverviewWidget>) => {
    updateDraft(
      draft.map((widget, i) => (i === index ? { ...widget, ...patch } : widget)),
    );
  };

  const assetKeys = useMemo(() => assets.map((item) => item.key), [assets]);

  const quickLinksOf = (widget: OverviewWidget): { label: string; href: string }[] =>
    Array.isArray(widget.props.links) ? (widget.props.links as { label: string; href: string }[]) : [];

  return (
    <Modal
      open={open}
      title={t("配置系统总览")}
      width={720}
      onCancel={onCancel}
      footer={
        <Space>
          <Popconfirm title={t("恢复为默认布局？")} onConfirm={onReset} okText={t("恢复")} cancelText={t("取消")}>
            <Button>{t("恢复默认")}</Button>
          </Popconfirm>
          <Button onClick={onCancel}>{t("取消")}</Button>
          <Button type="primary" loading={saving} onClick={() => onSave(draft)}>
            {t("保存布局")}
          </Button>
        </Space>
      }
    >
      <Divider orientation="left" plain>
        {t("卡片库（点击添加）")}
      </Divider>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(WIDGET_TYPE_META) as OverviewWidgetType[]).map((type) => (
          <Button key={type} size="small" onClick={() => addWidget(type)}>
            + {t(WIDGET_TYPE_META[type].label)}
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
              {t(WIDGET_TYPE_META[type].hint)}
            </Text>
          </Button>
        ))}
      </div>

      <Divider orientation="left" plain>
        {t("已配置卡片")}（{draft.length}）
      </Divider>

      {draft.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("尚未添加卡片，从上方卡片库选择")} />
      ) : (
        <div className="flex flex-col gap-3">
          {draft.map((widget, index) => (
            <div
              key={`${widget.type}-${index}`}
              className="rounded-lg border border-solid border-[var(--ant-color-border-secondary)] p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Space>
                  <Button size="small" disabled={index === 0} onClick={() => move(index, -1)}>
                    ↑
                  </Button>
                  <Button size="small" disabled={index === draft.length - 1} onClick={() => move(index, 1)}>
                    ↓
                  </Button>
                </Space>
                <Tag color="blue">{WIDGET_TYPE_META[widget.type]?.label ? t(WIDGET_TYPE_META[widget.type].label) : widget.type}</Tag>
                <Input
                  size="small"
                  style={{ width: 180 }}
                  value={widget.title ?? ""}
                  placeholder={widgetDefaultTitle(widget.type, t)}
                  onChange={(event) => patchWidget(index, { title: event.target.value || null })}
                />
                <Select
                  size="small"
                  style={{ width: 90 }}
                  value={widget.span}
                  options={SPAN_OPTIONS.map((opt) => ({ ...opt, label: t(opt.label) }))}
                  onChange={(span) => patchWidget(index, { span })}
                />
                <Popconfirm title={t("删除该卡片？")} onConfirm={() => removeAt(index)} okText={t("删除")} cancelText={t("取消")}>
                  <Button size="small" danger>
                    删除
                  </Button>
                </Popconfirm>
              </div>

              {widget.type === "asset_stats" ? (
                <div className="mt-2">
                  <Checkbox.Group
                    value={(Array.isArray(widget.props.asset_keys) ? widget.props.asset_keys : assetKeys) as string[]}
                    onChange={(keys) => patchWidget(index, { props: { ...widget.props, asset_keys: keys } })}
                    options={assets.map((item) => ({ label: item.label, value: item.key }))}
                  />
                </div>
              ) : null}

              {widget.type === "quick_links" ? (
                <div className="mt-2 flex flex-col gap-2">
                  {quickLinksOf(widget).map((link, linkIndex) => (
                    <div key={linkIndex} className="flex items-center gap-2">
                      <Input
                        size="small"
                        style={{ width: 140 }}
                        placeholder={t("名称（如 ATP模型）")}
                        value={link.label}
                        onChange={(event) => {
                          const links = quickLinksOf(widget).map((item, i) =>
                            i === linkIndex ? { ...item, label: event.target.value } : item,
                          );
                          patchWidget(index, { props: { ...widget.props, links } });
                        }}
                      />
                      <Input
                        size="small"
                        style={{ flex: 1 }}
                        placeholder="/admin/atp-models"
                        value={link.href}
                        onChange={(event) => {
                          const links = quickLinksOf(widget).map((item, i) =>
                            i === linkIndex ? { ...item, href: event.target.value } : item,
                          );
                          patchWidget(index, { props: { ...widget.props, links } });
                        }}
                      />
                      <Button
                        size="small"
                        danger
                        onClick={() => {
                          const links = quickLinksOf(widget).filter((_, i) => i !== linkIndex);
                          patchWidget(index, { props: { ...widget.props, links } });
                        }}
                      >
                        {t("删")}
                      </Button>
                    </div>
                  ))}
                  <Button
                    size="small"
                    onClick={() => {
                      const links = [...quickLinksOf(widget), { label: "", href: "" }];
                      patchWidget(index, { props: { ...widget.props, links } });
                    }}
                  >
                    {t("+ 添加链接")}
                  </Button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}