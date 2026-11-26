/**
 * 基础数据包导出/导入两页共享的类型、常量、工具函数与任务详情面板。
 *
 * 后端端点（LP-14 既有，零接口改动）：
 *   POST /admin/platform-data/export        异步导出（类别 + 筛选）
 *   POST /admin/platform-data/import        异步导入（上传 ZIP 或复用历史导出 job_id）
 *   GET  /admin/platform-data/jobs          历史任务列表
 *   GET  /admin/platform-data/jobs/{id}     任务详情
 *   GET  /admin/platform-data/jobs/{id}/download  重新下载产物
 */
"use client";

import { useEffect, useState } from "react";
import { Alert, Descriptions, Space, Spin, Tag } from "antd";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { DimensionTypeTreeItem } from "@/types/auth";

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
  /** 导出包大小（字节）。新后端显式返回；旧数据缺失时用 jobFileSize 兜底读 result_summary。 */
  file_size_bytes?: number | null;
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

/** 字节数转可读大小：12345 → 12.1 KB，24600000 → 23.5 MB；null/0/非法值显示 —。 */
export function formatBytes(bytes?: number | null): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  // 字节整数展示，其余保留 1 位小数（整数值去掉 .0）
  const text = value.toFixed(unitIndex === 0 ? 0 : 1).replace(/\.0$/, "");
  return `${text} ${units[unitIndex]}`;
}

/** 包大小（字节）：优先使用后端显式字段，旧数据 / 旧后端回落到 result_summary.file_size。 */
export function jobFileSize(job: Pick<JobSummary, "file_size_bytes" | "result_summary">): number | null {
  if (typeof job.file_size_bytes === "number" && job.file_size_bytes > 0) return job.file_size_bytes;
  const legacy = job.result_summary?.file_size;
  return typeof legacy === "number" && legacy > 0 ? legacy : null;
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

/**
 * 任务详情面板（Tab 内容）：与线路管理的详情 Tab 一致，打开即按需拉取任务详情。
 * 抽屉形态已由列表 Tab + 可关闭详情 Tab 取代（LP-130）。
 */
export function PlatformDataJobDetailPane({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const { fetchWithAuth } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<JobDetail | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setData(null);
    void (async () => {
      try {
        const response = await fetchWithAuth(`/api/v1/admin/platform-data/jobs/${jobId}`);
        if (!response.ok) throw new Error(await readApiError(response));
        const detail = (await response.json()) as JobDetail;
        if (active) setData(detail);
      } catch (caught) {
        if (active) setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [fetchWithAuth, jobId]);

  if (loading) {
    return (
      <div className="admin-platform-data-detail-pane admin-platform-data-detail-loading">
        <Spin />
      </div>
    );
  }
  if (error) {
    return (
      <div className="admin-platform-data-detail-pane">
        <Alert type="error" showIcon message={t("加载失败")} description={error} />
      </div>
    );
  }
  if (!data) return null;

  const statusMeta = STATUS_META[data.status] ?? STATUS_FALLBACK;
  return (
    <div className="admin-platform-data-detail-pane">
      <Descriptions
        size="small"
        column={2}
        bordered
        items={[
          { key: "id", label: t("任务 ID"), children: <span style={{ wordBreak: "break-all" }}>{data.id}</span> },
          { key: "kind", label: t("类型"), children: data.kind === "export" ? t("导出") : t("导入") },
          {
            key: "status",
            label: t("状态"),
            children: <Tag color={statusMeta.color}>{t(statusMeta.label)}</Tag>,
          },
          { key: "size", label: t("包大小"), children: formatBytes(jobFileSize(data)) },
          {
            key: "categories",
            label: t("类别"),
            children:
              data.categories && data.categories.length
                ? data.categories.map((c) => t(CATEGORY_LABEL[c] ?? c)).join(" / ")
                : "—",
          },
          { key: "artifact", label: t("产物文件"), children: data.artifact_filename ?? "—" },
          { key: "site", label: t("来源站点"), children: data.source_site ?? "—" },
          { key: "schema", label: t("包版本"), children: data.schema_version ?? "—" },
          { key: "created", label: t("创建时间"), children: formatDateTime(data.create_date) },
          { key: "finished", label: t("完成时间"), children: formatDateTime(data.finish_date) },
        ]}
      />
      {data.error_message ? (
        <Alert type="error" showIcon message={t("执行失败")} description={data.error_message} />
      ) : null}
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <DetailBlock title={t("请求参数 (request_payload)")} value={data.request_payload} />
        <DetailBlock title={t("清单 (manifest)")} value={data.manifest} />
        <DetailBlock title={t("结果摘要 (result_summary)")} value={data.result_summary} />
      </Space>
    </div>
  );
}

function DetailBlock({
  title,
  value,
}: {
  title: string;
  value: unknown;
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
          color: "var(--gray-12)",
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
