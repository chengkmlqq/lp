"use client";

import { useMemo, useState } from "react";
import { Input, Typography } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { ICON_CATEGORIES, resolveIcon } from "@/lib/icon-registry";

const { Title } = Typography;

export default function AdminIconsPage() {
  const [search, setSearch] = useState("");

  const categories = useMemo(() => {
    const q = search.trim().toLowerCase();
    return ICON_CATEGORIES.map((cat) => ({
      ...cat,
      icons: cat.icons.filter(
        (icon) =>
          !q ||
          icon.name.toLowerCase().includes(q) ||
          icon.label.toLowerCase().includes(q),
      ),
    })).filter((cat) => cat.icons.length > 0);
  }, [search]);

  return (
    <div className="p-6">
      <Title level={4} style={{ marginBottom: 16 }}>
        图标参考
      </Title>
      <Input
        placeholder="搜索图标名称..."
        prefix={<SearchOutlined />}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 24, maxWidth: 320 }}
        allowClear
      />
      {categories.map((cat) => (
        <div key={cat.key} style={{ marginBottom: 24 }}>
          <Title level={5} style={{ marginBottom: 12 }}>
            {cat.label}
          </Title>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
              gap: 12,
            }}
          >
            {cat.icons.map((icon) => {
              const Component = resolveIcon(icon.name);
              return (
                <div
                  key={icon.name}
                  title={`${icon.label} (${icon.name})`}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 4,
                    padding: 12,
                    border: "1px solid var(--ant-color-border, #d9d9d9)",
                    borderRadius: 8,
                    cursor: "default",
                    transition: "border-color 0.2s",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLDivElement).style.borderColor =
                      "var(--ant-color-primary, #1677ff)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLDivElement).style.borderColor =
                      "var(--ant-color-border, #d9d9d9)";
                  }}
                >
                  <span style={{ fontSize: 20 }}>
                    {Component && <Component />}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      color: "var(--ant-color-text-secondary, rgba(0,0,0,0.45))",
                      textAlign: "center",
                      wordBreak: "break-all",
                    }}
                  >
                    {icon.name}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {categories.length === 0 && (
        <div style={{ color: "var(--ant-color-text-secondary)" }}>
          没有找到匹配的图标
        </div>
      )}
    </div>
  );
}
