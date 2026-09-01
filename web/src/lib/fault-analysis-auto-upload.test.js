import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const TEMP_UPLOAD_FILE = join(__dirname, "../components/fault-analysis/temp-file-upload.tsx");
const PAGE_FILE = join(__dirname, "../app/admin/fault-analysis/page.tsx");

const TEMP_UPLOAD = readFileSync(TEMP_UPLOAD_FILE, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-385: multiple file selection adds pending items as one state update", () => {
  assert.ok(
    TEMP_UPLOAD.includes("const pendingItems = pairs.map"),
    "多文件选择应先生成完整 pending 列表",
  );
  assert.ok(
    TEMP_UPLOAD.includes("patchValue((items) => [...items, ...pendingItems])"),
    "多文件选择应使用单次状态更新追加全部 pending 文件",
  );
});

test("LP-385: 两段式上传提交携带每个已完成临时文件 id，未完成时阻止提交", () => {
  assert.ok(
    PAGE.includes("hasPendingUploads("),
    "提交前应检查各文件字段是否存在未完成上传",
  );
  assert.ok(
    PAGE.includes("仍有文件在上传中，请等待上传完成后提交"),
    "存在未完成上传时必须阻止提交并给出提示",
  );
  assert.ok(
    PAGE.includes("pickTempFileIds(list)"),
    "行波等可多文件字段应遍历提交全部已完成临时文件 id",
  );
  assert.ok(
    PAGE.includes("pickTempFileId(list)"),
    "单文件字段应提取已完成临时文件 id",
  );
  assert.ok(
    PAGE.includes("/api/v1/fault-analysis/upload"),
    "两段式上传应提交到 /api/v1/fault-analysis/upload",
  );
});
