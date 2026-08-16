import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/tower-models/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-399: tower-models 卡片缺深色模式配色已补齐", () => {
  const darkCard = CSS.match(
    /:root\[data-fquiz-theme="dark"\] \.admin-tower-models-model-card \{([^}]*)\}/,
  )?.[1];
  assert.ok(darkCard, "应存在杆塔模型卡片深色模式容器规则");
  assert.match(darkCard, /border-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\) 35%/, "深色模式边框应使用主色混合色");
  assert.match(darkCard, /linear-gradient/, "深色模式应使用渐变背景");
  assert.match(darkCard, /box-shadow:\s*0 8px 18px/, "深色模式应使用统一柔和阴影");
  assert.match(darkCard, /!important/, "深色模式规则应带 !important");
});

test("LP-399: tower-models 卡片深色模式含头部与 body 背景规则", () => {
  const darkHead = CSS.match(
    /:root\[data-fquiz-theme="dark"\] \.admin-tower-models-model-card > \.ant-card-head \{([^}]*)\}/,
  )?.[1];
  assert.ok(darkHead, "应存在深色模式卡片头部规则");
  assert.match(darkHead, /border-bottom-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\) 25%/, "头部下边框应使用主色混色");
  assert.match(darkHead, /background:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\) 10%/, "头部应使用主色淡背景");

  const darkBody = CSS.match(
    /:root\[data-fquiz-theme="dark"\] \.admin-tower-models-model-card > \.ant-card-body \{([^}]*)\}/,
  )?.[1];
  assert.ok(darkBody, "应存在深色模式卡片 body 规则");
  assert.match(darkBody, /background:\s*var\(--ant-color-bg-container\)/, "body 背景应与容器一致");
});