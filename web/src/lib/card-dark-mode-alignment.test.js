import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");

test("LP-398: syslog 日志卡片深色模式补齐头部/正文规则（对齐 roles/system-messages）", () => {
  const headRule = /:root\[data-fquiz-theme="dark"\] \.admin-syslog-log-card > \.ant-card-head \{([^}]*)\}/;
  const headBlock = CSS.match(headRule)?.[1];
  assert.ok(headBlock, "应存在深色模式 syslog 卡片头部规则");
  assert.match(headBlock, /border-bottom-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "深色卡片头部下边框应使用主色混色");
  assert.match(headBlock, /background:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "深色卡片头部背景应使用主色淡背景");
  assert.match(headBlock, /!important/, "深色规则应带 !important");

  const bodyRule = /:root\[data-fquiz-theme="dark"\] \.admin-syslog-log-card > \.ant-card-body \{([^}]*)\}/;
  const bodyBlock = CSS.match(bodyRule)?.[1];
  assert.ok(bodyBlock, "应存在深色模式 syslog 卡片正文规则");
  assert.match(bodyBlock, /background:\s*var\(--ant-color-bg-container\)/, "深色卡片正文背景应为 colorBgContainer");
  assert.match(bodyBlock, /!important/, "深色规则应带 !important");
});

test("LP-398: fl-analysis 任务卡片深色模式补齐正文规则（对齐 fault-analysis 卡片）", () => {
  const bodyGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-fl-analysis-job-card\s*>\s*\.ant-card-body\s*[^,{]*[,{]/;
  assert.match(CSS, bodyGroup, "深色模式应覆盖 fl-analysis 任务卡片正文背景规则");
  const bodyRule = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-fl-analysis-job-card\s*>\s*\.ant-card-body[\s\S]*?\{([^}]*)\}/;
  const block = CSS.match(bodyRule)?.[1];
  assert.ok(block, "应存在深色模式 fl-analysis 任务卡片正文规则块");
  assert.match(block, /background:\s*var\(--ant-color-bg-container\)/, "深色卡片正文背景应为 colorBgContainer");
  assert.match(block, /!important/, "深色规则应带 !important");
});

test("LP-398: fl-analysis 任务卡片补齐浅色操作区分隔线规则（与标题区分隔线一致）", () => {
  const actionsBlock = CSS.match(
    /^\.admin-fl-analysis-job-card-actions \{([^}]*)\}/m,
  )?.[1];
  assert.ok(actionsBlock, "应存在 .admin-fl-analysis-job-card-actions 浅色规则块");
  assert.match(
    actionsBlock,
    /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/,
    "操作区分隔线应使用主色混色",
  );
});