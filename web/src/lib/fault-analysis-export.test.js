import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DETAIL_FILE = join(__dirname, "../components/fault-analysis/analysis-detail-view.tsx");
const PAGE_FILE = join(__dirname, "../app/admin/fault-analysis/page.tsx");

const DETAIL = readFileSync(DETAIL_FILE, "utf-8");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-402: 详情页导出走后端 report 接口生成 Word 报告", () => {
  // 详情视图的导出统一由 ReportView「导出报告」按钮触发，调用后端 /report 接口
  assert.ok(
    DETAIL.includes("/api/v1/fault-analysis/${analysisId}/report"),
    "动态 Tab 详情导出应调用后端 /report 接口",
  );
  assert.ok(
    DETAIL.includes("导出报告"),
    "详情报告工具栏应展示「导出报告」按钮",
  );
  assert.ok(
    DETAIL.includes("handleExportReport"),
    "导出处理函数应为 handleExportReport",
  );
});

test("LP-402: 前端不再拼装导出文档（exportToPDF/exportToWord 已移除）", () => {
  assert.ok(
    !DETAIL.includes("exportToPDF") && !DETAIL.includes("exportToWord"),
    "动态 Tab 详情不得再引用 exportToPDF/exportToWord",
  );
  assert.ok(
    !PAGE.includes("exportToPDF") && !PAGE.includes("exportToWord"),
    "列表页不得再引用 exportToPDF/exportToWord",
  );
  assert.ok(
    !DETAIL.includes("/export-matlab"),
    "详情不得再引用已下线的 /export-matlab 引擎产物导出",
  );
});

test("LP-402: 下载文件名按报告语义命名（标题_故障分析报告.docx）", () => {
  assert.ok(
    DETAIL.includes("_故障分析报告.docx"),
    "导出文件名应包含「故障分析报告」语义后缀",
  );
});
