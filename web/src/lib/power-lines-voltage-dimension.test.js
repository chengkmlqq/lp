import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGE_FILE = join(__dirname, "../app/admin/power-lines/page.tsx");
const PAGE = readFileSync(PAGE_FILE, "utf-8");

test("LP-29: 电压等级选项来自维度管理 hook 而非硬编码常量", () => {
  assert.match(PAGE, /import \{ useDimensionOptions \} from "@\/hooks\/use-dimension-options"/);
  assert.match(PAGE, /useDimensionOptions\(\s*\{ voltage_level: "voltage_level" \}/);
  assert.match(PAGE, /dimensionOptionMap\.voltage_level/);
  assert.ok(!/LINE_VOLTAGE_OPTIONS/.test(PAGE), "不应再保留硬编码 LINE_VOLTAGE_OPTIONS");
  assert.ok(!/LINE_VOLTAGE_VALUE_TO_KV/.test(PAGE), "不应再保留硬编码 value→kv 映射");
  assert.ok(!/LINE_VOLTAGE_KV_TO_DEFAULT_OPTION/.test(PAGE), "不应再保留硬编码 kv→option 映射");
  assert.ok(!/resolveVoltageOptionFromKv/.test(PAGE), "不应再保留硬编码回显函数");
  assert.ok(!/ac_110_x4|dc_500/.test(PAGE), "不应再出现交直流/同塔 x4 硬编码编码");
});

test("LP-29: 提交仍以 Number(code) 传 voltage_kv，编辑以 String(kv) 回显", () => {
  assert.match(PAGE, /voltage_kv:\s*values\.voltage_level\s*\?\s*Number\(values\.voltage_level\)\s*:\s*null/);
  assert.match(PAGE, /voltage_level:\s*line\.voltage_kv\s*!=\s*null\s*\?\s*String\(line\.voltage_kv\)\s*:\s*null/);
});

test("LP-29: 历史非标 kV 有兜底回显选项", () => {
  assert.match(PAGE, /editingVoltageValue/);
  assert.match(PAGE, /kV（历史值）/);
  assert.match(PAGE, /!voltageKvOptions\.some\(\(item\) => item\.value === editingVoltageValue\)/);
});

test("LP-29: 维度接口不可用时给空态提示，不回退到硬编码", () => {
  assert.match(PAGE, /dimensionOptionsLoading/);
  assert.match(PAGE, /暂无可用电压等级，请在维度管理中配置/);
  assert.match(PAGE, /options=\{voltageOptions\}/);
});
