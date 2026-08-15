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
