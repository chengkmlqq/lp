import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-392: 地闪密度列表表格高度锚点使用动态 min-height", () => {
  assert.ok(
    PAGE.includes("tableScrollAnchorRef"),
    "列表表格应挂载高度锚点 ref",
  );
  assert.ok(
    PAGE.includes("admin-lightning-distribution-table-anchor"),
    "列表表格应使用地闪密度锚点类",
  );
  assert.ok(
    PAGE.includes("--admin-lightning-distribution-table-body-min-height"),
    "表格 body 最小高度应通过 CSS 变量传入",
  );
  assert.ok(
    PAGE.includes('className="admin-lightning-distribution-table-anchor"'),
    "列表视图锚点 div 应使用锚点类",
  );
  assert.ok(
    PAGE.includes(
      '"--admin-lightning-distribution-table-body-min-height": `${tableScrollY}px`',
    ),
    "锚点 div 应将动态 tableScrollY 注入 CSS 变量",
  );
});

test("LP-392: 表格 body min-height 由 CSS 变量驱动并兜底", () => {
  assert.ok(
    CSS.includes(".admin-lightning-distribution-table-anchor .ant-table-body {"),
    "全局样式应包含地闪密度表格 body 规则",
  );
  const block = CSS.match(
    /\.admin-lightning-distribution-table-anchor \.ant-table-body \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在地闪密度表格 body 规则块");
  assert.match(
    block,
    /min-height:\s*var\(--admin-lightning-distribution-table-body-min-height,\s*180px\);/,
    "min-height 应使用 CSS 变量并带 180px 兜底",
  );
});