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

test("LP-385: auto-classify request sends every completed temp file id", () => {
  assert.ok(
    PAGE.includes("const completedAutoFiles = autoFiles.filter"),
    "提交前应明确筛选上传完成的自动识别文件",
  );
  assert.ok(
    PAGE.includes("completedAutoFiles.length !== autoFiles.length"),
    "自动识别文件未全部完成时必须阻止提交",
  );
  assert.ok(
    PAGE.includes("for (const item of completedAutoFiles)"),
    "FormData 必须遍历每个已完成的自动识别文件",
  );
  assert.ok(
    PAGE.includes("formData.getAll(\"auto_classify_temp_file_ids\").length"),
    "提交前应校验 FormData 中的临时文件 ID 数量",
  );
});
