/**
 * 基础数据包导出/导入两页共享的类型、常量、工具函数与详情抽屉。
 *
 * 后端端点（LP-14 既有，零接口改动）：
 *   POST /admin/platform-data/export        异步导出（类别 + 筛选）
 *   POST /admin/platform-data/import        异步导入（上传 ZIP 或复用历史导出 job_id）
 *   GET  /admin/platform-data/jobs          历史任务列表
 *   GET  /admin/platform-data/jobs/{id}     任务详情
 *   GET  /admin/platform-data/jobs/{id}/download  重新下载产物
 */
"use client";

import { Drawer, Space, type ReactNode } from "antd";

import { useI18n } from "@/lib/i18n";
import type { DimensionTypeTreeItem } from "@/types/auth";
import type { DimensionItemListResponse } from "@/types/dimension";

export const TABLE_MIN_SCROLL_Y = 180;
export const POLL_INTERVAL_MS = 3000;

export type JobKind = "export" | "import";
// 与后端 PlatformDataJob.status 对齐：终态成功值为 success（非 completed）
export type JobStatus = "pending" | "running" | "success" | "failed";

export type JobSummary = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  categories?: string[] | null;
  schema_version?: string | null;
  artifact_filename?: string | null;
  source_site?: string | null;
  create_date?: string | null;
  finish_date?: string | null;
  result_summary?: Record<string, unknown> | null;
  error_message?: string | null;
};

export type JobDetail = JobSummary & {
  request_payload?: Record<string, unknown>;
  manifest?: Record<string, unknown> | null;
  artifact_storage_path?: string | null;
  artifact_file_id?: number | null;
};

export const CATEGORY_OPTIONS = [
  { label: "维度", value: "dimensions" },
  { label: "系统参数", value: "system_params" },
  { label: "ATP 模型", value: "atp_models" },
] as const;

export const CATEGORY_LABEL: Record<string, string> = {
  dimensions: "维度",
  system_params: "系统参数",
  atp_models: "ATP 模型",
};

// 兜底：未知状态一律按 pending 展示，避免后端新增状态时整表渲染崩溃
export const STATUS_FALLBACK: { color: string; label: string } = { color: "default", label: "等待中" };
export const STATUS_META: Record<JobStatus, { color: string; label: string }> = {
  pending: STATUS_FALLBACK,
  running: { color: "processing", label: "执行中" },
  success: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

// ATP 模型导出筛选：前端维度字段 → 维度管理类型 code
// 注意场景的类型 code 是 scenario（不是 scene_type），与 ATP 模型页保持一致
export const EXPORT_DIMENSION_TYPE_CODES = {
  voltage_level: "voltage_level",
  tower_type: "tower_type",
  scene: "scenario",
} as const;
export type ExportDimensionField = keyof typeof EXPORT_DIMENSION_TYPE_CODES;
export type DimensionOption = { label: string; value: string };
export type ExportDimensionOptions = Record<ExportDimensionField, DimensionOption[]>;

export const EMPTY_EXPORT_DIMENSION_OPTIONS: ExportDimensionOptions = {
  voltage_level: [],
  tower_type: [],
  scene: [],
};

export function flattenDimensionTypes(types: DimensionTypeTreeItem[]): DimensionTypeTreeItem[] {
  return types.flatMap((type) => [type, ...flattenDimensionTypes(type.children ?? [])]);
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function summarizeResult(summary?: Record<string, unknown> | null): string {
  if (!summary) return "—";
  const parts: string[] = [];
  for (const [key, value] of Object.entries(summary)) {
    if (value && typeof value === "object") {
      const inner = Object.entries(value as Record<string, unknown>)
        .map(([k, v]) => `${k}:${typeof v === "number" ? v : String(v)}`)
        .join(" ");
      parts.push(`${key}（${inner}）`);
    } else {
      parts.push(`${key}:${String(value)}`);
    }
  }
  return parts.length ? parts.join("，") : "—";
}

export function PlatformDataDetailDrawer({
  open,
  loading,
  data,
  onClose,
}: {
  open: boolean;
  loading: boolean;
  data: JobDetail | null;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <DrawerWrap open={open} loading={loading} title={t("任务详情")} onClose={onClose}>
      {data ? (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <DetailBlock title={t("请求参数 (request_payload)")} value={data.request_payload} />
          <DetailBlock title={t("清单 (manifest)")} value={data.manifest} />
          <DetailBlock title={t("结果摘要 (result_summary)")} value={data.result_summary} />
          {data.error_message ? (
            <DetailBlock title={t("错误信息 (error_message)")} value={data.error_message} error />
          ) : null}
        </Space>
      ) : null}
    </DrawerWrap>
  );
}

function DetailBlock({
  title,
  value,
  error,
}: {
  title: string;
  value: unknown;
  error?: boolean;
}) {
  const text =
    value == null
      ? "—"
      : typeof value === "string"
        ? value
        : JSON.stringify(value, null, 2);
  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{title}</div>
      <pre
        style={{
          maxHeight: 280,
          overflow: "auto",
          padding: 12,
          borderRadius: 6,
          background: "var(--gray-a2)",
          color: error ? "#cf1322" : "var(--gray-12)",
          fontSize: 12,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          margin: 0,
        }}
      >
        {text}
      </pre>
    </div>
  );
}

// 轻量抽屉封装
function DrawerWrap({
  open,
  loading,
  title,
  onClose,
  children,
}: {
  open: boolean;
  loading: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Drawer title={title} width={520} open={open} onClose={onClose} loading={loading}>
      {children}
    </Drawer>
  );
}
