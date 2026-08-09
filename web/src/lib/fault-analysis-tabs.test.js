import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fault-analysis/page.tsx");
const FORM_FILE = join(__dirname, "../components/fault-analysis/create-analysis-form-advanced.tsx");
const DETAIL_FILE = join(__dirname, "../components/fault-analysis/analysis-detail-view.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const PAGE = readFileSync(PAGE_FILE, "utf-8");
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
