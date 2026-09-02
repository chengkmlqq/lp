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

test("LP-348: 新建/编辑表单不再使用内层 Tabs，改为纵向三分区", () => {
  assert.ok(
    !FORM.includes('className="admin-fault-analysis-modal-tabs"'),
    "表单不应再使用 admin-fault-analysis-modal-tabs 内层 Tabs",
  );
  assert.ok(
    !FORM.includes("<Tabs"),
    "表单不应再嵌套内层 Tabs",
  );
  assert.ok(
    !FORM.includes("admin-fault-analysis-form-section-title"),
    "各步骤区块标题已移除（步骤名由 STEP_TITLES 提供）",
  );
  assert.ok(
    !FORM.includes(">故障线路</div>"),
    "故障线路区块标题已移除（步骤名由 STEP_TITLES 提供）",
  );
  assert.ok(
    !FORM.includes("<span>故障信息</span>"),
    "故障信息区块标题已移除（步骤名由 STEP_TITLES 提供）",
  );
  assert.ok(
    !FORM.includes(">分析数据</div>"),
    "分析数据区块标题已移除（步骤名由 STEP_TITLES 提供）",
  );
  assert.ok(
    FORM.includes("htmlType=\"submit\""),
    "表单底部应提供提交按钮",
  );
  assert.ok(
    FORM.includes("loading={submitting}"),
    "提交按钮应展示 submitting 加载态",
  );
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

test("LP-348: 新建/编辑表单纵向分区有对应全局样式", () => {
  assert.ok(
    CSS.includes(".admin-fault-analysis-form-tab-pane {"),
    "应存在 Tab 内表单容器样式（admin-fault-analysis-form-tab-pane）",
  );
  const titleBlock = CSS.match(
    /\.admin-fault-analysis-form-section-title \{([^}]*)\}/,
  )?.[1];
  assert.ok(titleBlock, "应存在表单分区标题样式规则");
  assert.match(titleBlock, /font-weight:\s*600/, "分区标题应加粗");
  assert.ok(
    CSS.includes(".admin-fault-analysis-form-actions {"),
    "应存在表单提交按钮区域样式",
  );
  assert.ok(
    !CSS.includes(".admin-fault-analysis-modal-tabs"),
    "不应再存在 modal-tabs 内层 Tabs 样式",
  );
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
  assert.ok(PAGE.includes("MoreOutlined"), "操作列应使用 ⋯ 三点下拉（对齐雷电流幅值页）");
  assert.ok(
    PAGE.includes('key: "analysis-log"') && PAGE.includes('label: "分析日志"'),
    "日志入口应收进 ⋯ 下拉菜单",
  );
  assert.ok(
    PAGE.includes('key: "delete"') && PAGE.includes("danger: true"),
    "删除应收进 ⋯ 下拉并保留危险样式",
  );
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

test("LP-319: 故障分析卡片删除/日志入口按处理器存在性渲染（收进 ⋯ 下拉）", () => {
  assert.ok(CARD.includes("...(onDelete"), "删除入口应仅在传入 onDelete 时渲染（收进 ⋯ 下拉）");
  assert.ok(
    CARD.includes("...(onLog && analysis.task_id"),
    "日志入口应仅在传入 onLog 且存在 task_id 时渲染（收进 ⋯ 下拉）",
  );
  assert.ok(PAGE.includes("onDelete={canManage ? handleDelete : undefined}"), "卡片视图删除入口应受 canManage 门控");
  assert.ok(!CARD.includes("onEdit"), "编辑入口已移除，卡片不应再接收 onEdit");
});

test("LP-546: 新建表单改为固定高度分步抽屉，不再走 Tab", () => {
  assert.ok(
    PAGE.includes("createModalOpen"),
    "应存在 createModalOpen 状态",
  );
  assert.ok(
    PAGE.includes("openCreateModal"),
    "应存在 openCreateModal 打开新建表单",
  );
  assert.ok(
    PAGE.includes("<Drawer"),
    "新建表单应使用 Drawer 抽屉承载",
  );
  assert.ok(
    !PAGE.includes("openCreateTab"),
    "不应再存在 openCreateTab 打开新建 Tab 的逻辑",
  );
  assert.ok(
    !PAGE.includes("CREATE_TAB_KEY"),
    "不应再存在新建 Tab 固定 key 常量",
  );
  assert.ok(
    !PAGE.includes("EDIT_TAB_KEY_PREFIX"),
    "不应再存在编辑 Tab key 前缀常量",
  );
  assert.ok(
    PAGE.includes("CreateAnalysisFormTab"),
    "抽屉内容应挂载 CreateAnalysisFormTab",
  );
  assert.ok(
    PAGE.includes('mode="create"'),
    "新建抽屉应使用 CreateAnalysisFormTab 创建模式",
  );
  assert.ok(
    !PAGE.includes('mode="edit"'),
    "编辑入口已移除，不应再存在编辑模式渲染",
  );
});

test("LP-546: 提交成功自动关闭新建抽屉，提交中禁止关闭", () => {
  assert.ok(
    PAGE.includes("setCreateModalOpen(false)"),
    "新建成功后应关闭新建抽屉（回到列表）",
  );
  assert.ok(
    PAGE.includes("handleCreateSuccess"),
    "新建成功应刷新列表并关闭抽屉",
  );
  assert.ok(
    PAGE.includes("formModalSubmitting"),
    "应跟踪抽屉提交状态以禁止关闭",
  );
  assert.ok(
    PAGE.includes("onSubmittingChange={setFormModalSubmitting}"),
    "抽屉提交状态应回传页面",
  );
  assert.ok(
    PAGE.includes("keyboard={false}"),
    "抽屉应禁止 Esc 误关（提交中防丢失）",
  );
});

test("LP-393: 详情动态 Tab 标签去掉故障类型结果标签", () => {
  const labelBlock = PAGE.match(
    /const tabLabel = defaultView/,
  )?.[0];
  assert.ok(labelBlock, "详情 Tab 标签应通过 tabLabel 统一计算（默认/计算过程/产物）");
  assert.ok(
    !PAGE.includes('<Tag color="blue">{record.fault_type}</Tag>'),
    "详情 Tab 标签不应再渲染故障类型结果标签",
  );
});

test("LP-393: 列表主 Tab 标题改为「故障分析」", () => {
  assert.ok(
    PAGE.includes(
      'label: <span className="admin-fault-analysis-tab-title">故障分析</span>',
    ),
    "列表主 Tab 标题应为「故障分析」",
  );
  assert.ok(
    !PAGE.includes("故障分析列表"),
    "不应再存在「故障分析列表」文案",
  );
});

