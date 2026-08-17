import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/fault-analysis/[id]/page.tsx");
const DETAIL_FILE = join(__dirname, "../components/fault-analysis/analysis-detail-view.tsx");
const EXPORT_UTILS_FILE = join(__dirname, "../lib/export-utils.ts");

const PAGE = readFileSync(PAGE_FILE, "utf-8");
const DETAIL = readFileSync(DETAIL_FILE, "utf-8");

test("LP-402: 导出按钮改为调用后端 export-matlab 接口，不再前端拼文档", () => {
  // 两个入口（独立详情页 + 动态 Tab 详情）都应调用后端导出接口
  assert.ok(
    PAGE.includes("/export-matlab"),
    "独立详情页导出应调用后端 /export-matlab 接口",
  );
  assert.ok(
    DETAIL.includes("/export-matlab"),
    "动态 Tab 详情导出应调用后端 /export-matlab 接口",
  );
  assert.ok(
    PAGE.includes("导出引擎产物"),
    "导出下拉应展示「导出引擎产物」项",
  );
  assert.ok(
    DETAIL.includes("导出引擎产物"),
    "动态 Tab 导出下拉应展示「导出引擎产物」项",
  );
});

test("LP-402: 前端拼文档逻辑已移除（export-utils 不再被故障分析页面引用）", () => {
  assert.ok(
    !PAGE.includes("exportToPDF") && !PAGE.includes("exportToWord"),
    "独立详情页不得再引用 exportToPDF/exportToWord",
  );
  assert.ok(
    !DETAIL.includes("exportToPDF") && !DETAIL.includes("exportToWord"),
    "动态 Tab 详情不得再引用 exportToPDF/exportToWord",
  );
  assert.ok(
    PAGE.includes("handleExportMatlab") && DETAIL.includes("handleExportMatlab"),
    "导出处理函数应为 handleExportMatlab",
  );
  // export-utils.ts 已删除（无其他调用方），避免残留死代码
  assert.ok(
    !existsSync(EXPORT_UTILS_FILE),
    "export-utils.ts 已无引用，应删除",
  );
});

test("LP-402: 下载文件名优先取后端 Content-Disposition", () => {
  assert.ok(
    PAGE.includes('disposition.match(/filename\\*=UTF-8\'\'([^;]+)/i)'),
    "前端应解析 RFC 5987 filename* 中文文件名",
  );
  assert.ok(
    DETAIL.includes('disposition.match(/filename\\*=UTF-8\'\'([^;]+)/i)'),
    "动态 Tab 前端应解析 RFC 5987 filename* 中文文件名",
  );
});