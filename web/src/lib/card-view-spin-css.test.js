import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = join(__dirname, "..");
const CSS = readFileSync(join(SRC, "app/globals.css"), "utf-8");
const MARKER = "admin-card-view-spin";

function collectTsx(dir) {
  const result = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) result.push(...collectTsx(full));
    else if (entry.isFile() && entry.name.endsWith(".tsx")) result.push(full);
  }
  return result;
}

/** 嵌套 Spin（带 spinning=）列表：卡片视图必须打标记，表格/弹窗保留 antd 原生行为。 */
function nestedSpins() {
  const result = [];
  for (const file of collectTsx(SRC)) {
    const lines = readFileSync(file, "utf-8").split("\n");
    lines.forEach((line, index) => {
      if (/<Spin\s+spinning=/.test(line)) {
        result.push({ path: relative(SRC, file), line: index + 1, text: line.trim() });
      }
    });
  }
  return result;
}

test("卡片视图 loading：共享 CSS 规则把 indicator 锚定到滚动可视区", () => {
  // 4 个类选择器：antd cssinjs 运行时注入的是 .ant-spin.css-hash > .ant-spin-section(0-3-0)，
  // 静态 globals.css 先加载，必须用更高特异性才能压过它（否则 spinner 仍是 absolute 漂移）。
  const selector =
    /\.admin-card-view-spin\.ant-spin-spinning\.ant-spin > \.ant-spin-section \{([^}]*)\}/;
  const match = CSS.match(selector);
  assert.ok(match, "必须存在 .admin-card-view-spin 的 0-4-0 选择器规则");

  const block = match[1];
  assert.match(block, /position:\s*sticky/, "indicator 必须用 sticky 锚定滚动可视区");
  assert.match(block, /top:\s*50%/, "sticky top 必须是可视区 50%");
  assert.match(block, /left:\s*auto/, "必须覆盖 antd 的 left:50%，避免 sticky 水平偏移");
  assert.match(block, /width:\s*max-content/, "宽度收缩到 indicator 本身");
  assert.match(block, /height:\s*0/, "零高度，不挤动卡片网格");
  assert.match(block, /margin-left:\s*50%/, "水平居中");
  assert.match(block, /justify-content:\s*center/, "指示器围绕零高度线居中");
  assert.match(block, /transform:\s*translate\(-50%,\s*0\)/, "覆盖 antd 的 translate(-50%,-50%)");
});

test("卡片视图 nested Spin 必须带 .admin-card-view-spin 标记", () => {
  // 白名单：仅这三处是表格/小表单的 Spin，卡片数量有分页上限，不存在「随内容变多漂移」。
  const allowedUnmarked = [
    "spinning={trialTowersLoading}",
    "spinning={runsQuery.isFetching}",
    "spinning={resolveLoading}",
  ];

  const spins = nestedSpins();
  const marked = spins.filter((item) => item.text.includes(MARKER));
  assert.ok(marked.length >= 17, `卡片视图 Spin 标记数应至少 17，实际 ${marked.length}`);

  for (const item of spins) {
    if (item.text.includes(MARKER)) continue;
    assert.ok(
      allowedUnmarked.some((allowed) => item.text.includes(allowed)),
      `${item.path}:${item.line} 是新增的嵌套 Spin，请确认：卡片视图需加 className="${MARKER}"，` +
        `表格/弹窗请加入测试白名单`,
    );
  }
});

test("防雷计算页的页面层遮罩与统一修法并存，互不覆盖", () => {
  assert.ok(CSS.includes(".admin-fl-analysis-card-region {"));
  assert.ok(CSS.includes(".admin-fl-analysis-card-loading {"));
});
