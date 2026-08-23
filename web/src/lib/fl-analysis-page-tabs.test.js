import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fl-analysis/page.tsx");
const CARD_FILE = join(__dirname, "../components/fl-analysis/job-card-list.tsx");
const TABLE_FILE = join(__dirname, "../components/fl-analysis/job-table.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const PAGE = readFileSync(PAGE_FILE, "utf-8");
const CARD = readFileSync(CARD_FILE, "utf-8");
const TABLE = readFileSync(TABLE_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-377: 页面骨架对齐线路管理——去外层 Card，Tabs 白带 Tab 栏承载标题", () => {
  assert.ok(
    PAGE.includes('className="admin-fl-analysis-tabs"'),
    "应使用 admin-fl-analysis-tabs 白带 Tabs 结构",
  );
  assert.ok(
    PAGE.includes('label: <span className="admin-fl-analysis-tab-title">防雷计算</span>'),
    "列表主 Tab 标题应为「防雷计算」",
  );
  assert.ok(PAGE.includes("closable: false"), "主列表 Tab 应不可关闭");
  assert.ok(
    !PAGE.includes("防雷分析与改造") && !PAGE.includes('<Card>\n          <div className="flex flex-col gap-3'),
    "不应再存在外层 Header Card",
  );
});

test("LP-377: 「新建任务」按钮移入 tabBarExtraContent 且仅 canManage 显示", () => {
  assert.ok(
    PAGE.includes("tabBarExtraContent="),
    "应使用 tabBarExtraContent 放置新建按钮",
  );
  assert.match(PAGE, /canManage\s*&&[\s\S]{0,120}新建任务/, "新建按钮应受 canManage 控制");
  assert.ok(
    !PAGE.includes("<Button\n                type=\"primary\"\n                onClick={() => {\n                  setCreateModalOpen(true);\n                }\n              >\n                新建任务"),
    "外层 Card 内的新建按钮应已移除",
  );
});

