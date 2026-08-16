import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fl-analysis/page.tsx");
const CARD_FILE = join(__dirname, "../components/fl-analysis/job-card-list.tsx");
const TABLE_FILE = join(__dirname, "../components/fl-analysis/job-table.tsx");
const TAB_VIEW_FILE = join(__dirname, "../components/fl-analysis/job-detail-tab-view.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const PAGE = readFileSync(PAGE_FILE, "utf-8");
const CARD = readFileSync(CARD_FILE, "utf-8");
const TABLE = readFileSync(TABLE_FILE, "utf-8");
const TAB_VIEW = readFileSync(TAB_VIEW_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-374: 任务列表主 Tab 改为「任务列表」且常驻不可关闭", () => {
  assert.ok(
    PAGE.includes('label: <span className="admin-fl-analysis-tab-title">任务列表</span>'),
    "主 Tab 标题应为「任务列表」",
  );
  assert.ok(
    PAGE.includes("closable: false"),
    "主列表 Tab 应不可关闭",
  );
  assert.ok(
    !PAGE.includes('label: <span className="admin-fl-analysis-tab-title">分级结果</span>'),
    "「分级结果」不再作为页面级主 Tab（移入任务详情 Tab 内）",
  );
});

test("LP-374: 任务列表支持卡片/列表双视图 Segmented 切换", () => {
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

test("LP-374: 列表视图使用 JobTable，卡片视图使用 JobCardList", () => {
  assert.ok(PAGE.includes("import { JobTable }"), "应引入 JobTable");
  assert.ok(PAGE.includes("import { JobCardList }"), "应引入 JobCardList");
  assert.ok(
    PAGE.includes('viewMode === "card" ?'),
    "应按 viewMode 分支渲染卡片/列表视图",
  );
});

test("LP-374: 列表视图 Table 列包含 任务名/线路/类型/状态/创建/完成/杆塔/结果/错误信息", () => {
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
  assert.ok(TABLE.includes("rowClassName"), "列表视图应支持选中行高亮");
  assert.ok(TABLE.includes("onRow"), "点击行应可打开任务详情");
});

test("LP-374: 任务卡片对齐线路管理三段式 AntD Card 结构", () => {
  assert.ok(CARD.includes("<Card"), "卡片应使用 AntD Card 结构（不再自定义 button）");
  assert.ok(
    !CARD.includes("<button"),
    "不应再使用自定义 button 卡片",
  );
  assert.ok(
    CARD.includes("admin-fl-analysis-job-card-title"),
    "卡片应有标题区（admin-fl-analysis-job-card-title）",
  );
  assert.ok(
    CARD.includes("admin-fl-analysis-job-card-actions"),
    "卡片应有按钮区（admin-fl-analysis-job-card-actions）",
  );
  assert.ok(CARD.includes("onSelect(job)"), "卡片点击应回调 job 对象");
});

test("LP-374: 点击任务打开/激活任务详情 Tab，按 job.id 去重", () => {
  assert.ok(
    PAGE.includes("openJobDetailTab"),
    "应存在 openJobDetailTab 打开任务详情 Tab",
  );
  assert.ok(
    PAGE.includes("previous.some((tab) => tab.key === tabKey)"),
    "应按 job.id 去重避免重复叠加 Tab",
  );
  assert.ok(
    PAGE.includes("setActiveTabKey(tabKey)"),
    "打开后应激活对应任务 Tab",
  );
  assert.ok(
    PAGE.includes("JobDetailTabView"),
    "任务 Tab 内容应挂载 JobDetailTabView",
  );
});

test("LP-374: 任务 Tab 内容以打开时 job 快照构建，支持多开", () => {
  assert.ok(
    PAGE.includes("Array<{ key: string; job: FlAnalysisJobSummary }>>"),
    "detailTabs 应以 job 快照存储（key + job）",
  );
  assert.ok(
    PAGE.includes("job={tab.job}"),
    "任务 Tab 内容应以打开时的 job 快照构建",
  );
  assert.ok(
    PAGE.includes("jobs={jobs}"),
    "应传递最新任务列表供复算选择基线任务",
  );
});

test("LP-374: 提交中的任务 Tab 禁止关闭（submittingTabKeys）", () => {
  assert.ok(
    PAGE.includes("submittingTabKeys"),
    "应跟踪提交中的任务 Tab",
  );
  assert.ok(
    PAGE.includes("setTabSubmitting"),
    "应提供提交状态上报回调",
  );
  assert.ok(
    PAGE.includes("submittingTabKeys.has(key)"),
    "提交进行中的任务 Tab 应禁止关闭",
  );
});

test("LP-374: 关闭任务 Tab 按「左邻 → 最左 → 任务列表」回退", () => {
  const block = PAGE.match(/const handleTabsEdit = useCallback[\s\S]*?\},\s*\[submittingTabKeys\]\);/)?.[0];
  assert.ok(block, "应能找到 handleTabsEdit 定义");
  assert.match(block, /next\[Math\.max\(0, removedIndex - 1\)\]\?\.key/, "应优先回退到左邻 Tab");
  assert.match(block, /next\[0\]\?\.key/, "其次回退到最左 Tab");
  assert.match(block, /LIST_TAB_KEY/, "兜底回退到任务列表主 Tab");
  assert.ok(PAGE.includes("detailTabsRef"), "应使用 ref 读取最新 detailTabs");
  assert.ok(PAGE.includes("activeTabKeyRef"), "应使用 ref 读取最新 activeTabKey");
});

