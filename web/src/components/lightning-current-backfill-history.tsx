"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { Dayjs } from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  DatePicker,
  Descriptions,
  Dropdown,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { MenuProps } from "antd";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { MoreOutlined } from "@ant-design/icons";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useBackfillTaskProgressSync, type BackfillTaskPatch } from "@/hooks/use-backfill-task-progress";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { readApiError } from "@/lib/api";
import type {
  LineListResponse,
  LineSummary,
  LightningAmplitudeBackfillLine,
  LightningAmplitudeBackfillLineListResponse,
  LightningCurrentBackfillTaskDetail,
  LightningCurrentBackfillTaskListResponse,
  LightningCurrentBackfillTaskSummary,
  LightningCurrentBackfillTowerDetail,
} from "@/types/auth";

const BACKFILL_HISTORY_MIN_SCROLL_Y = 180;
const BACKFILL_HISTORY_ESTIMATED_HEADER_HEIGHT = 56;
const BACKFILL_HISTORY_ESTIMATED_PAGINATION_HEIGHT = 64;
const BACKFILL_HISTORY_BOTTOM_GAP = 8;

type LightningCurrentBackfillHistoryTableProps = {
  amplitudeId?: string;
};

/** 回填任务状态 → 标签文案 / 标签色 / 进度条状态（逐行进度条用）。 */
const BACKFILL_STATUS_META: Record<
  string,
  { label: string; tagColor: string; progressStatus: "normal" | "active" | "success" | "exception" }
> = {
  pending: { label: "排队中", tagColor: "default", progressStatus: "normal" },
  processing: { label: "处理中", tagColor: "processing", progressStatus: "active" },
  completed: { label: "已完成", tagColor: "success", progressStatus: "success" },
  failed: { label: "失败", tagColor: "error", progressStatus: "exception" },
};

/**
 * 渲染「回填状态 + 进度条」单元格。
 *
 * 一次回填 = 一条记录：进度条落在该记录**自己的那一行**里，
 * 多条回填任务各占一行、各自推进，互不影响（不再需要页面级/置顶的进度面板）。
 */
function renderBackfillProgressCell(
  status: string | null | undefined,
  progress: number | null | undefined,
  errorMessage?: string | null,
) {
  const key = status || "pending";
  const meta = BACKFILL_STATUS_META[key] ?? {
    label: key,
    tagColor: "default",
    progressStatus: "normal" as const,
  };
  const percent = Math.max(0, Math.min(100, Math.round(progress ?? 0)));
  const isActive = key === "pending" || key === "processing";
  const tip =
    key === "failed" ? errorMessage || "回填失败" : isActive ? `进度 ${percent}%` : undefined;
  // 2026-09-27 规范：回填过程中展示进度条；完成/失败后直接展示状态标签
  if (isActive) {
    return (
      <Tooltip title={tip}>
        <Progress
          percent={percent}
          status={meta.progressStatus}
          size="small"
          showInfo={false}
          style={{ width: 140 }}
        />
      </Tooltip>
    );
  }
  return (
    <Tooltip title={tip}>
      <Tag color={meta.tagColor} style={{ marginInlineEnd: 0 }}>
        {meta.label}
      </Tag>
    </Tooltip>
  );
}

/** 电流回填单任务响应（`{task: {...}, towers: [...]}`）→ 进度补丁。 */
function parseCurrentBackfillTask(
  payload: Record<string, unknown>,
): { status: string; progress: number; errorMessage: string | null } {
  const task = (payload.task ?? payload) as Record<string, unknown>;
  const progress = Number(task.progress);
  return {
    status: String(task.status ?? "pending"),
    progress: Number.isFinite(progress) ? progress : 0,
    errorMessage: (task.error_message as string | null) ?? null,
  };
}

