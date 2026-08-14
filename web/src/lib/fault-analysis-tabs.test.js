import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fault-analysis/page.tsx");
const CARD_FILE = join(__dirname, "../components/fault-analysis/analysis-card.tsx");
const FORM_FILE = join(__dirname, "../components/fault-analysis/create-analysis-form-advanced.tsx");
const DETAIL_FILE = join(__dirname, "../components/fault-analysis/analysis-detail-view.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const PAGE = readFileSync(PAGE_FILE, "utf-8");
const CARD = readFileSync(CARD_FILE, "utf-8");
const FORM = readFileSync(FORM_FILE, "utf-8");
const DETAIL = readFileSync(DETAIL_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-275: 故障分析页面详情不再全页切换，改用动态选项卡", () => {
  assert.ok(
    PAGE.includes('type="editable-card"'),
    "详情展示应使用 editable-card 动态选项卡",
  );
  assert.ok(
    PAGE.includes("className=\"admin-fault-analysis-tabs\""),
    "外层 Tabs 应使用 admin-fault-analysis-tabs",
  );
  assert.ok(
    !PAGE.includes("setViewingId"),
    "不应再存在 viewingId 全页切换状态",
  );
});

test("LP-275: 详情 Tab 以分析 id 去重，支持多开", () => {
  assert.ok(
    PAGE.includes("previous.some((tab) => tab.key === tabKey)"),
    "openDetail 应以分析 id 去重，避免重复叠加 Tab",
  );
  assert.ok(
    PAGE.includes("handleTabsEdit"),
    "应存在 handleTabsEdit 关闭 Tab 逻辑",
  );
  assert.ok(
    PAGE.includes("AnalysisDetailView"),
    "详情 Tab 内容应挂载 AnalysisDetailView",
  );
});

test("LP-275: 新建/编辑 Modal 大尺寸宽度已移除", () => {
  assert.ok(
    !PAGE.includes("width={950}"),
    "不应再存在 950 大尺寸 Modal",
  );
});

test("LP-275: 新建/编辑表单改用 Tabs 分组", () => {
  assert.ok(
    FORM.includes('className="admin-fault-analysis-modal-tabs"'),
    "表单应使用 Tabs 分组（admin-fault-analysis-modal-tabs）",
  );
  assert.ok(FORM.includes('key: "line"'), "应存在“故障线路”Tab");
  assert.ok(FORM.includes('label: "故障线路"'), "故障线路 Tab 标签应为“故障线路”");
  assert.ok(FORM.includes('key: "fault"'), "应存在“故障信息”Tab");
  assert.ok(FORM.includes('label: "故障信息"'), "故障信息 Tab 标签应为“故障信息”");
  assert.ok(FORM.includes('key: "data"'), "应存在“分析数据”Tab");
  assert.ok(FORM.includes('label: "分析数据"'), "分析数据 Tab 标签应为“分析数据”");
});

test("LP-275: 表单字段名与提交逻辑保持不变", () => {
  for (const field of [
    "line_id",
    "station_name",
    "fault_time",
    "fault_line_name",
    "fault_phase",
    "fault_duration",
    "reclosure_status",
    "fault_voltage",
    "fault_current",
    "max_zero_current",
    "zero_compensation",
    "fault_resistance",
    "line_length",
    "line_angle",
    "line_impedance",
    "lightning_current",
    "lightning_longitude",
    "lightning_latitude",
    "wave_distance",
    "traveling_wave_distance",
    "optical_position",
    "optical_device_location",
    "wave_data_file",
    "lightning_data_file",
    "traveling_wave_file",
    "optical_data_file",
  ]) {
    assert.ok(FORM.includes(`name="${field}"`), `表单应保留字段 ${field}`);
  }
});

test("LP-275: 详情导出容器使用唯一 id 前缀（多开详情 Tab 不冲突）", () => {
  assert.ok(
    DETAIL.includes("analysis-export-content-${tabKey}"),
    "详情导出容器 id 应带 tabKey 前缀避免重复",
  );
  assert.ok(
    DETAIL.includes("exportElementId"),
    "PDF 导出应使用带前缀的容器 id",
  );
  assert.ok(
    !DETAIL.includes("onBack"),
    "详情视图不应再依赖返回列表回调（由 Tab 关闭接管）",
  );
});

