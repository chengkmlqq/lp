"use client";

import { Select } from "antd";

type CreatableSingleSelectProps = {
  allowClear?: boolean;
  disabled?: boolean;
  options: Array<{ label: string; value: string }>;
  placeholder?: string;
  value?: string | null;
  onChange?: (value: string) => void;
};

export function CreatableSingleSelect({
  allowClear = true,
  disabled,
  options,
  placeholder,
  value,
  onChange,
}: CreatableSingleSelectProps) {
  const normalizedValue = value !== null && value !== undefined && value !== "" ? [value] : [];

  return (
    <Select
      allowClear={allowClear}
      disabled={disabled}
      mode="tags"
      maxCount={1}
      options={options}
      placeholder={placeholder}
      value={normalizedValue}
      onChange={(nextValue) => {
        if (Array.isArray(nextValue)) {
          if (nextValue.length === 0) {
            onChange?.("");
          } else {
            onChange?.(nextValue[nextValue.length - 1] ?? "");
          }
        }
      }}
      tokenSeparators={[","]}
    />
  );
}
