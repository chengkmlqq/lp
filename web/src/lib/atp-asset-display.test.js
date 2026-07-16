import assert from "node:assert/strict";
import test from "node:test";

import {
  getAtpAssetStatusDisplay,
  getAtpReleaseStatusDisplay,
  getAtpRunStatusDisplay,
  getAtpRunnerKindLabel,
} from "./atp-asset-display.ts";

test("ATP asset and release statuses render in chinese labels", () => {
  assert.deepEqual(getAtpAssetStatusDisplay("enabled"), { label: "启用", color: "green" });
  assert.deepEqual(getAtpAssetStatusDisplay("archived"), { label: "归档", color: "red" });
  assert.deepEqual(getAtpReleaseStatusDisplay("released"), { label: "已发布", color: "green" });
  assert.deepEqual(getAtpRunStatusDisplay("running"), { label: "执行中", color: "gold" });
});

test("runner kinds and unknown values fall back safely", () => {
  assert.equal(getAtpRunnerKindLabel("hybrid"), "混合");
  assert.deepEqual(getAtpRunStatusDisplay("custom"), { label: "custom", color: "blue" });
});