/** 把进度补丁合并进「幅值模式」的一行；收尾字段一并就地写入，故完成后无需再刷列表。 */
function mergeAmplitudeBackfillRow(
  row: LightningAmplitudeBackfillLine,
  patch: BackfillTaskPatch,
): LightningAmplitudeBackfillLine {
  const task = (patch.raw.task ?? patch.raw) as Record<string, unknown>;
  const next: LightningAmplitudeBackfillLine = {
    ...row,
    status: patch.status,
    progress: patch.progress,
    error_message: patch.errorMessage,
    current_a: (task.current_a as number | null) ?? row.current_a,
    current_b: (task.current_b as number | null) ?? row.current_b,
    peak_max: (task.peak_max as number | null) ?? row.peak_max,
    peak_min: (task.peak_min as number | null) ?? row.peak_min,
    sampled_event_count:
      (task.sampled_event_count as number | undefined) ?? row.sampled_event_count,
  };
  const unchanged =
    next.status === row.status &&
    next.progress === row.progress &&
    next.error_message === row.error_message &&
    next.current_a === row.current_a &&
    next.current_b === row.current_b &&
    next.peak_max === row.peak_max &&
    next.peak_min === row.peak_min &&
    next.sampled_event_count === row.sampled_event_count;
  return unchanged ? row : next;
}

