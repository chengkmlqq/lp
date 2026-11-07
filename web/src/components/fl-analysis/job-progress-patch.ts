import type { QueryClient } from "@tanstack/react-query";

import type { FlAnalysisJobListResponse } from "@/types/auth";

/**
 * tower_done（每塔一次的高频事件）：就地 patch 所有防雷任务列表缓存中目标任务的
 * 进度字段，避免整表重取与 loading 遮罩闪烁。
 *
 * 事件 payload 由后端 fl_analysis_service._publish_change 推送，字段：
 * { job_id, run_id, tower_id, tower_no, seq_no, processed, total, risk_level }。
 * 列表进度口径与 types.runningProgressPercent 对齐：
 * percent = (result_tower_count + fractional_progress) / total_tower_count。
 */
export function patchFlJobProgressInListCaches(
  queryClient: QueryClient,
  jobId: string,
  payload: Record<string, unknown>,
): void {
  if (!jobId) {
    return;
  }
  queryClient.setQueriesData<FlAnalysisJobListResponse>(
    {
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && (query.queryKey[0] === "/api/v1/fl-analysis/jobs" || query.queryKey[0].startsWith("/api/v1/fl-analysis/jobs?")),
    },
    (previous) => {
      if (!previous?.items) {
        return previous;
      }
      const processed = typeof payload.processed === "number" ? payload.processed : null;
      const totalCount = typeof payload.total === "number" && payload.total > 0 ? payload.total : null;
      let touched = false;
      const items = previous.items.map((item) => {
        if (item.id !== jobId) {
          return item;
        }
        touched = true;
        return {
          ...item,
          result_tower_count: processed ?? item.result_tower_count,
          total_tower_count: totalCount ?? item.total_tower_count,
          fractional_progress:
            processed !== null && totalCount !== null
              ? Math.max(0, Math.min(1, processed / totalCount))
              : item.fractional_progress,
        };
      });
      return touched ? { ...previous, items } : previous;
    },
  );
}
