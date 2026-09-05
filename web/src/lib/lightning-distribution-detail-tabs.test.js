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
  const openDetailBlock = SOURCE.match(/const openDetail = useCallback[\s\S]*?\},\s*\[fetchWithAuth\]\);/);
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

test("LP-302: detail view wrapped in 10px-padded scrollable container", () => {
  assert.ok(
    /<div className="admin-lightning-distribution-detail-view">/.test(SOURCE),
    "详情内容应包裹在 admin-lightning-distribution-detail-view 容器中",
  );
  const rule = CSS.match(
    /\.admin-lightning-distribution-detail-view \s*\{([^}]*)\}/,
  )?.[1];
  assert.ok(rule, "globals.css 中应存在 .admin-lightning-distribution-detail-view 规则");
  assert.match(rule, /padding:\s*10px/, "容器应保持与线路管理页详情报一致的 10px 内边距");
  assert.match(rule, /overflow-y:\s*auto/, "内容超高时应出现纵向滚动条");
});

test("LP-401: 详情页仅保留网格图，不再使用选项卡组件", () => {
  const detailViewBlock = SOURCE.match(
    /function DistributionDetailView\([\s\S]*?<\/div>\n  \);\n\}/,
  )?.[0] ?? "";
  assert.ok(detailViewBlock.length > 0, "应能找到 DistributionDetailView 组件定义");
  assert.ok(
    /<DistributionImagePane[\s\S]*?query=\{imageQuery\}/.test(detailViewBlock),
    "详情页应直接渲染均匀网格图（DistributionImagePane + imageQuery）",
  );
  assert.ok(!/<Tabs/.test(detailViewBlock), "详情页不应再使用 Tabs 选项卡组件");
  assert.ok(!/处理日志/.test(detailViewBlock), "详情页不应再包含处理日志");
  assert.ok(!/lpImageQuery/.test(detailViewBlock), "详情页不应再加载 LP 分区图");
  assert.ok(!/logRows|logColumns/.test(detailViewBlock), "详情页不应再保留日志表格数据");
});