/** 同上，「全部回填记录」模式的一行。 */
function mergeCurrentBackfillTaskRow(
  row: LightningCurrentBackfillTaskSummary,
  patch: BackfillTaskPatch,
): LightningCurrentBackfillTaskSummary {
  const task = (patch.raw.task ?? patch.raw) as Record<string, unknown>;
  const next: LightningCurrentBackfillTaskSummary = {
    ...row,
    status: patch.status,
    progress: patch.progress,
    error_message: patch.errorMessage,
    current_a: (task.current_a as number | null) ?? row.current_a,
    current_b: (task.current_b as number | null) ?? row.current_b,
    peak_max: (task.peak_max as number | null) ?? row.peak_max,
    peak_min: (task.peak_min as number | null) ?? row.peak_min,
    updated_tower_count:
      (task.updated_tower_count as number | undefined) ?? row.updated_tower_count,
    sampled_event_count:
      (task.sampled_event_count as number | undefined) ?? row.sampled_event_count,
  };
  const unchanged =
    next.status === row.status &&
    next.progress === row.progress &&
    next.error_message === row.error_message &&
    next.current_a === row.current_a &&
    next.current_b === row.current_b &&
    next.peak_max === row.peak_max &&
    next.peak_min === row.peak_min &&
    next.updated_tower_count === row.updated_tower_count &&
    next.sampled_event_count === row.sampled_event_count;
  return unchanged ? row : next;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function renderAction(action: string) {
  if (action === "created") {
    return <Tag color="blue">{"新建"}</Tag>;
  }
  return <Tag color="orange">{"更新"}</Tag>;
}

function renderDelta(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  if (value > 0) {
    return <Typography.Text style={{ color: "#52c41a" }}>+{value.toFixed(3)}</Typography.Text>;
  }
  if (value < 0) {
    return <Typography.Text type="danger">{value.toFixed(3)}</Typography.Text>;
  }
  return <Typography.Text type="secondary">0.000</Typography.Text>;
}

export function LightningCurrentBackfillHistoryTable({
  amplitudeId,
}: LightningCurrentBackfillHistoryTableProps) {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message: messageApi, modal: modalApi } = App.useApp();
  const queryClient = useQueryClient();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [lineId, setLineId] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(BACKFILL_HISTORY_MIN_SCROLL_Y);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);
  // 任务执行日志弹窗（复用通用 TaskLogViewerDrawer，SSE 实时流）
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logTaskId, setLogTaskId] = useState<string | null>(null);
  const [logTitle, setLogTitle] = useState("任务执行日志");
  // 幅值模式：筛选关键词（draft 为输入框实时值，keyword 为已生效查询词，
  // 输入过程不触发请求，点「查询」/回车才把 draft 落进查询路径）
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  // 线路回填：本页内发起（外层列表只负责跳到本页）。
  // 进度不再由本组件另行跟踪 —— 列表本身即以回填任务为准，每行自带 status/progress，
  // 进度条直接渲染在对应记录行内，多条任务各占一行、互不干扰。
  const [backfillModalOpen, setBackfillModalOpen] = useState(false);
  const [backfillLineIds, setBackfillLineIds] = useState<string[]>([]);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  // 日志查看走 celery 权限（task-logs 接口），与任务监控页口径一致
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");
  const isAmplitudeMode = !!amplitudeId;

  const openLogViewer = useCallback((taskId: string | null | undefined, label: string) => {
    if (!taskId || !canReadLogs) {
      return;
    }
    setLogTaskId(taskId);
    setLogTitle(`回填任务日志 - ${label}`);
    setLogModalOpen(true);
  }, [canReadLogs]);

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    // 与线路管理-列表页同一套算法：用「可滚动面板(.admin-lightning-backfill-pane)的
    // padding-box 底边」推导表体高度。2026-09-12 对齐
    //   ① 不用 anchor 自身高度反推（会被表体 min-height 撑大 → 正反馈、越翻越高）
    //   ② 不用 window.innerHeight（漏掉面板底部内边距与页面底边距 → 溢出 12px、多出纵向滚动条）
    //   ③ 分页器上方 margin 16px + 4px 余量，保证容器内不产生滚动条
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-lightning-backfill-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? BACKFILL_HISTORY_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? BACKFILL_HISTORY_ESTIMATED_PAGINATION_HEIGHT;
    // 面板底边常低于视口底边（页面上方还有页签栏等），取较小值；并将面板自身已有的纵向溢出扣掉，
    // 避免表体算高撑出页面滚动条或面板内滚动条。2026-09-12
    const containerBottom = Math.min(containerRect.bottom, document.documentElement.clientHeight);
    const paneOverflow = Math.max(0, container.scrollHeight - container.clientHeight);
    const available = containerBottom - containerPadBottom - anchorTop - BACKFILL_HISTORY_BOTTOM_GAP - paneOverflow;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
    const clampedHeight = Math.max(BACKFILL_HISTORY_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const frameId = window.requestAnimationFrame(updateTableScrollHeight);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollHeight, isAmplitudeMode, pagination.current, pagination.pageSize, lineId, dateRange]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollHeight);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollHeight]);

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("page", String(pagination.current));
    params.set("page_size", String(pagination.pageSize));
    if (lineId) {
      params.set("line_id", lineId);
    }
    if (dateRange?.[0]) {
      params.set("start_date", dateRange[0].format("YYYY-MM-DD"));
    }
    if (dateRange?.[1]) {
      params.set("end_date", dateRange[1].format("YYYY-MM-DD"));
    }
    return `/api/v1/lightning-currents/backfill-tasks?${params.toString()}`;
  }, [dateRange, lineId, pagination.current, pagination.pageSize]);

  const listQuery = useQuery<LightningCurrentBackfillTaskListResponse>({
    queryKey: [listPath],
    enabled: !!user && canRead && !isAmplitudeMode,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskListResponse;
    },
  });

  const amplitudeLinesQuery = useQuery<LightningAmplitudeBackfillLineListResponse>({
    queryKey: ["lightning-currents", amplitudeId, "backfill-lines", keyword, pagination.current, pagination.pageSize],
    enabled: !!user && canRead && isAmplitudeMode,
    // 不用 refetchInterval 轮询整表：进度由 useBackfillTaskProgressSync 按任务就地更新，
    // 只动对应那一行，页面/表格不会有整体刷新感。
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("offset", String((pagination.current - 1) * pagination.pageSize));
      params.set("limit", String(pagination.pageSize));
      if (keyword.trim()) {
        params.set("keyword", keyword.trim());
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${amplitudeId}/backfill-lines?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeBackfillLineListResponse;
    },
  });

  // ---------------------------------------------------------------------------
  // 线路回填：回填动作放在本页（回填记录详情）内发起，外层列表/卡片只负责跳转到这里。
  // ---------------------------------------------------------------------------
  // 线路选择：复用现有线路列表接口
  const backfillCandidatesQuery = useQuery<LineListResponse>({
    queryKey: ["lines", "for-lightning-backfill"],
    enabled: !!user && canManage && backfillModalOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  const backfillMutation = useMutation({
    mutationFn: async (lineIds: string[]) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      type SubmitResult =
        | { lineId: string; ok: true; taskId: string }
        | { lineId: string; ok: false; message: string };
      const results = await Promise.all(
        lineIds.map(async (targetLineId): Promise<SubmitResult> => {
          const response = await fetchWithAuth("/api/v1/lightning-currents/prepare-current", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              line_id: targetLineId,
              // 带上来源幅值：后端据此把任务与这条幅值记录关联，
              // 使行进中的记录立刻出现在本列表（每行一条、各自带进度）
              ...(amplitudeId ? { amplitude_id: amplitudeId } : {}),
            }),
          });
          if (!response.ok) {
            return { lineId: targetLineId, ok: false, message: await readApiError(response) };
          }
          const payload = (await response.json()) as {
            task_id?: string;
            backfill_task_id?: string;
          };
          const taskId = payload.backfill_task_id || payload.task_id || "";
          if (!taskId) {
            return { lineId: targetLineId, ok: false, message: t("接口未返回回填任务 ID") };
          }
          return { lineId: targetLineId, ok: true, taskId };
        }),
      );
      return results;
    },
    onSuccess: (results) => {
      const accepted = results.filter((item) => item.ok);
      const failures = results.filter((item) => !item.ok);
      setBackfillModalOpen(false);
      setBackfillLineIds([]);
      if (failures.length > 0) {
        messageApi.error(
          `已提交 ${accepted.length} 条，失败 ${failures.length} 条：${failures
            .map((item) => item.message)
            .join("；")}`,
        );
      } else {
        messageApi.success(`回填任务已提交（${accepted.length} 条线路）`);
      }
      // 刷新列表：新提交的任务立即以「行进中 + 进度条」出现在对应记录行内
      void queryClient.invalidateQueries({ queryKey: ["lightning-currents"] });
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "回填失败");
    },
  });

  // 删除回填记录（2026-09-27 回填记录列表删除按钮）：仅删记录，不回滚已写入塔的幅值
  const deleteBackfillMutation = useMutation({
    mutationFn: async (taskId: string) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/backfill-tasks/${taskId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return true;
    },
    onSuccess: () => {
      messageApi.success("回填记录已删除");
      void queryClient.invalidateQueries({ queryKey: ["lightning-currents"] });
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "删除回填记录失败");
    },
  });

  // ---- 进度「按记录就地更新」：只轮询进行中的任务，合并进对应行，不重新请求列表 ----
  useBackfillTaskProgressSync<LightningAmplitudeBackfillLine>({
    items: isAmplitudeMode ? amplitudeLinesQuery.data?.items ?? [] : [],
    enabled: !!user && canRead && isAmplitudeMode,
    fetchWithAuth,
    getTaskId: (row) => row.task_id,
    getStatus: (row) => row.status,
    taskPath: (taskId) => `/api/v1/lightning-currents/backfill-tasks/${taskId}`,
    parseTask: parseCurrentBackfillTask,
    matchQueryKey: (key) => key[0] === "lightning-currents" && key[2] === "backfill-lines",
    mergeItem: mergeAmplitudeBackfillRow,
  });

  useBackfillTaskProgressSync<LightningCurrentBackfillTaskSummary>({
    items: isAmplitudeMode ? [] : listQuery.data?.items ?? [],
    enabled: !!user && canRead && !isAmplitudeMode,
    fetchWithAuth,
    getTaskId: (row) => row.id,
    getStatus: (row) => row.status,
    taskPath: (taskId) => `/api/v1/lightning-currents/backfill-tasks/${taskId}`,
    parseTask: parseCurrentBackfillTask,
    matchQueryKey: (key) =>
      typeof key[0] === "string" && (key[0] as string).includes("/backfill-tasks?"),
    mergeItem: mergeCurrentBackfillTaskRow,
  });

  const openBackfillModal = useCallback(() => {
    setBackfillLineIds([]);
    setBackfillModalOpen(true);
  }, []);

  const linesQuery = useQuery<LineListResponse>({
    queryKey: ["lines"],
    enabled: !!user && canRead && !isAmplitudeMode,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  const detailQuery = useQuery<LightningCurrentBackfillTaskDetail>({
    queryKey: ["lightning-currents", "backfill-tasks", detailTaskId],
    enabled: !!user && canRead && !!detailTaskId && detailOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/backfill-tasks/${detailTaskId}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskDetail;
    },
  });

  const openDetail = useCallback((record: LightningCurrentBackfillTaskSummary) => {
    setDetailTaskId(record.id);
    setDetailOpen(true);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailOpen(false);
    setDetailTaskId(null);
  }, []);

  const amplitudeColumns = useMemo<ColumnsType<LightningAmplitudeBackfillLine>>(
    () => [
      // 2026-09-27：去掉「线路编号」列，线路名称后增加「杆塔数量」列
      {
        title: t("线路名称"),
        dataIndex: "line_name",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string | null, row) =>
          value || row.line_code || "-",
      },
      {
        title: t("电压(kV)"),
        dataIndex: "voltage_kv",
        width: 110,
        render: (value: number | null) => (value == null ? "-" : value),
      },
      {
        title: t("杆塔数量"),
        key: "tower_count",
        width: 100,
        align: "center" as const,
        render: (_: unknown, row) => row.tower_count ?? 0,
      },
      {
        title: t("回填时间"),
        dataIndex: "prepared_at",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: t("回填状态"),
        key: "progress",
        width: 160,
        render: (_: unknown, row) =>
          renderBackfillProgressCell(row.status, row.progress, row.error_message),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 150,
        fixed: "right",
        align: "right" as const,
        render: (_: unknown, row) => {
          const moreMenuItems: MenuProps["items"] = [
            ...(canReadLogs && row.task_id
              ? [
                  {
                    key: "log",
                    label: t("日志"),
                    onClick: () => openLogViewer(row.task_id, row.line_name || row.line_code || "未知线路"),
                  },
                ]
              : []),
            ...(canManage && row.task_id
              ? [
                  {
                    key: "delete",
                    label: t("删除"),
                    danger: true,
                    disabled: deleteBackfillMutation.isPending,
                    onClick: () => {
                      modalApi.confirm({
                        title: t("删除回填记录"),
                        content: `确认删除线路「${row.line_name || row.line_code || "-"}」的回填记录吗？该操作仅删除记录，已写入塔的幅值数据不回滚。`,
                        okText: t("删除"),
                        cancelText: t("取消"),
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          if (row.task_id) {
                            await deleteBackfillMutation.mutateAsync(row.task_id);
                          }
                        },
                      });
                    },
                  },
                ]
              : []),
          ];
          return (
            <Space size={4}>
              <Button
                size="small"
                disabled={!row.task_id}
                onClick={() => {
                  if (!row.task_id) {
                    return;
                  }
                  setDetailTaskId(row.task_id);
                  setDetailOpen(true);
                }}
              >
                详情
              </Button>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, canReadLogs, openLogViewer, deleteBackfillMutation, modalApi],
  );

  const taskColumns = useMemo<ColumnsType<LightningCurrentBackfillTaskSummary>>(
    () => [
      {
        title: t("回填时间"),
        dataIndex: "prepared_at",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("线路名称"),
        dataIndex: "line_name",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string | null) => value || "-",
      },
      {
        title: t("回填状态"),
        key: "progress",
        width: 160,
        render: (_: unknown, row: LightningCurrentBackfillTaskSummary) =>
          renderBackfillProgressCell(row.status, row.progress, row.error_message),
      },
      {
        title: t("幅值a (kA)"),
        dataIndex: "current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("幅值b (kA)"),
        dataIndex: "current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("更新杆塔数"),
        dataIndex: "updated_tower_count",
        width: 110,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("操作人"),
        dataIndex: "prepared_by",
        width: 120,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      {
        title: t("操作"),
        key: "actions",
        width: 170,
        fixed: "right",
      align: "right" as const,
        render: (_: unknown, row) => (
          <Space size={4}>
            <Button size="small" onClick={() => openDetail(row)}>
              查看详情
            </Button>
            <Button
              size="small"
              disabled={!row.task_id || !canReadLogs}
              onClick={() => openLogViewer(row.task_id, row.line_name || row.line_id || "未知线路")}
            >
              日志
            </Button>
          </Space>
        ),
      },
    ],
    [canReadLogs, openDetail, openLogViewer],
  );

  const towerColumns = useMemo<ColumnsType<LightningCurrentBackfillTowerDetail>>(
    () => [
      {
        title: t("塔号"),
        dataIndex: "tower_no",
        width: 120,
        render: (value: string | null, row) => value || row.tower_id || "-",
      },
      {
        title: t("操作"),
        dataIndex: "action",
        width: 80,
        render: (value: string) => renderAction(value),
      },
      {
        title: t("回填前幅值a"),
        dataIndex: "previous_current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填后幅值a"),
        dataIndex: "current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("变化量a"),
        dataIndex: "delta_a",
        width: 100,
        render: (value: number | null) => renderDelta(value),
      },
      {
        title: t("回填前幅值b"),
        dataIndex: "previous_current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填后幅值b"),
        dataIndex: "current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("变化量b"),
        dataIndex: "delta_b",
        width: 100,
        render: (value: number | null) => renderDelta(value),
      },
    ],
    [],
  );

  // 抽屉数据源：任务模式用任务详情，幅值模式用「幅值+线路」明细
  const detailData = detailQuery.data;
  const detailLoading = detailQuery.isLoading;
  const detailFetching = detailQuery.isFetching;
  const task = detailData?.task;

  const handleSearch = useCallback(() => {
    // 输入框当前值落为「已生效」关键词后，与分页一起构成新 queryKey：
    // 输入过程不查询，只有点「查询」/回车才把输入值带进请求路径。
    setKeyword(keywordDraft.trim());
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, [keywordDraft]);

  const tableDataSource = isAmplitudeMode
    ? amplitudeLinesQuery.data?.items ?? []
    : listQuery.data?.items ?? [];
  const tableTotal = isAmplitudeMode ? amplitudeLinesQuery.data?.total ?? 0 : listQuery.data?.total ?? 0;
  // 用 isLoading（仅首次加载）而非 isFetching：后台按任务更新进度不进入 loading，避免表格闪烁
  const tableLoading = isAmplitudeMode ? amplitudeLinesQuery.isLoading : listQuery.isLoading;

  return (
    <div className="admin-lightning-backfill-pane">
      {isAmplitudeMode && (
        <div className="admin-filter-bar">
          <Form layout="inline" onFinish={handleSearch}>
            <Form.Item label={t("线路")} style={{ marginBottom: 0 }}>
              <Input
                allowClear
                placeholder={t("按线路编号/名称筛选")}
                style={{ width: 240 }}
                value={keywordDraft}
                onChange={(event) => setKeywordDraft(event.target.value)}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Space size={4}>
                <Button type="primary" htmlType="submit">
                  查询
                </Button>
                {canManage && (
                  <Button onClick={openBackfillModal} disabled={backfillMutation.isPending}>
                    回填
                  </Button>
                )}
              </Space>
            </Form.Item>
          </Form>
        </div>
      )}

      {!isAmplitudeMode && (
        <div className="admin-filter-bar">
          <Form layout="inline" onFinish={handleSearch}>
            <Form.Item label={t("线路")}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder={t("选择线路")}
                style={{ width: 240 }}
                value={lineId ?? undefined}
                onChange={(value: string | undefined) => {
                  setLineId(value ?? null);
                  handleSearch();
                }}
                options={(linesQuery.data?.items ?? []).map((line: LineSummary) => ({
                  label: `${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`,
                  value: line.id,
                }))}
              />
            </Form.Item>
            <Form.Item label={t("回填时间")}>
              <DatePicker.RangePicker
                allowClear
                value={dateRange ?? undefined}
                onChange={(dates) => {
                  setDateRange(dates && dates[0] && dates[1] ? [dates[0], dates[1]] : null);
                  handleSearch();
                }}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Space size={4}>
                <Button type="primary" htmlType="submit">
                  查询
                </Button>
                {canManage && (
                  <Button onClick={openBackfillModal} disabled={backfillMutation.isPending}>
                    回填
                  </Button>
                )}
              </Space>
            </Form.Item>
          </Form>
        </div>
      )}

      <div
        ref={tableScrollAnchorRef}
        className="admin-lightning-backfill-table-view flex-1 min-h-0"
        style={{ "--admin-lightning-backfill-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
      >
        <Table<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>
          rowKey={(row) => {
            // 幅值模式：一行 = 一次回填任务，故用 task_id（同一线路可有多条回填记录）
            const amplitudeRow = row as LightningAmplitudeBackfillLine;
            if (isAmplitudeMode && amplitudeRow.task_id) {
              return amplitudeRow.task_id;
            }
            return (row as LightningCurrentBackfillTaskSummary).id;
          }}
          columns={isAmplitudeMode ? (amplitudeColumns as ColumnsType<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>) : (taskColumns as ColumnsType<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>)}
          dataSource={tableDataSource}
          loading={tableLoading}
          tableLayout="fixed"
          scroll={{ x: 900, y: tableScrollY }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: tableTotal,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: () => `共 ${tableTotal} 条`,
            hideOnSinglePage: false,
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={isAmplitudeMode ? "该幅值尚未被任何线路回填使用。" : "未找到回填记录。"}
              />
            ),
          }}
        />
      </div>

      {/* 回填：在本页（回填记录详情）选择线路并提交；确认后进度在表格上方实时展示 */}
      <Modal
        title={t("回填线路")}
        open={backfillModalOpen}
        onCancel={() => {
          setBackfillModalOpen(false);
          setBackfillLineIds([]);
        }}
        onOk={() => {
          if (backfillLineIds.length > 0) {
            backfillMutation.mutate(backfillLineIds);
          }
        }}
        okText={t("确认回填")}
        okButtonProps={{
          disabled: backfillLineIds.length === 0,
          loading: backfillMutation.isPending,
        }}
        width={480}
        destroyOnHidden
      >
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          showSearch
          optionFilterProp="label"
          placeholder={t("搜索并选择线路（可多选）")}
          value={backfillLineIds}
          onChange={(value: string[]) => setBackfillLineIds(value)}
          loading={backfillCandidatesQuery.isFetching}
          options={(backfillCandidatesQuery.data?.items ?? []).map((line: LineSummary) => {
            // 无杆塔 = 没有可回填的数据，后端会直接 400；这里提前标黄并禁用，避免白跑一次
            const noTower = (line.tower_count ?? 0) === 0;
            return {
              label: (
                <Space size={6} style={{ width: "100%", justifyContent: "space-between" }}>
                  <span>{`${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`}</span>
                  {noTower ? (
                    <Tag color="warning" style={{ marginInlineEnd: 0 }}>
                      无杆塔数据
                    </Tag>
                  ) : (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {line.tower_count} 塔
                    </Typography.Text>
                  )}
                </Space>
              ),
              value: line.id,
              disabled: noTower,
            };
          })}
        />
      </Modal>

      <Drawer
        title={task?.line_name ? `回填明细 - ${task.line_name}` : "回填任务详情"}
        open={detailOpen}
        onClose={closeDetail}
        width={920}
        destroyOnHidden
      >
          {(detailLoading && !task) ? (
            <AdminPageLoading minHeightClassName="min-h-[240px]" />
          ) : task ? (
            <Space direction="vertical" size={16} className="w-full">
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label={t("线路")}>
                  {task.line_name || "-"}
                </Descriptions.Item>
                <Descriptions.Item label={t("回填时间")}>
                  {formatDateTime(task.prepared_at)}
                </Descriptions.Item>
                <Descriptions.Item label={t("操作人")}>
                  {task.prepared_by || "-"}
                </Descriptions.Item>
                <Descriptions.Item label={t("采样数")}>
                  {task.sampled_event_count}
                </Descriptions.Item>
                <Descriptions.Item label={t("幅值a (kA)")}>
                  {formatNumber(task.current_a, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={t("幅值b (kA)")}>
                  {formatNumber(task.current_b, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={t("峰值max (kA)")}>
                  {formatNumber(task.peak_max, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={t("峰值min (kA)")}>
                  {formatNumber(task.peak_min, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={t("更新杆塔数")}>
                  {task.updated_tower_count}
                </Descriptions.Item>
                <Descriptions.Item label={t("新建杆塔数")}>
                  {task.created_profile_count}
                </Descriptions.Item>
                {task.warnings.length > 0 && (
                  <Descriptions.Item label={t("警告")} span={2}>
                    <Space direction="vertical" size={2}>
                      {task.warnings.map((warn, index) => (
                        <Typography.Text key={index} type="warning">
                          {warn}
                        </Typography.Text>
                      ))}
                    </Space>
                  </Descriptions.Item>
                )}
              </Descriptions>

              <div>
                <Typography.Title level={5}>{t("杆塔回填明细")}</Typography.Title>
                <Table<LightningCurrentBackfillTowerDetail>
                  rowKey="tower_id"
                  columns={towerColumns}
                  dataSource={detailData?.towers ?? []}
                  loading={detailFetching}
                  size="small"
                  tableLayout="fixed"
                  scroll={{ x: 860 }}
                  pagination={false}
                  locale={{
                    emptyText: (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={t("暂无杆塔明细。")}
                      />
                    ),
                  }}
                />
              </div>
            </Space>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("加载失败或任务不存在")}
            />
          )}
      </Drawer>

      <TaskLogViewerDrawer
        taskId={logTaskId}
        title={logTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
        variant="modal"
      />
    </div>
  );
}
