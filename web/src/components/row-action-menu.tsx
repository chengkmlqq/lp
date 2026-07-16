"use client";

import { DownOutlined } from "@ant-design/icons";
import { Button, Dropdown, Typography, type MenuProps } from "antd";

type RowActionMenuColor = "gray" | "red" | "indigo" | string;

export type RowActionMenuItem = {
  key: string;
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  color?: RowActionMenuColor;
};

type RowActionMenuProps = {
  items: RowActionMenuItem[];
  triggerLabel?: string;
  align?: "start" | "center" | "end";
};

export function RowActionMenu({
  items,
  triggerLabel = "操作",
  align = "end",
}: RowActionMenuProps) {
  if (items.length === 0) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }

  const menuItems: MenuProps["items"] = items.map((item) => ({
    key: item.key,
    label: item.label,
    disabled: item.disabled,
    danger: item.color === "red",
    onClick: () => {
      if (!item.disabled) {
        item.onSelect();
      }
    },
  }));

  const placement =
    align === "start"
      ? "bottomLeft"
      : align === "center"
        ? "bottom"
        : "bottomRight";

  return (
    <Dropdown menu={{ items: menuItems }} placement={placement} trigger={["click"]}>
      <Button size="small">
        {triggerLabel}
        <DownOutlined />
      </Button>
    </Dropdown>
  );
}
