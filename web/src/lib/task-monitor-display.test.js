import assert from "node:assert/strict";
import test from "node:test";

import { getTaskDisplayName } from "./celery-task-display.ts";
import {
  formatTaskMonitorDuration,
  formatTaskMonitorErrorMessage,
  getQueueDisplayName,
  getTaskSourceDisplay,
  getTaskStateDisplay,
} from "./task-monitor-display.ts";

test("getTaskStateDisplay returns chinese labels for known celery states", () => {
  assert.deepEqual(getTaskStateDisplay("STARTED"), { label: "执行中", color: "processing" });
  assert.deepEqual(getTaskStateDisplay("FAILURE"), { label: "失败", color: "red" });
  assert.deepEqual(getTaskStateDisplay("TIMEOUT"), { label: "超时", color: "volcano" });
  assert.deepEqual(getTaskStateDisplay("custom_state"), { label: "未识别状态", color: "geekblue" });
});

test("getTaskStateDisplay keeps pending states visually distinct (LP-347)", () => {
  assert.deepEqual(getTaskStateDisplay("TODO"), { label: "待处理", color: "gold" });
  assert.deepEqual(getTaskStateDisplay("PENDING"), { label: "待执行", color: "gold" });
  assert.deepEqual(getTaskStateDisplay("REVOKED"), { label: "已撤销", color: "grey" });
  assert.deepEqual(getTaskStateDisplay("CANCELLED"), { label: "已取消", color: "grey" });
});

test("getTaskSourceDisplay localizes flower task buckets", () => {
  assert.deepEqual(getTaskSourceDisplay("ACTIVE"), { label: "活跃任务", color: "processing" });
  assert.deepEqual(getTaskSourceDisplay("RESERVED"), { label: "预留任务", color: "gold" });
  assert.deepEqual(getTaskSourceDisplay("RECENT"), { label: "最近记录", color: "default" });
});

test("task monitor helpers localize queue names and english errors", () => {
  assert.equal(getQueueDisplayName("celery"), "默认队列");
  assert.equal(getQueueDisplayName("analysis-priority"), "analysis-priority");
  assert.equal(formatTaskMonitorDuration(null), "-");
  assert.equal(formatTaskMonitorDuration(0.5), "< 1 秒");
  assert.equal(formatTaskMonitorDuration(1), "1 秒");
  assert.equal(formatTaskMonitorDuration(59), "59 秒");
  assert.equal(formatTaskMonitorDuration(60), "1 分 0 秒");
  assert.equal(formatTaskMonitorDuration(125), "2 分 5 秒");
  assert.equal(formatTaskMonitorDuration(3599), "59 分 59 秒");
  assert.equal(formatTaskMonitorDuration(3600), "1 时 0 分 0 秒");
  assert.equal(formatTaskMonitorDuration(3661), "1 时 1 分 1 秒");
  assert.equal(formatTaskMonitorDuration(7384), "2 时 3 分 4 秒");
  assert.equal(formatTaskMonitorErrorMessage("flower request timeout: /api/tasks", "任务加载失败"), "任务监控服务请求超时，请稍后重试。");
  assert.equal(formatTaskMonitorErrorMessage("HTTP 502", "任务加载失败"), "任务加载失败（HTTP 502）");
  assert.equal(formatTaskMonitorErrorMessage("任务监控服务异常", "任务加载失败"), "任务监控服务异常");
});

test("getTaskDisplayName hides internal task paths behind chinese labels", () => {
  assert.equal(getTaskDisplayName("app.tasks.fl_analysis_tasks.execute_fl_analysis_job"), "防雷分析计算");
  assert.equal(getTaskDisplayName("app.tasks.scheduled_task_tasks.execute_scheduled_task_job"), "定时任务执行");
  assert.equal(getTaskDisplayName("app.tasks.atp_asset_tasks.process_release_archive_upload"), "ATP 版本归档处理");
  assert.equal(getTaskDisplayName("app.tasks.unknown_tasks.custom_job"), "未识别任务");
});

test("getTaskDisplayName labels LP-206 newly registered tasks", () => {
  assert.equal(getTaskDisplayName("app.tasks.worker_registry_tasks.flush_task_log_buffers"), "任务日志缓冲落库");
});
