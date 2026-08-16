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

test("LP-398: 地闪密度表格锚点容器补齐 flex 撑满规则（对齐线路管理页 table-view）", () => {
  const anchorBlock = CSS.match(
    /^\.admin-lightning-distribution-table-anchor \{([^}]*)\}/m,
  )?.[1];
  assert.ok(anchorBlock, "应存在 .admin-lightning-distribution-table-anchor 容器规则块");
  assert.match(anchorBlock, /display:\s*flex/, "锚点容器应为 flex 布局");
  assert.match(anchorBlock, /flex:\s*1/, "锚点容器应 flex:1 撑满");
  assert.match(anchorBlock, /min-height:\s*0/, "锚点容器应 min-height:0");
  assert.match(anchorBlock, /flex-direction:\s*column/, "锚点容器应为纵向布局");
});

test("LP-398: 地闪密度列表视图分页条隐藏单选页时保持显示（对齐卡片视图分页）", () => {
  assert.ok(
    PAGE.includes("hideOnSinglePage: false"),
    "列表视图 Table 分页应隐藏单页时不隐藏，避免与卡片视图分页条切换时晃动",
  );
});