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
  // 深色主题规则与其他同类卡片分组定义，选择器在分组内而非块首
  const darkGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-power-lines-line-card\s*[^,{]*[,{]/;
  assert.match(CSS, darkGroup, "深色模式应存在线路卡片配色规则");
  const headGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-power-lines-line-card\s*>\s*\.ant-card-head\s*[,{]/;
  assert.match(CSS, headGroup, "深色模式应存在线路卡片头部配色规则");
});

test("LP-301: detail view is a flex column so meta card + tabs stack and stretch", () => {
  const block = CSS.match(/\.admin-power-lines-detail-view \{([^}]*)\}/)?.[1];
  assert.ok(block, "应存在 .admin-power-lines-detail-view 规则块");
  assert.match(block, /display:\s*flex/, "详情视图应为 flex 布局");
  assert.match(block, /flex-direction:\s*column/, "详情视图应为纵向布局");
  assert.match(block, /overflow-y:\s*auto/, "详情视图应开启纵向滚动");
});

test("LP-307: detail view scrolls vertically without redundant inner table wrapper scroll", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.ok(/<div className="relative">\s*<Table<LineTowerSummary>/.test(detailBlock), "杆塔列表 Table 外层不应再有 overflow-auto 滚动容器");
});

test("LP-301: detail view shows meta card on top and map/tower switch below", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /admin-power-line-detail-meta/, "详情顶部应展示基本信息 Card");
  assert.ok(!/key:\s*"info"[\s\S]{0,80}label:\s*"线路信息"/.test(detailBlock), "线路信息不应再作为独立 Tab");
  assert.match(detailBlock, /<Radio.Button value="map"/, "详情下方应有地图切换按钮");
  assert.match(detailBlock, /<GlobalOutlined \/>/, "地图切换按钮应使用图标");
  assert.match(detailBlock, /<Radio.Button value="table"/, "详情下方应有杆塔列表切换按钮");
  assert.match(detailBlock, /<TableOutlined \/>/, "杆塔列表切换按钮应使用图标");
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

test("LP-317: detail view uses Radio.Group switch without Tabs", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /<Radio\.Group/, "地图/列表切换应使用 Radio.Group");
  assert.ok(!/<Tabs/.test(detailBlock), "详情视图不应再使用 Tabs 组件切换");
  assert.ok(!/type="editable-card"/.test(detailBlock), "详情视图不应再使用 editable-card 类型");
});

test("LP-317: detail view defaults to the tower list", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(
    detailBlock,
    /towerViewMode === "table" \? "block" : "none"/,
    "默认应展示杆塔列表面板（table）",
  );
  const tableIndex = detailBlock.indexOf("towerViewMode === \"table\" ? \"block\" : \"none\"");
  const mapIndex = detailBlock.indexOf("towerViewMode === \"map\" ? \"block\" : \"none\"");
  assert.ok(tableIndex >= 0 && mapIndex > tableIndex, "杆塔列表面板应位于地图面板之前");
});

