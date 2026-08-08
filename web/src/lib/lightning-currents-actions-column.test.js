import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-currents/page.tsx");

test("lightning-currents actions column follows unified UI spec (width 200, 2 direct buttons, dropdown)", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");

  // 提取操作列定义块（从 title: "操作" 到 columns useMemo 闭合）
  const actionsColumnMatch = source.match(/title: "操作",\s+key: "actions"[\s\S]*?\},\n\s+\],/);
  assert.ok(actionsColumnMatch, "actions column definition must exist");
  const col = actionsColumnMatch[0];

  // 操作列宽度统一为 200、固定右侧
  assert.ok(
    /width: 200,\s+fixed: "right",/.test(col),
    "actions column must be width 200 and fixed right",
  );

  // 默认仅 2 个直接按钮：详情、删除
  assert.ok(
    col.includes("onClick={() => openDetail(row)}"),
    "详情 must be a direct button calling openDetail",
  );
  assert.ok(
    />\s*删除\s*<\/Button>/.test(col),
    "删除 must be a direct button (not inside dropdown menu)",
  );

  // 详情/删除不在下拉菜单中
  assert.ok(!col.includes('key: "detail"'), "actions column must not have detail as dropdown item");
  assert.ok(!col.includes('key: "delete"'), "actions column must not have delete as dropdown item");

  // 条件操作（重试/杆塔列表）收进 MoreOutlined 三点下拉
  assert.ok(
    col.includes('key: "retry"') && col.includes('label: "重试"'),
    "retry must be a dropdown menu item",
  );
  assert.ok(
    col.includes('key: "towers"') && col.includes('label: "杆塔列表"'),
    "tower list must be a dropdown menu item",
  );

  // 权限（canManage）与状态（failed）条件保留
  assert.ok(
    col.includes('row.status === "failed" && canManage'),
    "retry must keep failed + canManage conditions",
  );
  assert.ok(
    col.includes("loading={deleteMutation.isPending}"),
    "delete must keep deleteMutation loading",
  );

  // 危险操作（删除）保留 danger 样式与 Modal.confirm 二次确认
  assert.ok(
    /<Button\s+size="small"\s+danger/.test(col),
    "delete button must keep danger style",
  );
  assert.ok(
    col.includes("Modal.confirm({") && col.includes("okButtonProps: { danger: true }"),
    "delete must keep Modal.confirm with danger okButtonProps",
  );
});
