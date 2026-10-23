"use client";

import { useMemo } from "react";
import { Select, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { ICON_CATEGORIES, resolveIcon } from "@/lib/icon-registry";

type IconPickerProps = {
  value?: string;
  onChange?: (value: string) => void;
};

/**
 * 图标下拉选择器 — 按业务场景分组展示（与 ICON_CATEGORIES 一致），
 * 支持搜索（图标名/中文标签）与清除。
 */
export function IconPicker({ value, onChange }: IconPickerProps) {
  const { t } = useI18n();
  const groupedOptions = useMemo(() => {
    return ICON_CATEGORIES.map((cat) => ({
      label: cat.label,
      options: cat.icons.map((icon) => {
        const IconComp = icon.component;
        return {
          value: icon.name,
          name: icon.name,
          labelText: `${icon.label} ${icon.name}`,
          label: (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <IconComp style={{ fontSize: 16 }} />
              <span>{icon.label}</span>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {icon.name}
              </Typography.Text>
            </span>
          ),
        };
      }),
    }));
  }, []);

  return (
    <Select
      allowClear
      showSearch
      placeholder={t("选择图标")}
      value={value || undefined}
      onChange={(next) => onChange?.(next ?? "")}
      options={groupedOptions}
      filterOption={(input, option) => {
        const opt = (option ?? {}) as { name?: string; labelText?: string };
        return `${opt.name ?? ""} ${opt.labelText ?? ""}`
          .toLowerCase()
          .includes(input.toLowerCase());
      }}
      style={{ width: "100%" }}
    />
  );
}

/** 渲染单个图标预览（用于表单显示当前选中图标） */
export function IconPreview({ name, showLabel }: { name: string | null; showLabel?: boolean }) {
  return renderIconPreview(name, showLabel);
}

function renderIconPreview(name: string | null, showLabel?: boolean) {
  if (!name) return <Typography.Text type="secondary">-</Typography.Text>;
  const IconComp = resolveIcon(name);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      {IconComp ? <IconComp style={{ fontSize: 16 }} /> : null}
      {showLabel && <Typography.Text code>{name}</Typography.Text>}
    </span>
  );
}
