import type { TablePaginationConfig } from "antd";

/**
 * MODO 表格分页统一规范（与 <ModoPagination /> 默认元素集一致）：
 * - 「共 X 条」总数文案（弱化 unit 差异，全站统一"条"）
 * - 页容量切换，固定档位 [10, 20, 50, 100]
 * - 快捷跳页（跳至 X 页）
 * - 常驻右下角 + marginBottom 0（配合白卡分页钉底 CSS：margin-top:auto 推底）
 * - 不随单页数据隐藏（hideOnSinglePage: false）
 *
 * 用法：pagination={modoTablePagination({ current, pageSize, total, onChange })}
 * 需要覆盖时显式传入对应字段（如弹窗小表：{ showSizeChanger: false, showQuickJumper: false }）。
 */
export const MODO_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export function modoTablePagination(config: TablePaginationConfig = {}): TablePaginationConfig {
  return {
    showSizeChanger: true,
    showQuickJumper: true,
    pageSizeOptions: MODO_PAGE_SIZE_OPTIONS,
    showTotal: (total) => `共 ${total} 条`,
    hideOnSinglePage: false,
    position: ["bottomRight"],
    style: { marginBottom: 0 },
    ...config,
  };
}
