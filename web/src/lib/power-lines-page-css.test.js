import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/power-lines/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-301: card-scroll container no longer adds its own 12px padding", () => {
  // 父容器 .admin-power-lines-list-pane 已提供 padding:12px，卡片滚动容器不应重复内边距
  const block = CSS.match(/\.admin-power-lines-card-scroll \{([^}]*)\}/)?.[1];
  assert.ok(block, "应存在 .admin-power-lines-card-scroll 规则块");
  assert.ok(!/padding\s*:\s*12px/.test(block), "卡片滚动容器不应再包含 padding: 12px");
  assert.match(block, /gap:\s*12px/, "gap: 12px 应保留");
});

test("LP-301: line card keeps worker-style color scheme in light theme", () => {
  const block = CSS.match(/\.admin-power-lines-line-card \{([^}]*)\}/)?.[1];
  assert.ok(block, "应存在 .admin-power-lines-line-card 规则块");
  assert.match(block, /var\(--fquiz-theme-primary\)/, "卡片应使用主色渐变配色");
  assert.match(block, /linear-gradient/, "卡片应使用渐变背景");
});

test("LP-301: line card has dark theme adaptation", () => {
  const darkSelector = /:root\[data-fquiz-theme="dark"\] \.admin-power-lines-line-card\s*\{/;
  assert.match(CSS, darkSelector, "深色模式应存在线路卡片配色规则");
  const headSelector = /:root\[data-fquiz-theme="dark"\] \.admin-power-lines-line-card\s*>\s*\.ant-card-head/;
  assert.match(CSS, headSelector, "深色模式应存在线路卡片头部配色规则");
});

test("LP-301: detail view is a flex column so meta card + tabs stack and stretch", () => {
  const block = CSS.match(/\.admin-power-lines-detail-view \{([^}]*)\}/)?.[1];
  assert.ok(block, "应存在 .admin-power-lines-detail-view 规则块");
  assert.match(block, /display:\s*flex/, "详情视图应为 flex 布局");
  assert.match(block, /flex-direction:\s*column/, "详情视图应为纵向布局");
});

test("LP-301: detail view shows meta card on top and map/tower tabs below", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /admin-power-line-detail-meta/, "详情顶部应展示基本信息 Card");
  assert.ok(!/key:\s*"info"[\s\S]{0,80}label:\s*"线路信息"/.test(detailBlock), "线路信息不应再作为独立 Tab");
  assert.match(detailBlock, /label:\s*"地图"/, "详情下方应有地图 Tab");
  assert.match(detailBlock, /label:\s*"杆塔列表"/, "详情下方应有杆塔列表 Tab");
});

test("LP-307: detail basic info is rendered as a bordered Descriptions table", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /<Descriptions bordered size="small" column=\{3\}>/, "基本信息应以 bordered Descriptions 表格呈现");
  assert.match(detailBlock, /label="线路编码"/, "表格应包含线路编码");
  assert.match(detailBlock, /label="线路名称"/, "表格应包含线路名称");
  assert.match(detailBlock, /label="电压等级"/, "表格应包含电压等级");
  assert.match(detailBlock, /label="杆塔总数"/, "表格应包含杆塔总数");
  assert.match(detailBlock, /label="估算长度"/, "表格应包含估算长度");
  assert.match(detailBlock, /label="更新时间"/, "表格应包含更新时间");
});

test("LP-307: detail tabs use card type without close icon", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /type="card"/, "选项卡应为 card 类型");
  assert.ok(!/type="editable-card"/.test(detailBlock), "选项卡不应再使用 editable-card 类型");
});

test("LP-307: detail tabs default to the tower list", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /defaultActiveKey="towers"/, "选项卡应默认激活杆塔列表");
  assert.match(detailBlock, /key: "towers"[\s\S]{0,60}label: "杆塔列表"/, "杆塔列表应为首个选项卡");
});

test("LP-307: detail tower table height is not limited (no vertical scroll setting)", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /scroll=\{\{ x: 1400 \}\}/, "杆塔列表 Table 应仅保留横向滚动");
  assert.ok(!/scroll=\{\{ x: 1400, y:/.test(detailBlock), "杆塔列表 Table 不应再有纵向滚动高度限制");
});
