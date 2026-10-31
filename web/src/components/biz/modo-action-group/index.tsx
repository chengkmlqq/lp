"use client";

import React from "react";
import { Button, Dropdown, Space } from "antd";
import type { MenuProps } from "antd";
import { MoreOutlined } from "@ant-design/icons";

export interface ActionItem {
  key: string;
  label: React.ReactNode;
  icon?: React.ReactNode;
  danger?: boolean;
  disabled?: boolean;
  loading?: boolean;
  /** 按钮原生 title 提示（如禁用原因说明） */
  title?: string;
  onClick?: () => void;
  visible?: boolean;
}

export interface ModoActionGroupProps {
  actions: ActionItem[];
  /** 直接平铺的最大按钮数，超出的收进「⋯」下拉，默认 2 */
  maxCount?: number;
}

/**
 * ModoActionGroup — 表格操作列统一按钮组（对齐线路管理页范式）：
 * - 最多平铺 maxCount 个 size="small" 文字按钮（文案以两字为宜）
 * - 超出的动作收进右侧「⋯」三点下拉（危险动作用 danger 标红）
 * - 未超出 maxCount 时不渲染「⋯」
 * - action.visible === false 的动作整体隐藏（用于权限控制）
 */
export const ModoActionGroup: React.FC<ModoActionGroupProps> = ({ actions = [], maxCount = 2 }) => {
  const visibleActions = actions.filter((action) => action.visible !== false);
  if (visibleActions.length === 0) return null;

  const primaryActions =
    visibleActions.length <= maxCount ? visibleActions : visibleActions.slice(0, maxCount);
  const secondaryActions =
    visibleActions.length <= maxCount ? [] : visibleActions.slice(maxCount);

  const menuItems: MenuProps["items"] = secondaryActions.map((action) => ({
    key: action.key,
    label: (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        {action.icon}
        {action.label}
      </span>
    ),
    danger: action.danger,
    disabled: action.disabled || action.loading,
    onClick: action.onClick,
  }));

  return (
    <Space size={4} role="group" style={{ whiteSpace: "nowrap" }}>
      {primaryActions.map((action) => (
        <Button
          key={action.key}
          size="small"
          danger={action.danger}
          disabled={action.disabled || action.loading}
          loading={action.loading}
          title={action.title}
          onClick={action.onClick}
        >
          {action.label}
        </Button>
      ))}
      {secondaryActions.length > 0 && (
        <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
          <Button size="small" icon={<MoreOutlined />} aria-label="更多操作" />
        </Dropdown>
      )}
    </Space>
  );
};

export default ModoActionGroup;
