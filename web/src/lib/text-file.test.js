import assert from "node:assert/strict";
import test from "node:test";

import { decodeTextBytes } from "./text-file.ts";

test("decodeTextBytes keeps utf-8 ATP text intact", () => {
  const bytes = new TextEncoder().encode("中文ATP线路");
  const decoded = decodeTextBytes(bytes);

  assert.equal(decoded.encoding, "utf-8");
  assert.equal(decoded.text, "中文ATP线路");
});

test("decodeTextBytes falls back to gb18030 for gbk ATP text", () => {
  const bytes = Uint8Array.from([214, 208, 206, 196, 65, 84, 80, 207, 223, 194, 183]);
  const decoded = decodeTextBytes(bytes);

  assert.equal(decoded.encoding, "gb18030");
  assert.equal(decoded.text, "中文ATP线路");
});

test("decodeTextBytes detects utf-16le ATP text without bom", () => {
  const bytes = Uint8Array.from(Buffer.from("ATP线路", "utf16le"));
  const decoded = decodeTextBytes(bytes);

  assert.equal(decoded.encoding, "utf-16le");
  assert.equal(decoded.text, "ATP线路");
});
