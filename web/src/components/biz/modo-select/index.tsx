"use client";

import React, { FC } from "react";
import { Select } from "antd";
import type { SelectProps } from "antd";
import { useI18n } from "@/lib/i18n";

export interface ModoSelectProps extends SelectProps {}

interface ModoSelectInternal extends FC<ModoSelectProps> {
  Option: typeof Select.Option;
}

/** ModoSelect — 默认 filled 变体 + 100% 宽（对齐 data-synth） */
export const ModoSelect: ModoSelectInternal = ({
  variant = "filled",
  placeholder,
  allowClear = true,
  style,
  ...props
}) => {
  const { t } = useI18n();
  return (
    <Select
      variant={variant}
      placeholder={placeholder ?? t("请选择")}
      allowClear={allowClear}
      style={{ width: "100%", ...style }}
      {...props}
    />
  );
};

ModoSelect.Option = Select.Option;

export default ModoSelect;