import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");

test("lightning-distribution line backfill queries use /api/v1/lines (not 404 /api/v1/power-lines)", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");

  // 后端线路列表接口为 GET /api/v1/lines；/api/v1/power-lines 不存在，会返回 404。
  assert.ok(
    !source.includes("/api/v1/power-lines"),
    "lightning-distribution page must not reference the non-existent /api/v1/power-lines endpoint",
  );

  // 导入弹窗与线路回填弹窗两处查询都应指向真实接口。
  const fetchMatches = source.match(/`\/api\/v1\/lines\?\$\{params\.toString\(\)\}`/g);
  assert.equal(fetchMatches?.length, 2, "both line-fillback queries must hit /api/v1/lines");
});
