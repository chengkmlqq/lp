import assert from "node:assert/strict";
import test from "node:test";

import {
  SYNC_TIMEOUT_MS,
  isSyncPending,
  isSyncTimedOut,
  resolveSyncPhase,
} from "./matlab-sync-status.ts";

const NOW = Date.parse("2026-11-21T10:00:00Z");

function minutesAgo(minutes: number): string {
  return new Date(NOW - minutes * 60 * 1000).toISOString();
}

test("pending and running are still syncing before the timeout", () => {
  const pending = { status: "pending", requested_at: minutesAgo(1) };
  assert.equal(isSyncPending(pending), true);
  assert.equal(isSyncTimedOut(pending, NOW), false);
  assert.equal(resolveSyncPhase({ sync_state: pending }, NOW), "syncing");

  const running = { status: "running", requested_at: minutesAgo(1), started_at: minutesAgo(0.5) };
  assert.equal(resolveSyncPhase({ sync_state: running }, NOW), "syncing");
});

test("pending beyond the threshold becomes timeout", () => {
  const stale = { status: "pending", requested_at: minutesAgo(3) };
  assert.equal(isSyncTimedOut(stale, NOW), true);
  assert.equal(resolveSyncPhase({ sync_state: stale }, NOW), "timeout");
  assert.equal(resolveSyncPhase({ sync_state: { status: "running", started_at: minutesAgo(2.1) } }, NOW), "timeout");
});

test("failed wins over timeout and keeps the error state", () => {
  const failed = { status: "failed", requested_at: minutesAgo(5), error: "disk full" };
  assert.equal(resolveSyncPhase({ sync_state: failed }, NOW), "failed");
});

test("deployed wins over any sync state", () => {
  assert.equal(
    resolveSyncPhase({ is_active: true, sync_state: { status: "failed" } }, NOW),
    "deployed",
  );
});

test("completed or missing sync state falls back to idle", () => {
  assert.equal(resolveSyncPhase({ sync_state: { status: "completed" } }, NOW), "idle");
  assert.equal(resolveSyncPhase({}, NOW), "idle");
});

test("missing or invalid timestamps never report timeout", () => {
  assert.equal(isSyncTimedOut({ status: "pending" }, NOW), false);
  assert.equal(isSyncTimedOut({ status: "pending", requested_at: "not-a-date" }, NOW), false);
});

test("custom timeout threshold is respected", () => {
  const state = { status: "pending", requested_at: minutesAgo(1) };
  assert.equal(isSyncTimedOut(state, NOW, 30 * 1000), true);
  assert.equal(SYNC_TIMEOUT_MS, 2 * 60 * 1000);
});
