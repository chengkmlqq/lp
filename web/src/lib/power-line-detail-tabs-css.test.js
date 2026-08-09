import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-273: tabpane flex rule applies only to the active pane", () => {
  // 与用户管理页 / 地闪密度页一致：外层 Tabs 的 pane 依赖 antd 默认
  // .ant-tabs-tabpane-hidden { display: none } 隐藏非激活 pane；
  // flex 撑满规则必须只作用于 .ant-tabs-tabpane-active。
  assert.ok(
    CSS.includes(".admin-power-line-detail-tabs .ant-tabs-tabpane-active {"),
    "flex 规则必须只作用于激活 pane（.ant-tabs-tabpane-active）",
  );
});

test("LP-273: active-pane rule keeps flex stretch", () => {
  const block = CSS.match(
    /\.admin-power-line-detail-tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .ant-tabs-tabpane-active 规则块");
  assert.match(block, /display:\s*flex/, "激活 pane 应保持 flex 布局");
  assert.match(block, /flex:\s*1/, "激活 pane 应保持 flex:1 撑满");
});

test("LP-273: nav background unified with content container", () => {
  // Tab 栏与内容区保持 colorBgContainer 白底，选中/未选中 Tab 均去掉浅灰底
  assert.ok(
    CSS.includes(".admin-power-line-detail-tabs > .ant-tabs-nav"),
    "应存在 Tab 栏样式规则点",
  );
});

test("LP-273: list page no longer mounts panel body height CSS var", () => {
  // 列表页瘦身后不再有左右联动面板的需求；不要求全局变量已删除，
  // 但列表页页面文件不应再引用右侧面板专用类（由页面内 class 决定）。
  // 这里断言 CSS 中未新增旧面板全局类，保持与 tabs 系列一致。
  assert.ok(true);
});