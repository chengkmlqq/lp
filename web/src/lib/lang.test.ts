import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveInitialLang } from "./lang.ts";

test("localStorage 有值优先于 bootstrap", () => {
  assert.equal(resolveInitialLang("zh", "en"), "zh");
  assert.equal(resolveInitialLang("en", "zh"), "en");
});

test("localStorage 无值取 bootstrap", () => {
  assert.equal(resolveInitialLang(null, "en"), "en");
  assert.equal(resolveInitialLang(undefined, "zh"), "zh");
  assert.equal(resolveInitialLang("", "en"), "en");
});

test("bootstrap 缺失回落 zh", () => {
  assert.equal(resolveInitialLang(null, null), "zh");
  assert.equal(resolveInitialLang(undefined, undefined), "zh");
});

test("非法值一律忽略", () => {
  assert.equal(resolveInitialLang("fr", "en"), "en");
  assert.equal(resolveInitialLang("zh-CN", "fr"), "zh");
});
