import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fault-recurrence/page.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const source = readFileSync(PAGE_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-276: antd Tabs is imported", () => {
  assert.ok(
    /\bTabs\b/.test(source.match(/(?:import\s*\{[\s\S]*?\}\s*from\s*["']antd["'])/)?.[0] ?? ""),
    "页面应从 antd 导入 Tabs",
  );
});

test("LP-276: 结果区改为 editable-card 动态 Tabs 且支持关闭", () => {
  assert.ok(
    /<Tabs\s*[\s\S]*?type="editable-card"[\s\S]*?hideAdd[\s\S]*?onEdit=\{handleTabsEdit\}/.test(source),
    "复现结果外层 Tabs 应为 editable-card + hideAdd + onEdit 可关闭",
  );
  assert.match(source, /className="admin-fault-recurrence-result-tabs"/);
});

test("LP-276: 分析成功将结果追加为新的结果 Tab（文件名 + 状态 Tag）", () => {
  const resultTabBlock = source.match(/onSuccess:\s*\(payload\)\s*=>\s*\{[\s\S]*?\n\s*\},\s*\n\s*onError/)?.[0];
  assert.ok(resultTabBlock, "应存在 onSuccess 回调");
  assert.match(resultTabBlock, /payload\.source_file_name/);
  assert.match(resultTabBlock, /resultTagColor\(payload\.result\.status\)/);
  assert.match(resultTabBlock, /setResultTabs/);
  assert.match(resultTabBlock, /setActiveTabKey/);
});

test("LP-276: 每个结果 Tab 内层静态 Tabs 分组为 结果概览 / 详细数据", () => {
  const viewBlock = source.match(/function FaultRecurrenceResultView[\s\S]*$/)?.[0] ?? "";
  assert.ok(viewBlock.includes("FaultRecurrenceResultView"));
  assert.match(viewBlock, /key:\s*"overview"/);
  assert.match(viewBlock, /key:\s*"detail"/);
  assert.ok(source.includes('label: "结果概览"'));
  assert.ok(source.includes('label: "详细数据"'));
});

test("LP-276: 详情数据 Table 列与数据字段保持完整", () => {
  const viewBlock = source.match(/function FaultRecurrenceResultView[\s\S]*$/)?.[0] ?? "";
  for (const col of ["波头时间 / μs", "波尾时间 / μs", "反击耐雷水平 / kA", "绕击耐雷水平 / kA"]) {
    assert.ok(viewBlock.includes(col), `应保留 ${col} 列`);
  }
  assert.ok(viewBlock.includes("dataSource={result.data_points}"));
});

test("LP-276: 清空结果清空全部结果 Tab", () => {
  const resetBlock = source.match(/const handleReset = \(\) => \{[\s\S]*?\n  \};/)?.[0] ?? "";
  assert.ok(resetBlock.includes("setResultTabs([])"));
  assert.ok(resetBlock.includes('setActiveTabKey("")'));
});

test("LP-276: 未选择文件/选择新文件不再清空已有结果 Tab", () => {
  const fileChangeBlock = source.match(/const handleFileChange = \(event[\s\S]*?\n  \};/)?.[0] ?? "";
  assert.ok(fileChangeBlock.includes("setSelectedFile(nextFile)"));
  assert.ok(!fileChangeBlock.includes("setResult("), "选择新文件不应清空已有结果");
});

test("LP-276: 空状态在无任何结果 Tab 时展示占位", () => {
  assert.ok(source.includes("resultTabs.length === 0"));
  assert.ok(source.includes('Empty description="选择基础数据文件并执行一次复现计算后，将在这里展示结果。"'));
});

test("LP-287: 复现结果外层 Card 已移除，内容放入 list-pane 容器", () => {
  assert.ok(
    !/<Card\s+title="复现结果"/.test(source),
    "不应再存在 <Card title=\"复现结果\"> 外层包裹",
  );
  assert.ok(
    source.includes('className="admin-fault-recurrence-result-pane"'),
    "复现结果内容应使用 list-pane 语义容器 admin-fault-recurrence-result-pane",
  );
  assert.ok(
    source.includes('className="admin-fault-recurrence-tabs"'),
    "外层 Tabs 应使用 admin-fault-recurrence-tabs",
  );
  assert.ok(
    source.includes('<div className="flex min-h-0 flex-1 flex-col">'),
    "页面根部应使用 flex min-h-0 flex-1 flex-col 撑满高度",
  );
});

test("LP-287: 复现结果 list-pane 内容区有纵向滚动样式", () => {
  const block = CSS.match(
    /\.admin-fault-recurrence-result-pane \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-fault-recurrence-result-pane 规则块");
  assert.match(block, /overflow-x:\s*hidden/, "list-pane 应横向隐藏溢出");
  assert.match(block, /overflow-y:\s*auto/, "list-pane 应保留纵向滚动");
  assert.match(block, /padding:\s*12px/, "list-pane 应保留 12px 内边距");
});

test("LP-287: 外层 Tabs 有对应全局样式", () => {
  assert.ok(
    CSS.includes(".admin-fault-recurrence-tabs {"),
    "应存在 .admin-fault-recurrence-tabs 规则块",
  );
  assert.ok(
    CSS.includes(".admin-fault-recurrence-tabs > .ant-tabs-nav {"),
    "应存在 Tab 栏样式规则，保证与容器连成白带",
  );
  assert.ok(
    CSS.includes(".admin-fault-recurrence-tab-title {"),
    "应存在主结果 Tab 标题样式规则",
  );
  const activeBlock = CSS.match(
    /\.admin-fault-recurrence-tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(activeBlock, "应存在 .ant-tabs-tabpane-active 规则块");
  assert.match(activeBlock, /display:\s*flex/, "激活 pane 应保持 flex 布局");
  assert.match(activeBlock, /flex:\s*1/, "激活 pane 应保持 flex:1 撑满");
});