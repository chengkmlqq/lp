import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GLOBALS_CSS = join(__dirname, "../app/globals.css");
const PAGE_FILE = join(__dirname, "../app/admin/elevation-records/page.tsx");

const CSS = readFileSync(GLOBALS_CSS, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

const cardBlock = PAGE.match(/const renderRecordCard = \(record: ElevationFileRecordSummary\) => \{[\s\S]*?\n  \};/)?.[0] ?? "";

test("LP-358: elevation card uses a three-section layout without antd title/extra", () => {
  assert.ok(cardBlock, "应能提取 renderRecordCard 组件定义");
  assert.ok(!/title=\{</.test(cardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(cardBlock), "卡片不应再使用 antd Card extra 放置操作按钮");
  assert.match(cardBlock, /flex flex-col gap-3/, "卡片内容应为三段式纵向布局");
  assert.match(cardBlock, /className="admin-elevation-record-card"/, "卡片应保留 admin-elevation-record-card 容器类");
  assert.match(cardBlock, /\bhoverable\b/, "卡片应保留 hoverable");
});

test("LP-358: upper section shows icon + strong truncate title with status tag and border-b divider", () => {
  assert.match(cardBlock, /<FileOutlined className="text-base text-gray-500" \/>/, "标题区左侧应有代表高程文件的图标");
  assert.match(cardBlock, /<Typography.Text strong className="truncate min-w-0 flex-1">/, "标题区应展示强体 truncate 文件名");
  assert.match(cardBlock, /<Tag color=\{statusTagColor\(record\.status\)\}>/, "文件状态 Tag 应保留在标题区");
  assert.match(cardBlock, /border-b border-gray-200/, "标题栏与信息区之间应有 border-b 分隔线");
});

test("LP-358: middle section renders the 7 elevation fields as icon + text-xs rows", () => {
  assert.match(cardBlock, /格式：/, "中部应保留格式信息");
  assert.match(cardBlock, /大小：/, "中部应保留大小信息");
  assert.match(cardBlock, /来源：/, "中部应保留来源信息");
  assert.match(cardBlock, /分辨率：/, "中部应保留分辨率信息");
  assert.match(cardBlock, /样本数：/, "中部应保留样本数信息");
  assert.match(cardBlock, /解析状态：/, "中部应保留解析状态信息");
  assert.match(cardBlock, /关联线路：/, "中部应保留关联线路信息");
  assert.match(cardBlock, /<FileTextOutlined className="text-xs text-gray-500" \/>/, "格式应带图标");
  assert.match(cardBlock, /<DatabaseOutlined /, "大小应带图标");
  assert.match(cardBlock, /<GlobalOutlined /, "来源应带图标");
  assert.match(cardBlock, /<AppstoreOutlined /, "分辨率应带图标");
  assert.match(cardBlock, /<NumberOutlined /, "样本数应带图标");
  assert.match(cardBlock, /<CheckCircleOutlined /, "解析状态应带图标");
  assert.match(cardBlock, /<DeploymentUnitOutlined /, "关联线路应带图标");
  assert.match(cardBlock, /type="secondary" className="text-xs/, "信息行应使用次要色 text-xs 文本");
});

test("LP-358: parse status tag keeps its color and format tag is retained as text-xs", () => {
  assert.match(cardBlock, /<Tag color=\{computedParseStatus\(record\)\.color\} className="text-xs">/, "解析状态应保留彩色 Tag");
  assert.match(cardBlock, /<Tag className="text-xs">\{record\.file_format\.toUpperCase\(\)\}<\/Tag>/, "格式应保留 text-xs Tag");
});

test("LP-358: linked-lines modal button is preserved", () => {
  assert.match(cardBlock, /openLinkedLinesModal\(record\)/, "关联线路应保留弹窗入口");
  assert.match(cardBlock, /record\.linked_line_count \?\? 0/, "关联线路应保留条数");
});

test("LP-358: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(cardBlock, /flex justify-end pt-2 border-t border-gray-200/, "操作区上方应有 border-t 分隔线并右对齐");
  assert.match(cardBlock, /icon=\{<EyeOutlined \/>\}/, "底部应有预览图标按钮");
  assert.match(cardBlock, /icon=\{<CloudUploadOutlined \/>\}/, "底部应有回填图标按钮");
  assert.match(cardBlock, /<Dropdown menu=\{\{ items: moreMenuItems \}\}/, "底部应有更多下拉按钮");
  assert.match(cardBlock, /disabled=\{rowBusy\}/, "操作按钮应保留 rowBusy 禁用态");
});

test("LP-358: delete stays in the more dropdown as danger with confirm", () => {
  assert.match(cardBlock, /key: "delete"/, "更多菜单应保留删除项");
  assert.match(cardBlock, /\bdanger: true\b/, "删除菜单项应标记 danger");
  assert.match(cardBlock, /Modal\.confirm\(/, "删除应保留二次确认弹窗");
  assert.match(cardBlock, /deleteMutation\.mutate\(record\.id\)/, "删除应保留删除调用");
});

test("LP-358: card container grid matches the power-lines pattern", () => {
  assert.match(PAGE, /grid gap-3 md:grid-cols-2 xl:grid-cols-4/, "卡片视图容器应使用 grid gap-3 2列/4列布局");
  assert.ok(!/Row gutter=\{\[12, 12\]\}/.test(PAGE), "卡片视图不应再使用 antd Row/Col 布局");
  assert.match(PAGE, /renderRecordCard\(recordItem\)/, "卡片渲染调用应保留");
});

test("LP-358: scroll-loading logic is preserved", () => {
  assert.match(PAGE, /pageCardRef/, "滚动加载应保留 pageCardRef");
  assert.match(PAGE, /setCardViewPage\(\(prev\) => prev \+ 1\)/, "触底加载下一页逻辑应保留");
  assert.match(PAGE, /isLoadingMore/, "加载更多状态应保留");
});

test("LP-358: card container keeps LP-301 aligned styling", () => {
  const block = CSS.match(/^\.admin-elevation-record-card \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在 .admin-elevation-record-card 规则块");
  assert.match(block, /color-mix\(in srgb, var\(--fquiz-theme-primary\) 26%/, "边框应使用主色混合色");
  assert.match(block, /linear-gradient/, "卡片应使用渐变背景");
  assert.match(block, /box-shadow: 0 8px 18px/, "卡片应使用统一柔和阴影");
});

test("LP-358: card body/head keeps aligned padding and dark theme coverage", () => {
  const bodyBlock = CSS.match(/^\.admin-elevation-record-card > \.ant-card-body \{([^}]*)\}/m)?.[1];
  assert.ok(bodyBlock, "应存在 .admin-elevation-record-card > .ant-card-body 规则块");
  assert.match(bodyBlock, /padding-block: 14px/, "卡片 body 应保持纵向 14px 内边距");
  const headBlock = CSS.match(/^\.admin-elevation-record-card > \.ant-card-head \{([^}]*)\}/m)?.[1];
  assert.ok(headBlock, "应存在 .admin-elevation-record-card > .ant-card-head 规则块");
  assert.match(headBlock, /min-height: 44px/, "卡片 head 应保持 44px 高度");
  const darkBlock = CSS.match(/:root\[data-fquiz-theme="dark"\] \.admin-elevation-record-card \{([^}]*)\}/m)?.[1];
  assert.ok(darkBlock, "应存在深色模式卡片规则");
  assert.match(darkBlock, /!important/, "深色模式规则应带 !important");
});

test("LP-358: card-view-content padding is aligned with the power-lines scroll container", () => {
  const block = CSS.match(/^\.admin-elevation-card-view-content \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在 .admin-elevation-card-view-content 规则块");
  assert.doesNotMatch(block, /padding: 2px 2px 4px/, "内容容器不应再保留旧的 2px 2px 4px 内边距");
});

test("LP-358: obsolete field-row CSS is removed", () => {
  assert.ok(!/\.admin-elevation-record-card-field/.test(CSS), "卡片字段行样式类已被三段式布局替代，不应残留");
});
