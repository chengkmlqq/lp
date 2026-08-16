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

test("LP-399: 筛选栏 Form.Item 与线路管理基线一致（marginBottom 0）", () => {
  assert.match(
    PAGE,
    /<Form\.Item label="关键词" className="admin-filter-keyword-item" style=\{\{ marginBottom: 0 \}\}>/,
    "关键词表单项应设置 marginBottom: 0 与基线一致",
  );
  assert.match(
    PAGE,
    /<Form\.Item style=\{\{ marginBottom: 0 \}\}>/,
    "查询按钮表单项应设置 marginBottom: 0",
  );
});

test("LP-355: lightning card uses a three-section layout without antd title/extra", () => {
  assert.ok(cardBlock, "应能提取 renderRecordCard 组件定义");
  assert.ok(!/title=\{</.test(cardBlock), "卡片不应再使用 antd Card title 作为标题区");
  assert.ok(!/\bextra=\{</.test(cardBlock), "卡片不应再使用 antd Card extra 放置操作菜单");
  assert.match(cardBlock, /flex flex-col/, "卡片内容应为三段式纵向布局");
  assert.ok(!/gap-3/.test(cardBlock), "外层不再依赖 gap-3 承担间距，区块间由边框分隔");
  assert.match(cardBlock, /className="admin-lightning-events-card"/, "卡片应保留 admin-lightning-events-card 容器类");
});

test("LP-355: upper section shows icon + strong truncate title with status tag and border-b divider", () => {
  assert.match(cardBlock, /admin-lightning-events-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200/, "标题区应使用专用标题类并带 px-4 py-3 独立内边距与 border-b 分隔线");
  assert.match(cardBlock, /<ThunderboltOutlined className="text-base text-gray-500" \/>/, "标题区左侧应有代表雷电流的图标");
  assert.match(cardBlock, /<Typography.Text strong className="truncate">/, "标题区应展示强体 truncate 文件名");
  assert.match(cardBlock, /<Tag color=\{meta\.color\}>/, "状态 Tag 应保留在标题区");
});

test("LP-355: middle section renders the LP-322 fields as icon + text rows", () => {
  assert.match(cardBlock, /flex flex-col gap-2 px-4 py-3/, "信息区应有 px-4 py-3 独立内边距");
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

test("LP-355: processing progress bar is preserved in the actions section", () => {
  assert.match(cardBlock, /record\.status === "processing"[\s\S]{0,120}<Progress /, "处理中状态应保留进度条");
  assert.match(cardBlock, /className="mr-auto flex-1 max-w-40"/, "进度条应左对齐推进到右侧按钮区，不破坏右对齐操作按钮");
});

test("LP-355: bottom section holds icon action buttons with a top border divider", () => {
  assert.match(cardBlock, /admin-lightning-events-card-actions flex justify-end px-4 py-2 border-t border-gray-200/, "操作区应使用专用操作类并右对齐、带 px-4 py-2 独立内边距与 border-t 分隔线");
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
  const darkGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-events-card\s*[^,{]*[,{]/;
  assert.match(CSS, darkGroup, "深色模式应覆盖雷电流卡片配色规则");
});

test("LP-388: card body padding is zeroed so dividers span the full card width", () => {
  const bodyBlock = CSS.match(/^\.admin-lightning-events-card > \.ant-card-body \{([^}]*)\}/m)?.[1];
  assert.ok(bodyBlock, "应存在雷电流卡片 body 规则块");
  assert.match(bodyBlock, /padding:\s*0/, "ant-card-body padding 应归零");
  assert.ok(!/padding-block/.test(bodyBlock), "不应再保留 padding-block 设置");
});

test("LP-388: title and actions classes match the line-card theme colors", () => {
  const titleBlock = CSS.match(/^\.admin-lightning-events-card-title \{([^}]*)\}/m)?.[1];
  assert.ok(titleBlock, "应存在 .admin-lightning-events-card-title 规则块");
  assert.match(titleBlock, /border-bottom-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "标题区下边框应使用主色混色");
  assert.match(titleBlock, /background:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "标题区背景应使用主色混色淡背景");
  const actionsBlock = CSS.match(/^\.admin-lightning-events-card-actions \{([^}]*)\}/m)?.[1];
  assert.ok(actionsBlock, "应存在 .admin-lightning-events-card-actions 规则块");
  assert.match(actionsBlock, /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "操作区分隔线应使用主色混色");
});

test("LP-388: dark theme covers title bar and actions divider", () => {
  const headGroup = /:root\[data-fquiz-theme="dark"\]\s[^{]*\.admin-lightning-events-card-title\s*[,{]/;
  assert.match(CSS, headGroup, "深色模式应覆盖雷电流卡片标题区配色规则");
  const actionsRule = /:root\[data-fquiz-theme="dark"\] \.admin-lightning-events-card-actions \{([^}]*)\}/;
  const actionsBlock = CSS.match(actionsRule)?.[1];
  assert.ok(actionsBlock, "应存在暗色主题操作区分隔线规则");
  assert.match(actionsBlock, /border-top-color:\s*color-mix\(in srgb, var\(--fquiz-theme-primary\)/, "暗色主题操作区分隔线应使用主色混色");
  assert.match(actionsBlock, /!important/, "暗色主题规则应带 !important");
});

test("LP-388: pagination bar matches the line-card vertical spacing", () => {
  const block = CSS.match(/^\.admin-lightning-events-pagination \{([^}]*)\}/m)?.[1];
  assert.ok(block, "应存在雷电流卡片分页容器规则");
  assert.match(block, /padding:\s*12px\s+0\s+8px/, "卡片分页容器应使用统一上下边距(顶部12px 底部8px)");
});

test("LP-355: obsolete field-row CSS is removed", () => {
  assert.ok(!/\.admin-lightning-events-card-field/.test(CSS), "卡片字段行样式类已被三段式布局替代，不应残留");
});

test("LP-398: 列表/卡片视图分页 total 使用同一服务端数据源", () => {
  // 列表视图分页 total 不应强制 Math.max(...,1)，应与卡片视图 Pagination 的 total 一致，
  // 避免 total=0 时分页条渲染不一致（列表隐藏、卡片显示）
  assert.ok(
    PAGE.includes("total: recordsQuery.data?.total ?? 0"),
    "列表视图 Table 分页 total 应直接使用服务端 total",
  );
  assert.ok(
    !PAGE.includes("Math.max(recordsQuery.data?.total ?? 0, 1)"),
    "列表视图分页不应再使用 Math.max(...,1) 强制最小 1",
  );
});
