"use client";

import React from "react";
import { Pagination } from "antd";
import type { PaginationProps } from "antd";
import styles from "./modo-pagination.module.css";

export interface ModoPaginationProps extends Omit<PaginationProps, "style"> {
  containerClassName?: string;
  /** 作用于外层容器（如 marginTop: "auto" 把分页推到 flex 容器底部） */
  style?: React.CSSProperties;
}

/**
 * ModoPagination — 常驻底栏分页（对齐 data-synth 的 modo-pagination 实现）。
 * 与 <ModoTable /> 配套使用：表格 flex:1 占满剩余高度，分页 flex-shrink:0 固定在底部。
 * 统一规范：容器自带 padding 10px 16px 8px，距页面（卡片）底部间距固定 8px。
 */
export const ModoPagination: React.FC<ModoPaginationProps> = ({
  showSizeChanger = true,
  showQuickJumper = true,
  showTotal = (total) => `共 ${total} 条`,
  containerClassName,
  style,
  ...props
}) => {
  return (
    <div
      className={
        containerClassName
          ? `${styles["pagination-container"]} ${containerClassName}`
          : styles["pagination-container"]
      }
      style={style}
    >
      <Pagination
        showSizeChanger={showSizeChanger}
        showQuickJumper={showQuickJumper}
        showTotal={showTotal}
        {...props}
      />
    </div>
  );
};

export default ModoPagination;
