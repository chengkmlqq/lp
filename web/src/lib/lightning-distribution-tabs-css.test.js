import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-243: tabpane flex rule applies only to the active pane", () => {
  // 外层 Tabs 的多详情 pane 依赖 antd 默认 .ant-tabs-tabpane-hidden { display: none }
  // 隐藏非激活 pane；若该 flex 规则仍作用于所有 .ant-tabs-tabpane，会撑满占位导致
  // 详情激活时默认列表页未被完整覆盖。
  assert.ok(
    CSS.includes(".admin-lightning-distribution-tabs .ant-tabs-tabpane-active {"),
    "flex 规则必须只作用于激活 pane（.ant-tabs-tabpane-active）",
  );
  assert.ok(
    !CSS.includes(
      ".admin-lightning-distribution-tabs .ant-tabs-tabpane {\n  display: flex;",
    ),
    "flex 规则不得再作用于所有 .ant-tabs-tabpane（否则覆盖 antd 隐藏）",
  );
});

test("LP-243: active-pane rule keeps flex stretch + no antd hidden override", () => {
  const block = CSS.match(
    /\.admin-lightning-distribution-tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .ant-tabs-tabpane-active 规则块");
  assert.match(block, /display:\s*flex/, "激活 pane 应保持 flex 布局");
  assert.match(block, /flex:\s*1/, "激活 pane 应保持 flex:1 撑满");
});
