import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/power-lines/[id]/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-317: map/tower switching uses Radio.Group without Tabs", () => {
  // 地图/列表切换由 Tabs 改为 Radio.Group，无需选项卡的关闭按钮
  assert.match(PAGE, /<Radio\.Group/, "地图/列表切换应使用 Radio.Group");
  assert.match(PAGE, /<Radio.Button value="map">地图<\/Radio.Button>/, "应存在地图切换按钮");
  assert.match(PAGE, /<Radio.Button value="table">杆塔列表<\/Radio.Button>/, "应存在杆塔列表切换按钮");
  assert.ok(!/<Tabs/.test(PAGE), "不应再使用 Tabs 组件切换地图/列表");
  assert.ok(!PAGE.includes('type="editable-card"'), "不应再使用 editable-card 类型（无关闭按钮）");
});

test("LP-304: tower list tab is the default view", () => {
  assert.match(PAGE, /useState<"table" \| "map">\("table"\)/, "默认应展示杆塔列表（table）");
});

test("LP-304: detail meta is presented as a bordered table", () => {
  assert.match(PAGE, /Descriptions bordered size="small" column=\{3\}/, "详情信息应使用 bordered Descriptions 表格呈现");
});

test("LP-304: tower table keeps only horizontal scroll", () => {
  assert.match(PAGE, /scroll=\{\{ x: 1520 \}\}/, "杆塔列表 Table 应仅保留横向滚动");
  assert.ok(!/scroll=\{\{[\s\S]*?y:/.test(PAGE), "杆塔列表 Table 不应再有纵向滚动参数");
});

test("LP-304: vertical scroll lives on the whole detail page, not the table", () => {
  assert.match(PAGE, /overflow-y-auto/, "详情页外层容器应开启纵向滚动");
  const tabpaneBlock = CSS.match(
    /\.admin-power-line-detail-tabs \.ant-tabs-tabpane-active \{([^}]*)\}/,
  )?.[1];
  assert.ok(!tabpaneBlock || !/flex:\s*1/.test(tabpaneBlock), "激活 pane 不应再 flex:1 撑满强制表格内部滚动");
});

test("LP-304: nav background unified with content container", () => {
  // Tab 栏与内容区保持 colorBgContainer 白底
  assert.ok(
    CSS.includes(".admin-power-line-detail-tabs > .ant-tabs-nav"),
    "应存在 Tab 栏样式规则点",
  );
});