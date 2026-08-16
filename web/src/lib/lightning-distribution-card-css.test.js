import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

const cardBlock = PAGE.match(/const renderRecordCard = \(record: LightningDistributionRecord\) => \{[\s\S]*?\n  \};/)?.[0] ?? "";

test("LP-357: lightning distribution card uses a three-section layout without antd title/extra", () => {
  assert.ok(cardBlock, "应能提取 renderRecordCard 组件定义");
  assert.ok(!/title=\{</.test(cardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(cardBlock), "卡片不应再使用 antd Card extra 放置操作菜单");
  assert.match(cardBlock, /flex flex-col/, "卡片内容应为三段式纵向布局");
  assert.match(cardBlock, /className="admin-lightning-distribution-event-card"/, "卡片应保留 admin-lightning-distribution-event-card 容器类");
  assert.match(cardBlock, /hoverable/, "卡片应保留 hoverable");
});

test("LP-357: upper section shows icon + strong truncate title with status tag and border-b divider", () => {
  assert.match(cardBlock, /admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200/, "标题区应使用专用类名并带 px-4 py-3 独立 padding");
  assert.match(cardBlock, /<ThunderboltOutlined className="text-base text-gray-500" \/>/, "标题区左侧应有代表地闪的图标");
  assert.match(cardBlock, /<Typography.Text strong className="truncate/, "标题区应展示强体 truncate 文件名");
  assert.match(cardBlock, /<Tag color=\{meta\.color\}>/, "状态 Tag 应保留在标题区");
  assert.match(cardBlock, /border-b border-gray-200/, "标题栏与信息区之间应有 border-b 分隔线");
});

test("LP-389: middle section renders the compact fields as icon + text rows", () => {
  assert.match(cardBlock, /flex flex-col gap-2 px-4 py-3/, "信息区应有 px-4 py-3 独立 padding");
  assert.match(cardBlock, /城市：/, "中部应保留城市信息");
  assert.match(cardBlock, /地点标签：/, "中部应保留地点标签信息");
  assert.match(cardBlock, /有效点数：/, "中部应保留有效点数信息");
  assert.match(cardBlock, /整体 Ng：/, "中部应保留整体 Ng 信息");
  assert.doesNotMatch(cardBlock, /导入时间：/, "中部不应再展示导入时间");
  assert.doesNotMatch(cardBlock, /最大电流：/, "中部不应再展示最大电流");
  assert.doesNotMatch(cardBlock, /平均电流：/, "中部不应再展示平均电流");
  assert.match(cardBlock, /<EnvironmentOutlined /, "城市应带图标");
  assert.match(cardBlock, /<TagOutlined /, "地点标签应带图标");
  assert.match(cardBlock, /<NumberOutlined /, "有效点数应带图标");
  assert.match(cardBlock, /<ThunderboltOutlined className="text-xs text-gray-500" \/>/, "整体 Ng 应带图标");
  assert.doesNotMatch(cardBlock, /<ClockCircleOutlined /, "导入时间图标应移除");
  assert.doesNotMatch(cardBlock, /<BarChartOutlined /, "最大/平均电流图标应移除");
  assert.match(cardBlock, /type="secondary" className="text-xs/, "信息行应使用次要色 text-xs 文本");
});

test("LP-357: processing progress bar is preserved in the info section", () => {
  assert.match(cardBlock, /record\.status === "processing"[\s\S]{0,120}<Progress /, "处理中状态应保留进度条");
});

test("LP-389: bottom section holds flat icon action buttons with a top border divider", () => {
  assert.match(cardBlock, /admin-lightning-distribution-event-card-actions flex justify-end px-4 py-2 border-t border-gray-200/, "操作区应使用专用类名并带 px-4 py-2 独立 padding");
  assert.match(cardBlock, /icon=\{<EyeOutlined \/>\}/, "底部应有详情图标按钮");
  assert.match(cardBlock, /type="text"\s*[\s\S]{0,200}size="small"/, "操作按钮应为 text 小号图标按钮");
});

test("LP-389: all actions flattened out of the dropdown menu", () => {
  assert.ok(!/key: "image"/.test(cardBlock), "下拉中不应再包含详情项");
  assert.doesNotMatch(cardBlock, /label: "详情"/, "下拉中不应再包含详情菜单项");
  assert.match(cardBlock, /openDetail\(record\)/, "详情应由 Eye 图标按钮打开");
  assert.doesNotMatch(cardBlock, /Dropdown menu=\{\{ items: dropdownItems \}\}/, "卡片不应再使用下拉折叠菜单");
  assert.doesNotMatch(cardBlock, /dropdownItems/, "dropdownItems 变量应被移除");
  assert.match(cardBlock, /icon=\{<FileTextOutlined \/>\}[\s\S]{0,120}openLogViewer\(record\.task_id/, "导入日志应平铺为图标按钮");
  assert.match(cardBlock, /openLogViewer\(record\.lp_draw_task_id/, "绘图日志应平铺为图标按钮");
  assert.match(cardBlock, /icon=\{<ThunderboltOutlined \/>\}[\s\S]{0,140}openLpDrawModal\(record\)/, "绘图应平铺为图标按钮");
  assert.match(cardBlock, /icon=\{<DeleteOutlined \/>\}/, "删除应平铺为危险图标按钮");
  assert.match(cardBlock, /Modal\.confirm\(/, "删除应保留二次确认弹窗");
  assert.match(cardBlock, /\bdanger\b/, "删除按钮应标记 danger");
  assert.match(cardBlock, /loading=\{deleteMutation\.isPending\}/, "删除按钮应保留 loading 态");
  const stopPropagationCount = (cardBlock.match(/event\.stopPropagation\(\)/g) ?? []).length;
  assert.ok(stopPropagationCount >= 5, "每个操作按钮都应 stopPropagation 防冒泡");
});

test("LP-357: card container keeps aligned styling with dark theme coverage", () => {
  const block = CSS.match(/^\.admin-lightning-distribution-event-card \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在 .admin-lightning-distribution-event-card 规则块");
  assert.match(block, /color-mix\(in srgb, var\(--fquiz-theme-primary\) 26%/, "边框应使用主色混合色");
  assert.match(block, /linear-gradient/, "卡片应使用渐变背景");
  assert.match(block, /box-shadow: 0 8px 18px/, "卡片应使用统一柔和阴影");
  const darkGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-distribution-event-card\s*[^,{]*[,{]/;
  assert.match(CSS, darkGroup, "深色模式应覆盖地闪密度卡片配色规则");
});

test("LP-389: card action bar keeps aligned border styling", () => {
  const block = CSS.match(/^\.admin-lightning-distribution-event-card-actions \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在 .admin-lightning-distribution-event-card-actions 规则块");
  assert.match(block, /border-top-color: color-mix\(in srgb, var\(--fquiz-theme-primary\) 18%/, "操作栏边框应使用主色混合色");
});

test("LP-391: card body padding zeroed and title/actions sections carry themed colors", () => {
  const bodyBlock = CSS.match(/^\.admin-lightning-distribution-event-card > \.ant-card-body \{([^}]*)\}/m)?.[1];
  assert.ok(bodyBlock, "应存在 .admin-lightning-distribution-event-card > .ant-card-body 规则块");
  assert.match(bodyBlock, /padding:\s*0/, "ant-card-body padding 应归零，由各区域自行控制");
  assert.ok(!/padding-block/.test(bodyBlock), "不应再保留 padding-block 设置");
  const titleBlock = CSS.match(/^\.admin-lightning-distribution-event-card-title \{([^}]*)\}/m)?.[1];
  assert.ok(titleBlock, "应存在 .admin-lightning-distribution-event-card-title 规则块");
  assert.match(titleBlock, /min-height:\s*44px/, "标题区应设置 min-height 44px");
  assert.match(titleBlock, /background:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\) 6%, transparent\)/, "标题区应使用主色淡背景");
  const actionsBlock = CSS.match(/^\.admin-lightning-distribution-event-card-actions \{([^}]*)\}/m)?.[1];
  assert.ok(actionsBlock, "应存在 .admin-lightning-distribution-event-card-actions 规则块");
  assert.match(actionsBlock, /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\) 18%/, "操作区分隔线应使用主色混色");
  const darkTitle = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-distribution-event-card-title\s*[,{]/;
  assert.match(CSS, darkTitle, "深色模式应覆盖标题区配色规则");
  const darkActions = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-distribution-event-card-actions\s*[,{]/;
  assert.match(CSS, darkActions, "深色模式应覆盖操作区分隔线规则");
});

test("LP-391: card grid shows four columns per row on xl screens", () => {
  const gridLine = PAGE.match(/<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">/);
  assert.ok(gridLine, "卡片 Grid 应为 4 列布局");
  assert.ok(!/xl:grid-cols-3/.test(PAGE), "不应再保留 xl 三列布局");
});

test("LP-391: pagination bar aligns with power-lines vertical spacing", () => {
  const paginationBlock = CSS.match(/^\.admin-lightning-distribution-pagination \{([^}]*)\}/m)?.[1];
  assert.ok(paginationBlock, "应存在 .admin-lightning-distribution-pagination 规则块");
  assert.match(paginationBlock, /padding:\s*12px\s+0\s+8px/, "分页容器应使用统一上下边距（顶部 12px 底部 8px）");
  assert.match(paginationBlock, /align-items:\s*center/, "分页容器应垂直居中");
});

test("LP-357: obsolete field-row CSS and dead head styles are removed", () => {
  assert.ok(!/\.admin-lightning-distribution-event-card-field/.test(CSS), "卡片字段行样式类已被三段式布局替代，不应残留");
  assert.ok(!/\.admin-lightning-distribution-event-card > \.ant-card-head/.test(CSS), "去掉 title/extra 后 ant-card-head 样式不应残留");
});
