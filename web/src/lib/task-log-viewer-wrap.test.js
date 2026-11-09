import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const VIEWER = readFileSync(join(ROOT, "components/task-log-viewer.tsx"), "utf-8");
const SYSLOG = readFileSync(join(ROOT, "app/admin/syslog/page.tsx"), "utf-8");
const CSS = readFileSync(join(ROOT, "app/globals.css"), "utf-8");

test("LP: 任务日志抽屉超长行按容器宽度折行，且不出现横向滚动条", () => {
  assert.match(VIEWER, /function wrapLogLines\(/, "应存在按可用宽度折行的工具函数");
  assert.match(VIEWER, /overflowX: "hidden"/, "日志容器应禁止横向滚动");
  assert.match(VIEWER, /overflowY: "auto"/, "日志容器应保留纵向滚动");
  assert.ok(
    !VIEWER.includes('overflow: "auto"'),
    "日志容器不应退回双向 overflow:auto（长行会撑出横向滚动条）",
  );
  assert.match(VIEWER, /overflow: "hidden"/, "显示行应有裁剪兜底，避免度量偏差撑宽");
});

test("LP: 折行后仍保持固定行高虚拟滚动（不因换行错位）", () => {
  assert.match(VIEWER, /const displayRows = useMemo\(/, "应派生折行后的显示行");
  assert.match(VIEWER, /displayRows\.slice\(start, end\)/, "虚拟窗口应渲染显示行而非原始逻辑行");
  assert.match(VIEWER, /height: total \* LOG_ROW_HEIGHT/, "滚动高度应按显示行数计算");
  assert.match(VIEWER, /height: LOG_ROW_HEIGHT/, "每个显示行仍是固定行高");
  assert.match(VIEWER, /new ResizeObserver\(measure\)/, "容器宽度变化时重新折行");
  assert.ok(
    !VIEWER.includes("contentRef.current?.clientHeight"),
    "虚拟窗口高度不应在渲染期读取 ref",
  );
});

test("LP: 折行覆盖无空格长串、全角字符与 tab", () => {
  assert.match(VIEWER, /logCharColumns\(ch\)/, "非 ASCII 字符应按实测宽度换算列数");
  assert.match(VIEWER, /Math\.ceil\(width \/ getLogCharWidth\(\)\)/, "列数应由字体实测宽度换算");
  assert.match(VIEWER, /used \+ cols > columns/, "无空格长串应在列边界硬折");
  assert.ok(
    VIEWER.includes("\\u0080-\\uffff"),
    "含非 ASCII 的行应走逐字符慢路径，不能按 length 直接放行",
  );
  assert.ok(
    VIEWER.includes("replace(/\\t/g"),
    "tab 应展开成空格，避免 pre 下占位与度量不一致",
  );
});

test("LP: 系统日志页入参/出参超长内容换行，表格不出现横向滚动条", () => {
  const wrapCount = (SYSLOG.match(/overflowWrap: "anywhere"/g) ?? []).length;
  assert.equal(wrapCount, 4, "表格入参/出参两列 + 卡片两处都应换行");
  assert.ok(SYSLOG.includes('wordBreak: "break-all"'), "长串应允许任意位置断行");
  assert.match(SYSLOG, /ellipsis=\{\{ rows: 3, tooltip: log\.detail \}\}/, "卡片入参应换行后再省略");
  assert.match(SYSLOG, /ellipsis=\{\{ rows: 3, tooltip: log\.output \}\}/, "卡片出参应换行后再省略");
  const tableCss = CSS.match(/\.admin-syslog-table-anchor \.ant-table-body \{[^}]*\}/)?.[0] ?? "";
  assert.match(tableCss, /overflow-x: hidden/, "表格体应有禁止横向滚动的兜底规则");
});
