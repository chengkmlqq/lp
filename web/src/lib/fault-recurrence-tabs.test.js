import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fault-recurrence/page.tsx");

const source = readFileSync(PAGE_FILE, "utf-8");

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