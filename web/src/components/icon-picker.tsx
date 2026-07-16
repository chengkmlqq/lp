"use client";

import { useMemo, useState, type ComponentType } from "react";
import { Input, Space, Tabs, Tooltip, Typography } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { ICON_CATEGORIES, resolveIcon } from "@/lib/icon-registry";

type IconPickerProps = {
  value?: string;
  onChange?: (value: string) => void;
};

export function IconPicker({ value, onChange }: IconPickerProps) {
  const [searchText, setSearchText] = useState("");
  const [activeTab, setActiveTab] = useState("all");

  const allIcons = useMemo(() => {
    const seen = new Set<string>();
    const result: { name: string; label: string }[] = [];
    for (const cat of ICON_CATEGORIES) {
      for (const icon of cat.icons) {
        if (!seen.has(icon.name)) {
          seen.add(icon.name);
          result.push({ name: icon.name, label: icon.label });
        }
      }
    }
    return result;
  }, []);

  const filteredIcons = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    if (!q) return allIcons;
    return allIcons.filter(
      (icon) =>
        icon.name.toLowerCase().includes(q) ||
        icon.label.toLowerCase().includes(q),
    );
  }, [allIcons, searchText]);

  const tabItems = useMemo(() => {
    const items = [
      {
        key: "all",
        label: `全部 (${allIcons.length})`,
        children: renderIconGrid(filteredIcons, value, onChange),
      },
      ...ICON_CATEGORIES.map((cat) => ({
        key: cat.key,
        label: `${cat.label} (${cat.icons.length})`,
        children: renderIconGrid(
          cat.icons.map((i) => ({ name: i.name, label: i.label })),
          value,
          onChange,
        ),
      })),
    ];
    return items;
  }, [allIcons.length, filteredIcons, value, onChange]);

  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Input
        allowClear
        placeholder="搜索图标名称..."
        prefix={<SearchOutlined />}
        value={searchText}
        onChange={(e) => {
          setSearchText(e.target.value);
          setActiveTab("all");
        }}
      />
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key);
          setSearchText("");
        }}
        items={tabItems}
        size="small"
        style={{ maxHeight: 360 }}
      />
      {value && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Typography.Text type="secondary">已选：</Typography.Text>
          {renderIconPreview(value)}
          <Typography.Text code>{value}</Typography.Text>
          <a
            style={{ cursor: "pointer", marginLeft: "auto" }}
            onClick={() => onChange?.("")}
          >
            清除
          </a>
        </div>
      )}
    </Space>
  );
}

function renderIconGrid(
  icons: { name: string; label: string }[],
  selectedValue: string | undefined,
  onSelect: ((value: string) => void) | undefined,
) {
  if (icons.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 24, color: "var(--ant-color-text-tertiary)" }}>
        未找到匹配的图标
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(72px, 1fr))",
        gap: 4,
        maxHeight: 260,
        overflowY: "auto",
      }}
    >
      {icons.map((icon) => {
        const isSelected = selectedValue === icon.name;
        const IconComp = resolveIcon(icon.name);
        return (
          <Tooltip key={icon.name} title={`${icon.label} (${icon.name})`}>
            <div
              onClick={() => onSelect?.(icon.name)}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 2,
                padding: "6px 2px",
                borderRadius: 6,
                cursor: "pointer",
                border: isSelected
                  ? "2px solid var(--ant-color-primary)"
                  : "2px solid transparent",
                background: isSelected
                  ? "var(--ant-color-primary-bg)"
                  : "transparent",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => {
                if (!isSelected) {
                  (e.currentTarget as HTMLElement).style.background =
                    "var(--ant-color-bg-elevated)";
                }
              }}
              onMouseLeave={(e) => {
                if (!isSelected) {
                  (e.currentTarget as HTMLElement).style.background =
                    "transparent";
                }
              }}
            >
              {IconComp && <IconComp style={{ fontSize: 20 }} />}
              <Typography.Text
                style={{
                  fontSize: 10,
                  lineHeight: "1.2",
                  textAlign: "center",
                  maxWidth: 64,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                type="secondary"
              >
                {icon.name.replace(/Outlined$/, "")}
              </Typography.Text>
            </div>
          </Tooltip>
        );
      })}
    </div>
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