test("LP-377: 登录/权限态改为 AdminPageLoading + Card + 返回首页按钮", () => {
  assert.ok(PAGE.includes("import { AdminPageLoading }"), "应引入 AdminPageLoading");
  assert.ok(
    PAGE.includes("<AdminPageLoading tip="),
    "初始化中应渲染 AdminPageLoading",
  );
  assert.ok(PAGE.includes("import Link from \"next/link\""), "应引入 Link 返回首页");
  assert.ok(
    /!user\)\s*\{\s*return\s*\(\s*<Card>[\s\S]{0,300}返回首页/.test(PAGE),
    "未登录态应返回 Card + 返回首页按钮",
  );
  assert.ok(
    /!canRead\)\s*\{\s*return\s*\(\s*<Card>[\s\S]{0,300}返回首页/.test(PAGE),
    "无权限态应返回 Card + 返回首页按钮",
  );
  assert.ok(
    !PAGE.includes('<Alert type="warning" showIcon message="请先登录后查看防雷分析结果。" />'),
    "裸 Alert 登录态应移除",
  );
});

test("LP-377: 任务列表支持卡片/列表双视图 Segmented 切换", () => {
  assert.ok(PAGE.includes("<Segmented"), "应使用 Segmented 视图切换");
  assert.ok(
    PAGE.includes('useState<"card" | "list">("card")'),
    "默认应为卡片视图 viewMode",
  );
  assert.ok(
    PAGE.includes('{ label: "卡片视图", value: "card" }'),
    "Segmented 应包含卡片视图选项",
  );
  assert.ok(
    PAGE.includes('{ label: "列表视图", value: "list" }'),
    "Segmented 应包含列表视图选项",
  );
});

test("LP-377: 列表视图使用 JobTable，卡片视图使用 JobCardList", () => {
  assert.ok(PAGE.includes("import { JobTable }"), "应引入 JobTable");
  assert.ok(PAGE.includes("import { JobCardList }"), "应引入 JobCardList");
  assert.ok(
    PAGE.includes('viewMode === "card" ?'),
    "应按 viewMode 分支渲染卡片/列表视图",
  );
});

test("LP-377: 列表视图 Table 列包含 任务名/线路/类型/状态/创建/完成/杆塔/结果/错误信息", () => {
  for (const column of [
    "任务名",
    "线路",
    "任务类型",
    "状态",
    "创建时间",
    "完成时间",
    "杆塔数",
    "结果数",
    "错误信息",
  ]) {
    assert.ok(TABLE.includes(`"${column}"`), `JobTable 应包含 ${column} 列`);
  }
  assert.ok(TABLE.includes("scrollY"), "JobTable 应支持动态 scrollY 高度");
  assert.match(TABLE, /scroll=\{\{ x: 1200, y: scrollY \}\}/, "表格应绑定动态纵向滚动高度");
});

test("LP-xxx: 防雷计算任务列表支持查看日志", () => {
  assert.ok(PAGE.includes("TaskLogViewerDrawer"), "页面应引入 TaskLogViewerDrawer");
  assert.ok(PAGE.includes("canReadLogs"), "页面应声明 celery 日志读取权限");
  assert.ok(
    PAGE.includes('canReadLogs={canReadLogs} onOpenLog={openLogViewer}'),
    "页面应向下传递日志读取能力",
  );
  assert.ok(
    CARD.includes("查看日志") && CARD.includes("onOpenLog?."),
    "卡片视图应在有权限时提供「查看日志」入口",
  );
  assert.ok(
    TABLE.includes("查看日志") && TABLE.includes("onOpenLog(job.task_id"),
    "列表视图应在有权限时提供「查看日志」入口",
  );
});

test("LP-377: 任务卡片 grid 列数对齐线路管理（md:2 xl:4）", () => {
  assert.ok(
    CARD.includes('md:grid-cols-2 xl:grid-cols-4'),
    "grid 应为 md:grid-cols-2 xl:grid-cols-4",
  );
  assert.ok(
    !CARD.includes('xl:grid-cols-3 2xl:grid-cols-4'),
    "不应再使用 xl:grid-cols-3 2xl:grid-cols-4",
  );
});

test("LP-377: 任务卡片使用 AntD Card + Empty PRESENTED_IMAGE_SIMPLE", () => {
  assert.ok(CARD.includes("<Card"), "卡片应使用 AntD Card 结构");
  assert.ok(
    CARD.includes("Empty.PRESENTED_IMAGE_SIMPLE"),
    "空态应使用 Empty.PRESENTED_IMAGE_SIMPLE",
  );
  assert.ok(
    CARD.includes("admin-fl-analysis-job-card-title"),
    "卡片应有标题区（admin-fl-analysis-job-card-title）",
  );
});

test("LP-377: 卡片滚动容器 + 底部 Pagination 对齐线路管理", () => {
  assert.ok(
    PAGE.includes('className="admin-power-lines-card-scroll"'),
    "卡片视图应使用 admin-power-lines-card-scroll 滚动容器",
  );
  assert.ok(
    PAGE.includes('className="admin-power-lines-pagination"'),
    "卡片视图底部应有 admin-power-lines-pagination 分页条",
  );
  assert.ok(
    PAGE.includes("showTotal={(total) => `共 ${total} 条`}"),
    "分页条应展示总条数",
  );
});

test("LP-377: 列表视图挂载动态滚动锚点容器 + CSS 变量", () => {
  assert.ok(
    PAGE.includes("tableScrollAnchorRef"),
    "页面应有表格滚动锚点 ref",
  );
  assert.ok(
    PAGE.includes("--admin-fl-analysis-table-body-min-height"),
    "应使用 admin-fl-analysis 专用表格高度 CSS 变量",
  );
  assert.ok(
    PAGE.includes("ResizeObserver"),
    "应使用 ResizeObserver 监听表格容器尺寸",
  );
  assert.ok(
    PAGE.includes("tableScrollY"),
    "应存在 tableScrollY 状态驱动滚动高度",
  );
});

test("LP-377: 实时刷新订阅 admin.fl-analysis topic", () => {
  assert.ok(PAGE.includes("useTopicSubscription"), "应使用 useTopicSubscription");
  assert.ok(
    PAGE.includes('useTopicSubscription("admin.fl-analysis"'),
    "应订阅 admin.fl-analysis topic",
  );
});

test("LP-377: 反馈统一使用 useToastFeedback + App.useApp", () => {
  assert.ok(PAGE.includes("useToastFeedback"), "应使用 useToastFeedback");
  assert.ok(PAGE.includes("App.useApp()"), "应使用 App.useApp 获取 message");
  assert.ok(
    !PAGE.includes("message.useMessage()"),
    "不应再散用 message.useMessage",
  );
});

test("LP-377: 相关样式存在——list-pane flex 链、filter-bar、卡片标题淡背景、表格高度", () => {
  assert.ok(CSS.includes(".admin-fl-analysis-list-pane {"), "应存在列表 pane 样式");
  const listPaneBlock = CSS.match(/\.admin-fl-analysis-list-pane \{([^}]*)\}/)?.[1];
  assert.ok(listPaneBlock, "应能提取 list-pane 规则块");
  assert.match(listPaneBlock, /display:\s*flex/, "list-pane 应为 flex");
  assert.match(listPaneBlock, /flex:\s*1/, "list-pane 应 flex:1");
  assert.ok(PAGE.includes('className="admin-filter-bar"'), "工具栏应使用 admin-filter-bar");

  const titleBlock = CSS.match(/^\.admin-fl-analysis-job-card-title \{([^}]*)\}/m)?.[1];
  assert.ok(titleBlock, "应存在卡片标题区样式");
  assert.match(titleBlock, /min-height:\s*44px/, "卡片标题区应 min-height:44px");
  assert.match(
    titleBlock,
    /background:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)\s*6%,\s*transparent\)/,
    "卡片标题区应有浅色主色淡背景",
  );

  assert.ok(CSS.includes(".admin-fl-analysis-table-view {"), "应存在表格视图样式");
  assert.ok(
    CSS.includes(".admin-fl-analysis-table-view .ant-table-body {"),
    "应存在表格 body 最小高度规则",
  );
});
