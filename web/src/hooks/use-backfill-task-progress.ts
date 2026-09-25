"use client";

import { useEffect, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

/** 回填任务的终态（进入终态后不再轮询）。 */
export const BACKFILL_TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "success"]);

/** 单条任务的进度补丁（含原始响应，供调用方按需取收尾字段）。 */
export type BackfillTaskPatch = {
  taskId: string;
  status: string;
  progress: number;
  errorMessage: string | null;
  /** 单任务接口的原始响应（幅值是 {task: {...}}，密度是扁平摘要，由任务的解析器取出） */
  raw: Record<string, unknown>;
};

type Options<TItem> = {
  /** 当前列表行：用来推断「现在有哪些任务在跑」 */
  items: TItem[];
  /** 从一行取出回填任务 id；返回 null 表示该行不参与轮询 */
  getTaskId: (item: TItem) => string | null;
  /** 从一行取出状态（终态则该行不再轮询） */
  getStatus: (item: TItem) => string;
  /** 单任务进度接口路径 */
  taskPath: (taskId: string) => string;
  /** 把响应体解析成 {status, progress, error_message}；不同接口结构不同 */
  parseTask: (payload: Record<string, unknown>) => {
    status: string;
    progress: number;
    errorMessage: string | null;
  };
  /** 判断某个缓存查询是否就是本列表（用于就地合并） */
  matchQueryKey: (queryKey: readonly unknown[]) => boolean;
  /** 把补丁合并进一行；返回同一引用表示无变化（避免无谓重渲染） */
  mergeItem: (item: TItem, patch: BackfillTaskPatch) => TItem;
  enabled: boolean;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  /** 轮询间隔，默认 3s */
  intervalMs?: number;
};

/**
 * 回填任务进度「按记录就地更新」。
 *
 * 只请求**仍在进行中**的那几条任务，并把结果直接合并进 react-query 缓存的对应行；
 * 不重新请求整个列表、不触发表格 loading —— 页面上只有那一条记录的进度条在动。
 *
 * 收尾字段（幅值/杆塔数/密度等）由单任务接口一并返回，也通过 mergeItem 就地写入，
 * 因此任务完成时同样**不需要**刷新列表。
 */
export function useBackfillTaskProgressSync<TItem>({
  items,
  getTaskId,
  getStatus,
  taskPath,
  parseTask,
  matchQueryKey,
  mergeItem,
  enabled,
  fetchWithAuth,
  intervalMs = 3000,
}: Options<TItem>) {
  const queryClient = useQueryClient();

  // 只轮询进行中的任务；全部终态后自动为空 → 查询停摆
  const activeTaskIds = useMemo(() => {
    const ids: string[] = [];
    for (const item of items) {
      if (BACKFILL_TERMINAL_STATUSES.has(getStatus(item))) {
        continue;
      }
      const id = getTaskId(item);
      if (id) {
        ids.push(id);
      }
    }
    return Array.from(new Set(ids));
  }, [items, getTaskId, getStatus]);

  const progressQuery = useQuery<BackfillTaskPatch[]>({
    queryKey: ["backfill-task-progress", activeTaskIds],
    enabled: enabled && activeTaskIds.length > 0,
    refetchInterval: intervalMs,
    // 轮询本身不展示 loading，避免任何闪烁
    queryFn: async () => {
      const results = await Promise.all(
        activeTaskIds.map(async (taskId) => {
          const response = await fetchWithAuth(taskPath(taskId));
          if (!response.ok) {
            return null;
          }
          const payload = (await response.json()) as Record<string, unknown>;
          const parsed = parseTask(payload);
          const patch: BackfillTaskPatch = {
            taskId,
            status: parsed.status,
            progress: parsed.progress,
            errorMessage: parsed.errorMessage,
            raw: payload,
          };
          return patch;
        }),
      );
      return results.filter((item): item is BackfillTaskPatch => item !== null);
    },
  });

  // 已合并过的「任务 → 进度」快照：值没变就不动缓存，彻底零重渲染
  const appliedRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    const updates = progressQuery.data;
    if (!updates || updates.length === 0) {
      return;
    }
    const changed = updates.filter((item) => {
      const signature = `${item.status}|${item.progress}|${item.errorMessage ?? ""}`;
      return appliedRef.current.get(item.taskId) !== signature;
    });
    if (changed.length === 0) {
      return;
    }
    const byTaskId = new Map(changed.map((item) => [item.taskId, item]));

    // 就地合并：只改缓存里的对应行，不发起任何列表请求
    queryClient.setQueriesData<{ items?: TItem[]; total?: number }>(
      { predicate: (query) => matchQueryKey(query.queryKey) },
      (previous) => {
        if (!previous || !Array.isArray(previous.items)) {
          return previous;
        }
        let touched = false;
        const nextItems = previous.items.map((item) => {
          const id = getTaskId(item);
          if (!id) {
            return item;
          }
          const patch = byTaskId.get(id);
          if (!patch) {
            return item;
          }
          const merged = mergeItem(item, patch);
          if (merged !== item) {
            touched = true;
          }
          return merged;
        });
        return touched ? { ...previous, items: nextItems } : previous;
      },
    );

    for (const item of changed) {
      appliedRef.current.set(item.taskId, `${item.status}|${item.progress}|${item.errorMessage ?? ""}`);
    }
  }, [progressQuery.data, queryClient, getTaskId, matchQueryKey, mergeItem]);

  return { activeTaskIds };
}
