import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

test("LP-242: main list card has a title header (方案B 标题载体)", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");
  assert.ok(
    /<AntCard[\s\S]*?className="admin-lightning-distribution-page-card"[\s\S]*?title="地闪密度统计"/.test(source),
    "主列表 Card 应设置 title=\"地闪密度统计\"，使标题栏为 Card 头部",
  );
});

test("LP-242: import button moved into card extra (对齐用户管理页)", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");
  // 主列表 Card（admin-lightning-distribution-page-card）的 extra 中应包含「导入」按钮，
  // 且不再通过 tabBarExtraContent 挂载到 Tab 栏。
  assert.ok(
    /className="admin-lightning-distribution-page-card"[\s\S]*?title="地闪密度统计"[\s\S]*?extra=\{\s*[\s\S]*?导入[\s\S]*?<\/Button>[\s\S]*?\}/.test(source),
    "「导入」按钮应放入主列表 Card 的 extra，与用户管理页「新建用户」对齐",
  );
  assert.equal(
    source.includes("tabBarExtraContent"),
    false,
    "「导入」按钮不应再通过 tabBarExtraContent 挂载在 Tab 栏",
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