test("LP-307: detail tower table height is not limited (no vertical scroll setting)", () => {
  const detailBlock = PAGE.match(/className="admin-power-lines-detail-view"[\s\S]*$/)?.[0];
  assert.ok(detailBlock, "应存在线路详情视图 JSX 块");
  assert.match(detailBlock, /scroll=\{\{ x: 1400 \}\}/, "杆塔列表 Table 应仅保留横向滚动");
  assert.ok(!/scroll=\{\{ x: 1400, y:/.test(detailBlock), "杆塔列表 Table 不应再有纵向滚动高度限制");
});

test("LP-317: embedded detail import/export buttons are permission gated", () => {
  assert.match(PAGE, /canTowerManage &&[\s\S]{0,160}导入 CSV/, "导入按钮应在 tower.manage 权限下显示");
  assert.match(PAGE, /canTowerRead &&[\s\S]{0,160}导出 CSV/, "导出按钮应在 tower.read 权限下显示");
  assert.match(PAGE, /towers\/import/, "导入应调用 /towers/import 接口");
  assert.match(PAGE, /towers\/export/, "导出应调用 /towers/export 接口");
});

test("LP-317: openDetail passes canTowerManage to embedded detail", () => {
  assert.match(PAGE, /canTowerManage=\{canTowerManage\}/, "openDetail 调用处应向下传递 canTowerManage");
});

const powerLineCardBlock = PAGE.match(/function PowerLineCard\([\s\S]*?\n\}/)?.[0] ?? "";

test("LP-320: line card uses a three-section layout without antd title/extra", () => {
  assert.ok(powerLineCardBlock, "应能提取 PowerLineCard 组件定义");
  assert.ok(!/title=\{</.test(powerLineCardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(powerLineCardBlock), "卡片不应再使用 antd Card extra 放置操作按钮");
  assert.match(powerLineCardBlock, /flex flex-col gap-3/, "卡片内容应为三段式纵向布局");
});

test("LP-320: upper section shows a line icon next to the title without status badge", () => {
  assert.match(powerLineCardBlock, /<DeploymentUnitOutlined /, "标题区左侧应有代表线路的图标");
  assert.match(powerLineCardBlock, /<Typography.Text strong/, "标题区应展示线路名称");
  assert.ok(!/<Badge/.test(powerLineCardBlock), "线路暂无状态,卡片不应显示状态 Badge");
});

test("LP-320: middle section renders basic info as icon + text rows", () => {
  assert.match(powerLineCardBlock, /电压等级：/, "中部应保留电压等级信息");
  assert.match(powerLineCardBlock, /杆塔总数：/, "中部应保留杆塔总数信息");
  assert.match(powerLineCardBlock, /估算长度：/, "中部应保留估算长度信息");
  assert.match(powerLineCardBlock, /更新时间：/, "中部应保留更新时间信息");
  assert.match(powerLineCardBlock, /<ThunderboltOutlined /, "电压等级应带图标");
  assert.match(powerLineCardBlock, /<ApartmentOutlined /, "杆塔总数应带图标");
  assert.match(powerLineCardBlock, /<SwapOutlined /, "估算长度应带图标");
  assert.match(powerLineCardBlock, /<ClockCircleOutlined /, "更新时间应带图标");
});

test("LP-320: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(powerLineCardBlock, /flex justify-end pt-2 border-t border-gray-200/, "操作区上方应有 border-t 分隔线并右对齐");
  assert.match(powerLineCardBlock, /icon=\{<EyeOutlined \/>\}/, "底部应有详情图标按钮");
  assert.match(powerLineCardBlock, /type="text"\s*[\s\S]{0,200}size="small"/, "操作按钮应为 text 小号图标按钮");
});

test("LP-320: delete action is icon button gated by canLineManage", () => {
  assert.match(powerLineCardBlock, /icon=\{<EditOutlined \/>\}/, "底部应有编辑图标按钮");
  assert.match(powerLineCardBlock, /icon=\{<DeleteOutlined \/>\}/, "底部应有删除图标按钮");
  assert.match(powerLineCardBlock, /\{canLineManage &&[\s\S]{0,200}icon=\{<DeleteOutlined \/>\}/, "删除按钮仅在 canLineManage 时显示");
  assert.match(powerLineCardBlock, /\bdanger\b/, "删除按钮应标记 danger");
});

test("LP-320: card and list view pagination share consistent vertical spacing", () => {
  const cardPaginationBlock = CSS.match(/\.admin-power-lines-pagination \{([^}]*)\}/)?.[1];
  assert.ok(cardPaginationBlock, "应存在卡片视图分页容器规则");
  assert.match(cardPaginationBlock, /padding:\s*12px\s+0\s+8px/, "卡片分页容器应使用统一上下边距(顶部12px 底部8px)");
  const tablePaginationRule =
    /\.admin-power-lines-tabs \.ant-table-pagination\s*\{([^}]*)\}/;
  const tablePaginationBlock = CSS.match(tablePaginationRule)?.[1];
  assert.ok(tablePaginationBlock, "应存在表格视图分页规则");
  assert.match(tablePaginationBlock, /margin:\s*12px\s+0\s+0\s*!important/, "表格分页应保持顶部 12px 间距");
});
