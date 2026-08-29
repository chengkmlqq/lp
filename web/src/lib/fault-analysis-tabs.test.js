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

test("LP-507: 故障分析页面不再使用动态选项卡，改用 Modal 弹窗", () => {
  assert.ok(!PAGE.includes('type="editable-card"'), "页面不应再使用 editable-card Tabs");
  assert.ok(!PAGE.includes("admin-fault-analysis-tabs"), "页面不应再使用 admin-fault-analysis-tabs");
  assert.ok(PAGE.includes("detailModalOpen"), "页面应维护详情弹窗状态");
  assert.ok(PAGE.includes("createModalOpen"), "页面应维护新建弹窗状态");
  assert.ok(PAGE.includes("editModalOpen"), "页面应维护编辑弹窗状态");
  assert.ok(PAGE.includes("detailAnalysisId"), "详情弹窗应记录当前分析 id");
  assert.ok(PAGE.includes("editAnalysisId"), "编辑弹窗应记录当前编辑 id");
  assert.ok(!PAGE.includes("detailTabs"), "页面应移除 detailTabs 状态");
  assert.ok(!PAGE.includes("activeTabKey"), "页面应移除 activeTabKey 状态");
  assert.ok(!PAGE.includes("handleTabsEdit"), "页面应移除 Tab 关闭逻辑");
  assert.ok(!PAGE.includes("closeTab"), "页面应移除 closeTab 逻辑");
});

test("LP-507: 详情弹窗使用 AnalysisDetailView 且支持默认视图", () => {
  assert.ok(PAGE.includes("AnalysisDetailView"), "详情弹窗应挂载 AnalysisDetailView");
  assert.ok(PAGE.includes("detailDefaultView"), "页面应维护详情默认视图");
  assert.ok(PAGE.includes('title="故障分析详情"'), "详情弹窗应显示标题");
  assert.ok(PAGE.includes("destroyOnClose"), "详情弹窗应关闭时销毁内容");
  assert.ok(PAGE.includes("footer={null}"), "详情弹窗应移除默认底部按钮");
});

test("LP-507: 新建/编辑弹窗使用 CreateAnalysisFormTab 并保持提交状态", () => {
  assert.ok(PAGE.includes("CreateAnalysisFormTab"), "新建/编辑弹窗应挂载 CreateAnalysisFormTab");
  assert.ok(PAGE.includes('title="新建故障分析"'), "应存在新建弹窗");
  assert.ok(PAGE.includes('title="编辑故障分析"'), "应存在编辑弹窗");
  assert.ok(PAGE.includes("confirmLoading={submittingCreate}"), "新建弹窗应展示提交状态");
  assert.ok(PAGE.includes("confirmLoading={submittingEdit}"), "编辑弹窗应展示提交状态");
  assert.ok(PAGE.includes("handleCreateSubmit"), "新建提交应由页面级函数接管");
  assert.ok(PAGE.includes("handleEditSubmit"), "编辑提交应由页面级函数接管");
});

test("LP-507: 详情按钮改为打开弹窗，操作列保留计算过程/产物/编辑/删除", () => {
  assert.ok(PAGE.includes("openDetailModal"), "详情按钮应打开详情弹窗");
  assert.ok(PAGE.includes('onClick={() => openDetail(row)}'), "详情按钮应触发详情弹窗");
  assert.ok(PAGE.includes('onClick={() => openDetail(row, "process")}'), "计算过程按钮应打开详情弹窗");
  assert.ok(PAGE.includes('label: "产物"'), "三点菜单应保留产物入口");
  assert.ok(PAGE.includes('label: "编辑"'), "三点菜单应保留编辑入口");
  assert.ok(PAGE.includes('label: "删除"'), "三点菜单应保留删除入口");
});

test("LP-507: 产物平铺为表格，产物视图使用 Table 不再依赖 Tree", () => {
  assert.ok(!DETAIL.includes("Tree"), "产物视图应移除 Tree 目录展示");
  assert.ok(DETAIL.includes("buildArtifactRows"), "产物应通过平铺行构建器生成");
  assert.ok(DETAIL.includes("ArtifactRow"), "产物行应拥有结构化类型");
  assert.ok(DETAIL.includes("Table<ArtifactRow>"), "产物应使用 antd Table 平铺展示");
  assert.ok(DETAIL.includes("产物名称"), "产物表格应包含产物名称列");
  assert.ok(DETAIL.includes("产物类型"), "产物表格应包含产物类型列");
  assert.ok(DETAIL.includes("文件路径"), "产物表格应包含文件路径列");
  assert.ok(DETAIL.includes("extension"), "产物表格应包含后缀列");
  assert.ok(DETAIL.includes('onDownload={handleDownloadArtifact}'), "产物行应保留下载能力");
  assert.ok(DETAIL.includes("downloadObject"), "产物下载逻辑应保留");
});

test("LP-507: 详情视图保持 report/process/artifacts 三种视图", () => {
  assert.ok(DETAIL.includes('defaultView="report"'), "详情默认视图应为 report");
  assert.ok(DETAIL.includes("activeView === \"report\""), "应渲染 report 视图");
  assert.ok(DETAIL.includes("activeView === \"process\""), "应渲染 process 视图");
  assert.ok(DETAIL.includes("activeView === \"artifacts\""), "应渲染 artifacts 视图");
});

test("LP-507: 列表页保留卡片/列表双视图与过滤/分页能力", () => {
  assert.ok(PAGE.includes("Segmented"), "过滤栏应包含 Segmented 视图切换");
  assert.ok(PAGE.includes('useState<"card" | "list">("card")'), "默认应为卡片视图");
  assert.ok(PAGE.includes("Table<FaultAnalysis>"), "列表视图应使用 antd Table");
  assert.ok(PAGE.includes("ColumnsType<FaultAnalysis>"), "表格列定义应使用 FaultAnalysis 类型");
  assert.ok(PAGE.includes("FAULT_STATUS_META"), "状态枚举应收敛为页面级常量");
  assert.ok(PAGE.includes("Dropdown"), "删除操作应收进三点 Dropdown");
  assert.ok(PAGE.includes("MoreOutlined"), "三点菜单应使用 MoreOutlined 图标");
  assert.ok(PAGE.includes('fixed: "right"'), "操作列应固定在右侧");
});

test("LP-507: 列表视图有动态表格高度锚点", () => {
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

test("LP-507: 卡片视图保留统一滚动和分页容器", () => {
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
  assert.ok(PAGE.includes('className="admin-fault-analysis-card-scroll"'), "卡片视图应使用滚动容器类");
});

test("LP-507: 列表内容区 list-pane 样式保留", () => {
  const block = CSS.match(
    /\.admin-fault-analysis-list-pane \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-fault-analysis-list-pane 规则块");
  assert.match(block, /overflow-x:\s*hidden/, "list-pane 应横向隐藏溢出");
  assert.match(block, /overflow-y:\s*auto/, "list-pane 应保留纵向滚动");
  assert.match(block, /padding:\s*12px/, "list-pane 应保留 12px 内边距");
});
