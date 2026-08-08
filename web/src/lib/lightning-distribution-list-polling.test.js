import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/lightning-distribution/page.tsx");

test("LP-263: list query polls conditionally instead of refetchInterval:false", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");

  // 列表查询不再硬编码 refetchInterval: false，必须按查询数据条件轮询。
  const distributionsQueryBlock = source.match(
    /distributionsQuery = useQuery\([\s\S]*?\n  \}\);/,
  );
  assert.ok(distributionsQueryBlock, "distributionsQuery 定义应存在");

  const block = distributionsQueryBlock[0];
  assert.ok(
    !/refetchInterval:\s*false/.test(block),
    "distributionsQuery 不应再使用 refetchInterval: false（列表刷新不能单点依赖 WebSocket）",
  );
});

test("LP-263: list polling enabled only while pending/processing records exist", () => {
  const source = readFileSync(PAGE_FILE, "utf-8");

  const distributionsQueryBlock = source.match(
    /distributionsQuery = useQuery\([\s\S]*?\n  \}\);/,
  );
  assert.ok(distributionsQueryBlock, "distributionsQuery 定义应存在");
  const block = distributionsQueryBlock[0];

  // 必须基于响应 items 判断是否有进行中记录，并按 ~5s 轮询、全部完成即停止。
  assert.ok(
    /hasActive = items\.some\(\(row\) => row\.status === "pending" \|\| row\.status === "processing"\)/.test(block),
    "存在 pending/processing 记录时才应启用轮询",
  );
  assert.ok(
    /return hasActive \? 5000 : false/.test(block),
    "进行中记录按 5s 轮询，完成后停止（避免常驻高频请求）",
  );
});
