import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const SOURCE = readFileSync(PAGE_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-302: detail tab title keeps only file name (no status Tag)", () => {
  const openDetailBlock = SOURCE.match(/const openDetail = useCallback[\s\S]*?\},\s*\[fetchWithAuth, canReadLogs, openLogViewer\]\);/);
  assert.ok(openDetailBlock, "应能找到 openDetail 定义");
  const block = openDetailBlock[0];
  assert.ok(
    /label:\s*<span>\{truncateFileName\(record\.source_file_name\)\}<\/span>/.test(block),
    "详情 Tab 标题应仅保留文件名",
  );
  assert.ok(
    !/<Tag color=\{meta\.color\}>\{meta\.label\}<\/Tag>/.test(block),
    "详情 Tab 标题不应再包含状态标签 Tag",
  );
});

test("LP-302: detail view wrapped in 12px-padded scrollable container", () => {
  assert.ok(
    /<div className="admin-lightning-distribution-detail-view">/.test(SOURCE),
    "详情内容应包裹在 admin-lightning-distribution-detail-view 容器中",
  );
  const rule = CSS.match(
    /\.admin-lightning-distribution-detail-view \s*\{([^}]*)\}/,
  )?.[1];
  assert.ok(rule, "globals.css 中应存在 .admin-lightning-distribution-detail-view 规则");
  assert.match(rule, /padding:\s*12px/, "容器应有 12px 内边距");
  assert.match(rule, /overflow-y:\s*auto/, "内容超高时应出现纵向滚动条");
});

test("LP-302: processing logs rendered as a Table with operation column", () => {
  const logsTabBlock = SOURCE.match(/label: "处理日志"[\s\S]*?<Table<DistributionLogRow>[\s\S]*?\/>/) ?? [];
  const logs = logsTabBlock[0] ?? "";
  assert.ok(logs.length > 0, "应存在「处理日志」Tab");
  assert.ok(
    /<Table<DistributionLogRow>/.test(logs),
    "处理日志应使用 Table 呈现",
  );
  assert.ok(/dataSource=\{logRows\}/.test(logs), "表格数据源应为构造的处理记录数组");
  assert.ok(/title: "操作"/.test(SOURCE), "表格应包含「操作」列");
  assert.ok(/onOpenLog\(row\.taskId, row\.logLabel, row\.fileName\)/.test(SOURCE), "操作列应提供查看日志按钮");
});
