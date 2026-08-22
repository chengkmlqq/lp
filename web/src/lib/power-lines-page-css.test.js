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

test("LP-433: list page no longer embeds PowerLineDetailView tabs", () => {
  assert.ok(!/PowerLineDetailView/.test(PAGE), "列表页应移除内嵌详情视图");
  assert.ok(!/type="editable-card"/.test(PAGE), "列表页应移除可编辑 Tab 栏");
  assert.ok(!/detailTabs/.test(PAGE), "列表页应移除详情 Tab 状态");
});

test("LP-433: list action buttons route to tower and map pages", () => {
  assert.match(PAGE, /onClick=\{\(\) => onDetail\(line\)\}[\s\S]{0,120}杆塔/, "列表详情按钮应显示为杆塔");
  assert.match(PAGE, /router\.push\(`\/admin\/power-lines\/\$\{line\.id\}\/towers`\)/, "列表操作应跳转杆塔页");
  assert.match(PAGE, /router\.push\(`\/admin\/power-lines\/\$\{line\.id\}\/map`\)/, "列表操作应新增跳转地图页");
});

test("LP-433: card actions provide tower and preview navigation", () => {
  const cardBlock = PAGE.match(/function PowerLineCard\([\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(cardBlock, "应存在 PowerLineCard 组件定义");
  assert.match(cardBlock, /GlobalOutlined/, "卡片应提供地图预览入口");
  assert.match(cardBlock, /onPreview\(line\)/, "卡片应支持地图预览跳转");
});

test("LP-433: towers page contains filters, import/export and tower table", () => {
  const towersPage = readFileSync(join(__dirname, "../app/admin/power-lines/[lineId]/towers/page.tsx"), "utf-8");
  assert.match(towersPage, /关键词/, "杆塔页应保留关键词筛选");
  assert.match(towersPage, /塔型/, "杆塔页应保留塔型筛选");
  assert.match(towersPage, /查询/, "杆塔页应保留查询按钮");
  assert.match(towersPage, /导入 CSV/, "杆塔页应保留导入功能");
  assert.match(towersPage, /导出 CSV/, "杆塔页应保留导出功能");
  assert.ok(/admin-power-line-detail-meta/.test(towersPage) || !/PowerLineCesiumMap/.test(towersPage), "杆塔页应移除地图视图");
});

test("LP-433: map page uses full-page Cesium map without view toggle", () => {
  const mapPage = readFileSync(join(__dirname, "../app/admin/power-lines/[lineId]/map/page.tsx"), "utf-8");
  assert.match(mapPage, /PowerLineCesiumMap/, "地图页应使用 Cesium 地图组件");
  assert.ok(!/Radio\.Group/.test(mapPage), "地图页不应再存在视图切换 Radio");
  assert.ok(!/towerViewMode/.test(mapPage), "地图页应移除地图/列表切换状态");
});
const powerLineCardBlock = PAGE.match(/function PowerLineCard\([\s\S]*?\n\}/)?.[0] ?? "";

test("LP-320: line card uses a three-section layout without antd title/extra", () => {
  assert.ok(powerLineCardBlock, "应能提取 PowerLineCard 组件定义");
  assert.ok(!/title=\{</.test(powerLineCardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(powerLineCardBlock), "卡片不应再使用 antd Card extra 放置操作按钮");
  assert.match(powerLineCardBlock, /flex flex-col/, "卡片内容应为三段式纵向布局");
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

test("LP-353: title bar is separated from basic info by a bottom border divider", () => {
  assert.match(
    powerLineCardBlock,
    /flex items-center gap-2 px-4 py-3 border-b border-gray-200/,
    "标题栏底部应有 border-b 分隔线且与底部操作栏 border-gray-200 风格一致",
  );
});

test("LP-320: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(powerLineCardBlock, /flex justify-end px-4 py-2 border-t border-gray-200/, "操作区上方应有 border-t 分隔线并右对齐");
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

test("LP-365: line card body padding is zeroed so dividers span the full card width", () => {
  const bodyBlock = CSS.match(/\.admin-power-lines-line-card > \.ant-card-body \{([^}]*)\}/)?.[1];
  assert.ok(bodyBlock, "应存在线路卡片 body 规则块");
  assert.match(bodyBlock, /padding:\s*0/, "ant-card-body padding 应归零");
  assert.ok(!/padding-block/.test(bodyBlock), "不应再保留 padding-block 设置");
});

test("LP-365: three card sections carry independent padding", () => {
  assert.match(powerLineCardBlock, /admin-power-lines-line-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200/, "标题栏应有 px-4 py-3 独立 padding");
  assert.match(powerLineCardBlock, /flex flex-col gap-2 px-4 py-3/, "信息区应有 px-4 py-3 独立 padding");
  assert.match(powerLineCardBlock, /admin-power-lines-line-card-actions flex justify-end px-4 py-2 border-t border-gray-200/, "按钮区应有 px-4 py-2 独立 padding");
  assert.ok(!/gap-3/.test(powerLineCardBlock), "外层不再依赖 gap-3 承担间距");
});

test("LP-365: action bar divider uses themed border color in light and dark themes", () => {
  const lightBlock = CSS.match(/\.admin-power-lines-line-card-actions \{([^}]*)\}/)?.[1];
  assert.ok(lightBlock, "应存在 .admin-power-lines-line-card-actions 规则块");
  assert.match(lightBlock, /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "浅色主题操作区分隔线应使用主色混色");
  const darkRule = /:root\[data-fquiz-theme="dark"\] \.admin-power-lines-line-card-actions \{([^}]*)\}/;
  const darkBlock = CSS.match(darkRule)?.[1];
  assert.ok(darkBlock, "应存在暗色主题操作区分隔线规则");
  assert.match(darkBlock, /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "暗色主题操作区分隔线应使用主色混色");
  assert.match(darkBlock, /!important/, "暗色主题规则应带 !important");
});
