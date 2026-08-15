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
  assert.match(cardBlock, /flex flex-col gap-3/, "卡片内容应为三段式纵向布局");
  assert.match(cardBlock, /className="admin-lightning-distribution-event-card"/, "卡片应保留 admin-lightning-distribution-event-card 容器类");
  assert.match(cardBlock, /hoverable/, "卡片应保留 hoverable");
});

test("LP-357: upper section shows icon + strong truncate title with status tag and border-b divider", () => {
  assert.match(cardBlock, /<ThunderboltOutlined className="text-base text-gray-500" \/>/, "标题区左侧应有代表地闪的图标");
  assert.match(cardBlock, /<Typography.Text strong className="truncate/, "标题区应展示强体 truncate 文件名");
  assert.match(cardBlock, /<Tag color=\{meta\.color\}>/, "状态 Tag 应保留在标题区");
  assert.match(cardBlock, /border-b border-gray-200/, "标题栏与信息区之间应有 border-b 分隔线");
});

test("LP-357: middle section renders the seven fields as icon + text rows", () => {
  assert.match(cardBlock, /城市：/, "中部应保留城市信息");
  assert.match(cardBlock, /地点标签：/, "中部应保留地点标签信息");
  assert.match(cardBlock, /导入时间：/, "中部应保留导入时间信息");
  assert.match(cardBlock, /有效点数：/, "中部应保留有效点数信息");
  assert.match(cardBlock, /整体 Ng：/, "中部应保留整体 Ng 信息");
  assert.match(cardBlock, /最大电流：/, "中部应保留最大电流信息");
  assert.match(cardBlock, /平均电流：/, "中部应保留平均电流信息");
  assert.match(cardBlock, /<EnvironmentOutlined /, "城市应带图标");
  assert.match(cardBlock, /<TagOutlined /, "地点标签应带图标");
  assert.match(cardBlock, /<ClockCircleOutlined /, "导入时间应带图标");
  assert.match(cardBlock, /<NumberOutlined /, "有效点数应带图标");
  assert.match(cardBlock, /<ThunderboltOutlined className="text-xs text-gray-500" \/>/, "整体 Ng 应带图标");
  assert.match(cardBlock, /<BarChartOutlined /, "最大电流/平均电流应带图标");
  assert.match(cardBlock, /type="secondary" className="text-xs/, "信息行应使用次要色 text-xs 文本");
});

test("LP-357: processing progress bar is preserved in the info section", () => {
  assert.match(cardBlock, /record\.status === "processing"[\s\S]{0,120}<Progress /, "处理中状态应保留进度条");
});

test("LP-357: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(cardBlock, /flex justify-end pt-2 border-t border-gray-200/, "操作区上方应有 border-t 分隔线并右对齐");
  assert.match(cardBlock, /icon=\{<EyeOutlined \/>\}/, "底部应有详情图标按钮");
  assert.match(cardBlock, /type="text"\s*[\s\S]{0,200}size="small"/, "操作按钮应为 text 小号图标按钮");
});

test("LP-357: detail moved out of dropdown to the Eye icon button; other actions kept in More dropdown", () => {
  assert.ok(!/key: "image"/.test(cardBlock), "下拉中不应再包含详情项");
  assert.doesNotMatch(cardBlock, /label: "详情"/, "下拉中不应再包含详情菜单项");
  assert.match(cardBlock, /openDetail\(record\)/, "详情应由 Eye 图标按钮打开");
  assert.match(cardBlock, /label: "导入日志"/, "下拉应保留导入日志");
  assert.match(cardBlock, /label: "绘图日志"/, "下拉应保留绘图日志");
  assert.match(cardBlock, /label: "绘图"/, "下拉应保留绘图");
  assert.match(cardBlock, /label: "删除"/, "下拉应保留删除");
  assert.match(cardBlock, /Modal\.confirm\(/, "删除应保留二次确认弹窗");
  assert.match(cardBlock, /danger: true as const/, "删除菜单项应标记 danger");
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

test("LP-357: obsolete field-row CSS and dead head styles are removed", () => {
  assert.ok(!/\.admin-lightning-distribution-event-card-field/.test(CSS), "卡片字段行样式类已被三段式布局替代，不应残留");
  assert.ok(!/\.admin-lightning-distribution-event-card > \.ant-card-head/.test(CSS), "去掉 title/extra 后 ant-card-head 样式不应残留");
});