test("LP-374: JobDetailTabView 挂载「分级结果」+ 塔详情动态 Tab（LP-274 子级）", () => {
  assert.ok(
    TAB_VIEW.includes('label: <span className="admin-fl-analysis-tab-title">分级结果</span>'),
    "任务 Tab 内应有「分级结果」固定主 Tab",
  );
  assert.ok(
    TAB_VIEW.includes("openTowerDetail"),
    "应支持打开塔详情动态 Tab",
  );
  assert.ok(
    TAB_VIEW.includes("TowerDetailView"),
    "塔详情 Tab 内容应挂载 TowerDetailView",
  );
  assert.ok(
    TAB_VIEW.includes("onSubmittingChange"),
    "任务 Tab 应上报提交状态锁定关闭",
  );
});

test("LP-374: JobDetailTabView 自持详情/结果查询，按 job.id 隔离（防串数据）", () => {
  assert.ok(
    TAB_VIEW.includes('["/api/v1/fl-analysis/jobs/detail", job.id]'),
    "详情查询应按 job.id 隔离",
  );
  assert.ok(
    TAB_VIEW.includes('["/api/v1/fl-analysis/jobs/results", job.id]'),
    "结果查询应按 job.id 隔离",
  );
});

test("LP-374: 启动/下载操作在任务 Tab 内自持（pending 按 Tab 隔离）", () => {
  assert.ok(
    TAB_VIEW.includes("startJobMutation"),
    "任务 Tab 应自持启动 mutation",
  );
  assert.ok(
    TAB_VIEW.includes("downloadResultsMutation"),
    "任务 Tab 应自持结果导出 mutation",
  );
  assert.ok(
    TAB_VIEW.includes("downloadReportMutation"),
    "任务 Tab 应自持报告下载 mutation",
  );
  assert.ok(
    TAB_VIEW.includes("startPending={startJobMutation.isPending}"),
    "启动按钮 pending 应绑定 Tab 内 mutation",
  );
});

test("LP-374: 任务卡片/列表/详情样式有对应全局样式", () => {
  assert.ok(CSS.includes(".admin-fl-analysis-job-card {"), "应存在任务卡片样式");
  assert.ok(CSS.includes(".admin-fl-analysis-job-card-title"), "应存在卡片标题区样式");
  assert.ok(CSS.includes(".admin-fl-analysis-job-card-actions"), "应存在卡片按钮区样式");
  assert.ok(CSS.includes(".admin-fl-analysis-list-toolbar"), "应存在列表工具栏样式");
  assert.ok(CSS.includes(".admin-fl-analysis-job-pane"), "应存在任务详情 Tab 内容容器样式");
  assert.ok(CSS.includes("admin-fl-analysis-job-row-selected"), "应存在列表选中行高亮样式");
});
