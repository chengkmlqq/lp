import assert from "node:assert/strict";
import test from "node:test";

import { normalizeAppRoutePath } from "./app-route-path.ts";

test("normalizeAppRoutePath maps legacy ATP viewer routes to the standalone ATP models route", () => {
  assert.equal(normalizeAppRoutePath("/admin/power-lines/atp-viewer"), "/atp-models");
  assert.equal(normalizeAppRoutePath("/power-lines/atp-viewer"), "/atp-models");
  assert.equal(normalizeAppRoutePath("/admin/atp-models"), "/atp-models");
});
