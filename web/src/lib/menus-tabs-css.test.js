import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-255: tabpane flex rule applies only to the active pane", () => {
  // 与地闪密度页一致：外层 Tabs 的 pane 依赖 antd 默认
  // .ant-tabs-tabpane-hidden { display: none } 隐藏非激活 pane；
  // flex 撑满规则必须只作用于 .ant-tabs-tabpane-active。
  assert.ok(
    CSS.includes(".admin_menus_tabs .ant-tabs-tabpane-active {"),
    "flex 规则必须只作用于激活 pane（.ant-tabs-tabpane-active）",
  );
  assert.ok(
    !CSS.includes(
      ".admin_menus_tabs .ant-tabs-tabpane {\n  display: flex;",
    ),
    "flex 规则不得再作用于所有 .ant-tabs-tabpane（否则覆盖 antd 隐藏）",
  );
});

test("LP-255: active-pane rule keeps flex stretch", () => {
  const block = CSS.match(
    /\.admin_menus_tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .ant-tabs-tabpane-active 规则块");
  assert.match(block, /display:\s*flex/, "激活 pane 应保持 flex 布局");
  assert.match(block, /flex:\s*1/, "激活 pane 应保持 flex:1 撑满");
});

test("LP-255: list-pane replaces removed outer Card body", () => {
  // 外层 AntCard 已移除，需用 list-pane 容器承担 padding/滚动/flex 布局职责
  const block = CSS.match(
    /\.admin_menus_list_pane \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin_menus_list_pane 规则块");
  assert.match(block, /overflow-y:\s*auto/, "list-pane 应保留纵向滚动");
  assert.match(block, /padding:\s*12px/, "list-pane 应保留 12px 内边距");
});

test("LP-255: old outer page-card rules are removed", () => {
  // 验收标准：无残留死代码（AntCard 外壳规则清理干净）。
  // 注意：globals.css 中 system-params 区块注释仍引用该字符串作为参照说明
  // （.admin-menus-page-card 的生命周期已完成），故仅断言规则块本身已移除。
  assert.ok(
    !CSS.includes(".admin-menus-page-card {") &&
      !CSS.includes(".admin-menus-page-card > .ant-card-body {"),
    "不应残留 .admin-menus-page-card 外层卡片规则块",
  );
});
