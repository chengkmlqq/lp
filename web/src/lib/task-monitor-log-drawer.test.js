import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/task-monitor/page.tsx");

const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-356: log drawer content is a flex column filling the drawer height", () => {
  const drawerBlock = PAGE.match(/<Drawer[\s\S]*?<\/Drawer>/)?.[0];
  assert.ok(drawerBlock, "应存在任务执行日志 Drawer");
  assert.match(
    drawerBlock,
    /<div[\s\S]{0,120}style=\{\{ display: "flex", flexDirection: "column", height: "100%" \}\}/,
    "抽屉内容区应为纵向 flex 布局并占满剩余高度",
  );
});

test("LP-356: log pre area stretches to fill remaining space and scrolls internally", () => {
  const preBlock = PAGE.match(/<pre\s+ref=\{logModalContentRef\}[\s\S]*?<\/pre>/)?.[0];
  assert.ok(preBlock, "应存在日志展示 pre 区块");
  assert.match(preBlock, /flex: 1/, "日志区应通过 flex:1 占满剩余高度");
  assert.match(preBlock, /minHeight: 0/, "日志区应保留 minHeight:0 以支持内部滚动");
  assert.match(preBlock, /overflow: "auto"/, "日志区应保留内部滚动");
  assert.ok(!/maxHeight: "60vh"/.test(preBlock), "日志区不应再使用 60vh 固定高度");
});

test("LP-386: task monitor query key includes a submit version and table stays mounted while loading", () => {
  assert.match(
    PAGE,
    /const \[searchVersion, setSearchVersion\] = useState\(0\);/,
    "应存在查询提交版本状态，用于每次点击查询都触发新请求",
  );
  assert.match(
    PAGE,
    /queryKey: \["task-monitor-overview", paginationCurrent, paginationPageSize, taskKeyword, searchVersion\],/,
    "表格查询 key 应包含提交版本，避免相同条件重复查询被缓存吞掉",
  );
  assert.match(
    PAGE,
    /queryKey: \["task-monitor-overview-card", cardViewPage, paginationPageSize, taskKeyword, searchVersion\],/,
    "卡片视图查询 key 也应同步包含提交版本",
  );
  assert.match(
    PAGE,
    /setSearchVersion\(\(prev\) => prev \+ 1\);/,
    "点击查询时应提升提交版本",
  );
  assert.ok(
    !/overviewData \?\s*\(/.test(PAGE),
    "表格区不应再依赖 overviewData 条件渲染整个 Table",
  );
  assert.match(
    PAGE,
    /rowKey=\{\(record\) => record\.task_id\}/,
    "表格 rowKey 应使用稳定的任务主键",
  );
});
