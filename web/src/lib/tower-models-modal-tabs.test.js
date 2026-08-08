import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/tower-models/page.tsx");
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const SOURCE = readFileSync(PAGE_FILE, "utf-8");
const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-278: 编辑/新建模型 Modal 表单改用 Tabs 分组", () => {
  assert.ok(
    SOURCE.includes('className="admin-tower-models-modal-tabs"'),
    "编辑模型 Modal 应使用 Tabs（admin-tower-models-modal-tabs）",
  );
});

test("LP-278: Tabs 分组包含基本信息与默认参数", () => {
  assert.ok(SOURCE.includes('key: "basic"'), "应存在“基本信息”Tab");
  assert.ok(SOURCE.includes('label: "基本信息"'), "基本信息 Tab 标签应为“基本信息”");
  assert.ok(SOURCE.includes('key: "defaults"'), "应存在“默认参数”Tab");
  assert.ok(SOURCE.includes('label: "默认参数"'), "默认参数 Tab 标签应为“默认参数”");
});

test("LP-278: 默认参数已纳入编辑表单 buildPayload", () => {
  for (const field of [
    "default_ground_resistance_ohm",
    "default_lightning_density",
    "default_span_small_m",
    "default_span_large_m",
    "default_slope_1",
    "default_slope_2",
  ]) {
    assert.ok(
      SOURCE.includes(`${field}: values.${field} ?? null,`),
      `buildPayload 应提交 ${field} 字段`,
    );
  }
});

test("LP-278: tower-models Modal Tabs 有对应全局样式", () => {
  const block = CSS.match(
    /\.admin-tower-models-modal-tabs \.ant-tabs-nav \{([^}]*)\}/,
  )?.[1];
  assert.ok(block, "应存在 .admin-tower-models-modal-tabs .ant-tabs-nav 规则块");
  assert.match(block, /margin:\s*0\s+0\s+12px/, "Tabs 导航栏应保留简洁间距");
});