/**
 * 主列表表格表体高度测量（全站统一）。
 *
 * 背景：站点级样式（globals.css「全站统一：列表页表格锚点撑满白卡」）把
 * *-table-anchor / *-table-view 拉伸为撑满白卡的 flex 列，分页经 margin-top:auto
 * 钉底。旧公式 `wrapper.height - body.height` 会把拉伸出的空白误算成表格外围
 * chrome，导致表体高度被钳在最小值——表格没占满剩余空间就出现纵向滚动条。
 *
 * 正确算法：表体高度 = 滚动容器可视底部 − 锚点顶部 − 表头 − 分页(含下边距) − 容器边框。
 * 滚动容器底边与表体高度无关，因此无论锚点被 flex 拉伸还是按内容自然高度都稳定收敛。
 *
 * 返回 null 表示表格尚未渲染（无表头），调用方应退回各自的兜底公式。
 */
export function measureTableScrollY(anchor: HTMLElement): number | null {
  const header = anchor.querySelector<HTMLElement>(".ant-table-header");
  if (!header) {
    return null;
  }

  const anchorTop = anchor.getBoundingClientRect().top;
  const headerHeight = header.getBoundingClientRect().height;

  const pagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
  let paginationHeight = 0;
  if (pagination) {
    const marginBottom = parseFloat(getComputedStyle(pagination).marginBottom) || 0;
    paginationHeight = pagination.getBoundingClientRect().height + marginBottom;
  }

  // 底边约束来自最近的可滚动祖先（面板内部滚动时同样适用），而非视口
  let limitBottom = typeof window !== "undefined" ? window.innerHeight : 0;
  let padBottom = 0;
  let node: HTMLElement | null = anchor.parentElement;
  while (node) {
    const overflowY = getComputedStyle(node).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") {
      limitBottom = node.getBoundingClientRect().bottom;
      padBottom = parseFloat(getComputedStyle(node).paddingBottom) || 0;
      break;
    }
    node = node.parentElement;
  }

  // 2px ≈ 表格容器上下边框
  const nextHeight = Math.floor(limitBottom - padBottom - anchorTop - headerHeight - paginationHeight - 2);
  return nextHeight;
}
