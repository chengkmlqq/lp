import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

test("LP-245: main list tab content wrapped in list-pane container (no Card shell)", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");
  assert.ok(
    /<Tabs[\s\S]*?className="admin-lightning-distribution-tabs"[\s\S]*?<div className="admin-lightning-distribution-list-pane">/.test(source),
    "默认页内容应直接放入 admin-lightning-distribution-list-pane 容器",
  );
  assert.ok(
    !/className="admin-lightning-distribution-page-card"/.test(source),
    "不应再存在 admin-lightning-distribution-page-card 外层 Card",
  );
});

test("LP-245: import button moved to tabBarExtraContent", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");
  // 「导入」按钮应通过 tabBarExtraContent 挂载到 Tab 条右上角。
  assert.ok(
    /tabBarExtraContent=\{\s*canManage \? \([\s\S]*?导入[\s\S]*?<\/Button>[\s\S]*?\) : null\s*\}/.test(source),
    "「导入」按钮应放入 Tabs 的 tabBarExtraContent",
  );
});

test("LP-242: css overrides tab bar to colorBgContainer (light + dark)", () => {
  const css = readFileSync(GLOBALS_CSS, "utf-8");
  assert.ok(
    /\.admin-lightning-distribution-tabs > \.ant-tabs-nav \.ant-tabs-tab \{\s*background:\s*var\(--ant-color-bg-container\) !important;/.test(css),
    "主列表 Tab 底色应覆盖为 colorBgContainer 白底",
  );
  assert.ok(
    css.includes(
      ':root[data-fquiz-theme="dark"] .admin-lightning-distribution-tabs > .ant-tabs-nav .ant-tabs-tab',
    ),
    "深色模式下 Tab 底色应同步覆盖",
  );
});