test("LP-275: 动态选项卡有对应全局样式", () => {
  const block = CSS.match(
    /\.admin-fault-analysis-tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-fault-analysis-tabs .ant-tabs-tabpane-active 规则块");
  assert.match(block, /display:\s*flex/, "激活 pane 应保持 flex 布局");
  assert.match(block, /flex:\s*1/, "激活 pane 应保持 flex:1 撑满");
  assert.ok(
    CSS.includes(".admin-fault-analysis-tabs > .ant-tabs-nav {"),
    "应存在 Tab 栏样式规则，保证与 Card 头部连成白带",
  );
  assert.ok(
    CSS.includes(".admin-fault-analysis-tab-title {"),
    "应存在主列表 Tab 标题样式规则",
  );
});

test("LP-275: 表单 Modal Tabs 有对应全局样式", () => {
  const block = CSS.match(
    /\.admin-fault-analysis-modal-tabs \.ant-tabs-nav \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-fault-analysis-modal-tabs .ant-tabs-nav 规则块");
  assert.match(block, /margin:\s*0\s+0\s+12px/, "Tabs 导航栏应保留简洁间距");
});

test("LP-285: 列表内容区 list-pane 有纵向滚动样式", () => {
  const block = CSS.match(
    /\.admin-fault-analysis-list-pane \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-fault-analysis-list-pane 规则块");
  assert.match(block, /overflow-x:\s*hidden/, "list-pane 应横向隐藏溢出");
  assert.match(block, /overflow-y:\s*auto/, "list-pane 应保留纵向滚动");
  assert.match(block, /padding:\s*12px/, "list-pane 应保留 12px 内边距");
});

test("LP-319: 故障分析页 Tabs 外壳化并迁入新建按钮", () => {
  assert.ok(
    !PAGE.includes("admin-fault-analysis-page-card"),
    "页面不应再使用 admin-fault-analysis-page-card 外层 Card",
  );
  assert.ok(!PAGE.includes("<Card"), "Tabs 不应再包裹在 Card 组件内");
  assert.ok(PAGE.includes("tabBarExtraContent"), "新建分析按钮应迁入 Tabs.tabBarExtraContent");
  assert.ok(PAGE.includes("canManage ?"), "新建/管理操作应保留 canManage 权限门控");
  assert.ok(
    !CSS.includes(".admin-fault-analysis-page-card"),
    "全局样式应删除外层 Card 相关规则",
  );
});

test("LP-319: 故障分析页支持卡片/列表双视图与表格操作列", () => {
  assert.ok(PAGE.includes("Segmented"), "过滤栏应包含 Segmented 视图切换");
  assert.ok(PAGE.includes('useState<"card" | "list">("card")'), "默认应为卡片视图");
  assert.ok(PAGE.includes("Table<FaultAnalysis>"), "列表视图应使用 antd Table");
  assert.ok(PAGE.includes("ColumnsType<FaultAnalysis>"), "表格列定义应使用 FaultAnalysis 类型");
  assert.ok(PAGE.includes("FAULT_STATUS_META"), "状态枚举应收敛为页面级常量");
  assert.ok(PAGE.includes("FAULT_RISK_META"), "风险枚举应收敛为页面级常量");
  assert.ok(PAGE.includes("Dropdown"), "删除操作应收进三点 Dropdown");
  assert.ok(PAGE.includes("MoreOutlined"), "三点菜单应使用 MoreOutlined 图标");
  assert.ok(PAGE.includes('fixed: "right"'), "操作列应固定在右侧");
});

test("LP-319: 故障分析列表视图有动态表格高度锚点", () => {
  for (const constant of [
    "FAULT_TABLE_MIN_SCROLL_Y",
    "FAULT_TABLE_ESTIMATED_HEADER_HEIGHT",
    "FAULT_TABLE_ESTIMATED_PAGINATION_HEIGHT",
    "FAULT_TABLE_BOTTOM_GAP",
  ]) {
    assert.ok(PAGE.includes(constant), `应定义 ${constant} 表格高度常量`);
  }
  assert.ok(PAGE.includes("updateTableScrollHeight"), "应存在表格滚动高度测量函数");
  assert.ok(PAGE.includes("ResizeObserver"), "应监听锚点容器尺寸变化");
  assert.ok(PAGE.includes("tableScrollAnchorRef"), "列表表格应挂载高度锚点 ref");
  assert.ok(PAGE.includes("admin-fault-analysis-table-anchor"), "列表表格应使用故障分析锚点类");
  assert.ok(PAGE.includes("--admin-fault-analysis-table-body-min-height"), "表格 body 最小高度应通过 CSS 变量传入");
});

test("LP-319: 故障分析卡片视图抽象为统一滚动和分页容器", () => {
  for (const className of [
    ".admin-fault-analysis-table-anchor",
    ".admin-fault-analysis-table-anchor .ant-table-body",
    ".admin-fault-analysis-card-view",
    ".admin-fault-analysis-card-scroll",
    ".admin-fault-analysis-card-scroll > .grid",
    ".admin-fault-analysis-pagination",
  ]) {
    assert.ok(CSS.includes(className), `全局样式应包含 ${className}`);
  }
  assert.ok(PAGE.includes('className="admin-fault-analysis-card-view"'), "卡片视图应使用统一容器类");
  assert.ok(PAGE.includes('className="admin-fault-analysis-card-scroll"'), "卡片列表应使用统一滚动类");
  assert.ok(PAGE.includes('className="admin-fault-analysis-pagination"'), "分页区域应使用统一分页类");
  assert.ok(!PAGE.includes("overflowY: 'auto'"), "卡片滚动不应继续使用内联 overflowY 样式");
});

test("LP-319: 故障分析卡片编辑和删除按钮按处理器存在性渲染", () => {
  assert.ok(CARD.includes("onEdit &&"), "编辑按钮应仅在传入 onEdit 时渲染");
  assert.ok(CARD.includes("onDelete &&"), "删除按钮应仅在传入 onDelete 时渲染");
  assert.ok(PAGE.includes("onEdit={canManage ? handleEdit : undefined}"), "卡片视图编辑入口应受 canManage 门控");
  assert.ok(PAGE.includes("onDelete={canManage ? handleDelete : undefined}"), "卡片视图删除入口应受 canManage 门控");
});
