import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/lightning-currents/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

const cardBlock = PAGE.match(/const renderRecordCard = \(record: LightningAmplitudeRecord\) => \{[\s\S]*?\n  \};/)?.[0] ?? "";

test("LP-355: lightning card uses a three-section layout without antd title/extra", () => {
  assert.ok(cardBlock, "应能提取 renderRecordCard 组件定义");
  assert.ok(!/title=\{</.test(cardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(cardBlock), "卡片不应再使用 antd Card extra 放置操作菜单");
  assert.match(cardBlock, /flex flex-col gap-3/, "卡片内容应为三段式纵向布局");
  assert.match(cardBlock, /className="admin-lightning-events-card"/, "卡片应保留 admin-lightning-events-card 容器类");
});

test("LP-355: upper section shows icon + strong truncate title with status tag and border-b divider", () => {
  assert.match(cardBlock, /<ThunderboltOutlined className="text-base text-gray-500" \/>/, "标题区左侧应有代表雷电流的图标");
  assert.match(cardBlock, /<Typography.Text strong className="truncate">/, "标题区应展示强体 truncate 文件名");
  assert.match(cardBlock, /<Tag color=\{meta\.color\}>/, "状态 Tag 应保留在标题区");
  assert.match(cardBlock, /border-b border-gray-200/, "标题栏与信息区之间应有 border-b 分隔线");
});

test("LP-355: middle section renders the LP-322 fields as icon + text rows", () => {
  assert.match(cardBlock, /城市：/, "中部应保留城市信息");
  assert.match(cardBlock, /安装位置：/, "中部应保留安装位置信息");
  assert.match(cardBlock, /传感器型号：/, "中部应保留传感器型号信息");
  assert.match(cardBlock, /采样点数：/, "中部应保留采样点数信息");
  assert.match(cardBlock, /采样时间：/, "中部应保留采样时间信息");
  assert.match(cardBlock, /<EnvironmentOutlined /, "城市应带图标");
  assert.match(cardBlock, /<HomeOutlined /, "安装位置应带图标");
  assert.match(cardBlock, /<AppstoreOutlined /, "传感器型号应带图标");
  assert.match(cardBlock, /<NumberOutlined /, "采样点数应带图标");
  assert.match(cardBlock, /<ClockCircleOutlined /, "采样时间应带图标");
  assert.match(cardBlock, /type="secondary" className="text-xs/, "信息行应使用次要色 text-xs 文本");
});

test("LP-355: processing progress bar is preserved in the info section", () => {
  assert.match(cardBlock, /record\.status === "processing"[\s\S]{0,120}<Progress /, "处理中状态应保留进度条");
});

test("LP-355: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(cardBlock, /flex justify-end pt-2 border-t border-gray-200/, "操作区上方应有 border-t 分隔线并右对齐");
  assert.match(cardBlock, /icon=\{<EyeOutlined \/>\}/, "底部应有详情图标按钮");
  assert.match(cardBlock, /type="text"\s*[\s\S]{0,200}size="small"/, "操作按钮应为 text 小号图标按钮");
});

test("LP-355: retry icon button is shown only for failed + canManage", () => {
  assert.match(cardBlock, /record\.status === "failed" && canManage[\s\S]{0,120}icon=\{<RedoOutlined \/>\}/, "重试图标按钮仅在 failed + canManage 时显示");
});

test("LP-355: delete icon button is danger and gated by canManage, keeps MinIO confirm", () => {
  assert.match(cardBlock, /\{canManage &&[\s\S]{0,200}icon=\{<DeleteOutlined \/>\}/, "删除按钮仅在 canManage 时显示");
  assert.match(cardBlock, /\bdanger\b/, "删除按钮应标记 danger");
  assert.match(cardBlock, /Modal\.confirm\(/, "删除应保留二次确认弹窗");
  assert.match(cardBlock, /MinIO/, "删除确认应保留 MinIO 源文件删除提示");
});

test("LP-355: card container keeps LP-311 aligned styling", () => {
  const block = CSS.match(/^\.admin-lightning-events-card \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在 .admin-lightning-events-card 规则块");
  assert.match(block, /color-mix\(in srgb, var\(--fquiz-theme-primary\) 26%/, "边框应使用主色混合色");
  assert.match(block, /linear-gradient/, "卡片应使用渐变背景");
  assert.match(block, /box-shadow: 0 8px 18px/, "卡片应使用统一柔和阴影");
});

test("LP-355: card body/head keeps LP-311 aligned padding and dark theme coverage", () => {
  const bodyBlock = CSS.match(/^\.admin-lightning-events-card > \.ant-card-body \{([^}]*)\}/m)?.[1];
  assert.ok(bodyBlock, "应存在 .admin-lightning-events-card > .ant-card-body 规则块");
  assert.match(bodyBlock, /padding-block: 14px/, "卡片 body 应保持纵向 14px 内边距");
  const darkGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-events-card\s*[^,{]*[,{]/;
  assert.match(CSS, darkGroup, "深色模式应覆盖雷电流卡片配色规则");
});

test("LP-355: obsolete field-row CSS is removed", () => {
  assert.ok(!/\.admin-lightning-events-card-field/.test(CSS), "卡片字段行样式类已被三段式布局替代，不应残留");
});
