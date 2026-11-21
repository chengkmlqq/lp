/**
 * MATLAB 引擎版本同步状态判定（LP-55）。
 *
 * 「生效」只是把同步任务投递到队列，页面需要在提交后展示「同步中」，
 * 并在超过阈值仍无完成事件时提示「等待 Worker 超时」——常见原因是队列没有在线消费者。
 * 纯函数抽出便于单测，页面只负责渲染。
 */

/** 提交同步任务后等待 worker 完成的阈值：超过即提示超时（毫秒）。 */
export const SYNC_TIMEOUT_MS = 2 * 60 * 1000;

export type MatlabSyncPhase = "deployed" | "failed" | "timeout" | "syncing" | "idle";

type SyncStateLike =
  | {
      status?: string;
      requested_at?: string;
      started_at?: string;
    }
  | null
  | undefined;

type VersionLike = {
  is_active?: boolean;
  sync_state?: SyncStateLike;
};

/** 同步任务是否仍在队列/执行中（未收到完成或失败事件）。 */
export function isSyncPending(state: SyncStateLike): boolean {
  const status = state?.status;
  return status === "pending" || status === "running";
}

/** 从提交时间起算是否已超过等待阈值；缺时间戳时返回 false（不误报超时）。 */
export function isSyncTimedOut(
  state: SyncStateLike,
  now: number,
  timeoutMs: number = SYNC_TIMEOUT_MS,
): boolean {
  if (!isSyncPending(state)) return false;
  const raw = state?.requested_at || state?.started_at || "";
  const startedAt = Date.parse(raw);
  if (Number.isNaN(startedAt)) return false;
  return now - startedAt > timeoutMs;
}

/**
 * 版本状态优先级：已部署 > 同步失败 > 等待超时 > 同步中 > 未生效/非当前。
 * 失败优先于超时，因为失败有明确错误信息可展示。
 */
export function resolveSyncPhase(version: VersionLike, now: number): MatlabSyncPhase {
  if (version.is_active) return "deployed";
  const state = version.sync_state;
  if (state?.status === "failed") return "failed";
  if (isSyncTimedOut(state, now)) return "timeout";
  if (isSyncPending(state)) return "syncing";
  return "idle";
}
