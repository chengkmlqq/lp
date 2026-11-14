"use client";

/**
 * 平台基础数据包工具页（LP-17）。
 *
 * 消费 LP-14 既有的后端端点（纯前端，零接口改动）：
 *   POST /admin/platform-data/export        异步导出（类别 + 筛选）
 *   POST /admin/platform-data/import        异步导入（上传 ZIP 或复用历史导出 job_id）
 *   GET  /admin/platform-data/jobs          历史任务列表
 *   GET  /admin/platform-data/jobs/{id}    任务详情
 *   GET  /admin/platform-data/jobs/{id}/download  重新下载产物
 *
 * 页面结构：导出区 → 导入区 → 任务列表区（含状态轮询 + 操作列）。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  type UploadFile,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DownloadOutlined, InboxOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { modoTablePagination } from "@/components/biz/modo-pagination";
import { readApiError } from "@/lib/api";
import { measureTableScrollY } from "@/lib/table-scroll-y";

const { Text } = Typography;

const TABLE_MIN_SCROLL_Y = 180;
const POLL_INTERVAL_MS = 3000;

type JobKind = "export" | "import";
type JobStatus = "pending" | "running" | "completed" | "failed";

type JobSummary = {
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

type JobDetail = JobSummary & {
  request_payload?: Record<string, unknown>;
  manifest?: Record<string, unknown> | null;
  artifact_storage_path?: string | null;
  artifact_file_id?: number | null;
};

const CATEGORY_OPTIONS = [
  { label: "维度", value: "dimensions" },
  { label: "系统参数", value: "system_params" },
  { label: "ATP 模型", value: "atp_models" },
] as const;

const CATEGORY_LABEL: Record<string, string> = {
  dimensions: "维度",
  system_params: "系统参数",
  atp_models: "ATP 模型",
};

const STATUS_META: Record<JobStatus, { color: string; label: string }> = {
  pending: { color: "default", label: "等待中" },
  running: { color: "processing", label: "执行中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function summarizeResult(summary?: Record<string, unknown> | null): string {
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

export default function PlatformDataPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message } = App.useApp();

  const canManage = hasPermission("platform_data.manage");

  // ── 任务列表 ──────────────────────────────────────────────────────
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<JobKind | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<JobStatus | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // ── 导出区 ────────────────────────────────────────────────────────
  const [exportCategories, setExportCategories] = useState<string[]>([]);
  const [filterVoltage, setFilterVoltage] = useState("");
  const [filterTower, setFilterTower] = useState("");
  const [filterScene, setFilterScene] = useState("");
  const [exportLoading, setExportLoading] = useState(false);

  // ── 导入区 ────────────────────────────────────────────────────────
  const [importFile, setImportFile] = useState<File | null>(null);
  const [sourceJobId, setSourceJobId] = useState<string | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [reuseJobs, setReuseJobs] = useState<JobSummary[]>([]);
  const importSelectRef = useRef<{ focus: () => void } | null>(null);

  // ── 详情抽屉 ──────────────────────────────────────────────────────
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailData, setDetailData] = useState<JobDetail | null>(null);

  const hasActive = useMemo(
    () => jobs.some((j) => j.status === "pending" || j.status === "running"),
    [jobs],
  );

  const exportBusy = useMemo(
    () => exportLoading || jobs.some((j) => j.kind === "export" && (j.status === "pending" || j.status === "running")),
    [exportLoading, jobs],
  );
  const importBusy = useMemo(
    () => importLoading || jobs.some((j) => j.kind === "import" && (j.status === "pending" || j.status === "running")),
    [importLoading, jobs],
  );

  // 表格高度自适应（与全站管理页一致：锚点测量）
  useEffect(() => {
    if (typeof window === "undefined") return;
    const measure = () => {
      const anchor = tableScrollAnchorRef.current;
      if (!anchor) return;
      const next = measureTableScrollY(anchor);
      if (next != null) setTableScrollY(Math.max(TABLE_MIN_SCROLL_Y, next));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [jobs.length]);

  const loadJobs = useCallback(async () => {
    setJobsLoading(true);
    setJobsError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", "100");
      params.set("offset", "0");
      if (kindFilter) params.set("kind", kindFilter);
      if (statusFilter) params.set("status", statusFilter);
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/jobs?${params.toString()}`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data = (await response.json()) as { items: JobSummary[]; total: number };
      setJobs(data.items ?? []);
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : String(error));
      setJobs([]);
    } finally {
      setJobsLoading(false);
    }
  }, [fetchWithAuth, kindFilter, statusFilter]);

  // 复用来源：已完成的历史导出任务
  const loadReuseJobs = useCallback(async () => {
    try {
      const response = await fetchWithAuth(
        `/api/v1/admin/platform-data/jobs?kind=export&status=completed&limit=100&offset=0`,
      );
      if (!response.ok) return;
      const data = (await response.json()) as { items: JobSummary[] };
      setReuseJobs(data.items ?? []);
    } catch {
      /* 复用来源加载失败不应阻断主流程 */
    }
  }, [fetchWithAuth]);

  // 初始加载
  useEffect(() => {
    if (!canManage) return;
    void loadJobs();
    void loadReuseJobs();
  }, [canManage, loadJobs, loadReuseJobs]);

  // 状态轮询：存在非终态任务时每 3s 拉取一次，全部终态或卸载时清除
  const pollingRef = useRef<number | null>(null);
  useEffect(() => {
    if (hasActive) {
      if (pollingRef.current == null) {
        pollingRef.current = window.setInterval(() => {
          void loadJobs();
        }, POLL_INTERVAL_MS);
      }
    } else if (pollingRef.current != null) {
      window.clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current != null) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [hasActive, loadJobs]);

  const startPollingSoon = useCallback(() => {
    // 触发后立即刷新一次，并让 hasActive 评估接管轮询
    void loadJobs();
  }, [loadJobs]);

  // ── 导出 ──────────────────────────────────────────────────────────
  const handleExport = async () => {
    if (exportCategories.length === 0) {
      message.warning(t("请至少勾选一个导出类别"));
      return;
    }
    const filters: Record<string, string> = {};
    if (exportCategories.includes("atp_models")) {
      if (filterVoltage.trim()) filters.voltage_level = filterVoltage.trim();
      if (filterTower.trim()) filters.tower_type = filterTower.trim();
      if (filterScene.trim()) filters.scene = filterScene.trim();
    }
    setExportLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categories: exportCategories, filters }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const job = (await response.json()) as JobSummary;
      message.success(t("已创建导出任务，正在打包…"));
      void startPollingSoon();
      setPagination((prev) => ({ ...prev, current: 1 }));
      void job;
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setExportLoading(false);
    }
  };

  // ── 导入 ──────────────────────────────────────────────────────────
  const handleImport = async () => {
    if (!importFile && !sourceJobId) {
      message.warning(t("请上传数据包 ZIP，或选择复用某次历史导出"));
      return;
    }
    setImportLoading(true);
    try {
      const formData = new FormData();
      if (importFile) formData.append("file", importFile);
      if (sourceJobId) formData.append("source_job_id", sourceJobId);
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const job = (await response.json()) as JobSummary;
      message.success(t("已创建导入任务，正在写入…"));
      setImportFile(null);
      setSourceJobId(null);
      void startPollingSoon();
      setPagination((prev) => ({ ...prev, current: 1 }));
      void job;
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setImportLoading(false);
    }
  };

  // ── 下载产物 ──────────────────────────────────────────────────────
  const handleDownload = async (job: JobSummary) => {
    if (!job.artifact_filename) return;
    try {
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/jobs/${job.id}/download`);
      if (!response.ok) throw new Error(await readApiError(response));
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = job.artifact_filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      message.success(`${t("下载已开始：")}${job.artifact_filename}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    }
  };

  // ── 复用为导入 ────────────────────────────────────────────────────
  const handleReuse = (job: JobSummary) => {
    setSourceJobId(job.id);
    importSelectRef.current?.focus();
    message.info(t("已填入复用来源，点击「导入数据包」即可"));
  };

  // ── 查看详情 ──────────────────────────────────────────────────────
  const handleOpenDetail = async (job: JobSummary) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/jobs/${job.id}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setDetailData((await response.json()) as JobDetail);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<JobSummary> = [
    {
      title: t("类型"),
      dataIndex: "kind",
      width: 90,
      render: (kind: JobKind) => (kind === "export" ? t("导出") : t("导入")),
    },
    {
      title: t("状态"),
      dataIndex: "status",
      width: 150,
      render: (status: JobStatus, record) => (
        <div>
          <Tag color={STATUS_META[status].color}>{STATUS_META[status].label}</Tag>
          {status === "failed" && record.error_message ? (
            <div style={{ color: "#cf1322", fontSize: 12, marginTop: 2, maxWidth: 280, wordBreak: "break-all" }}>
              {record.error_message}
            </div>
          ) : null}
        </div>
      ),
    },
    {
      title: t("类别"),
      dataIndex: "categories",
      width: 180,
      render: (categories?: string[] | null) =>
        categories && categories.length
          ? categories.map((c) => CATEGORY_LABEL[c] ?? c).join(" / ")
          : "—",
    },
    {
      title: t("产物文件"),
      dataIndex: "artifact_filename",
      width: 200,
      render: (filename?: string | null) => filename ?? "—",
    },
    {
      title: t("来源站点"),
      dataIndex: "source_site",
      width: 120,
      render: (site?: string | null) => site ?? "—",
    },
    {
      title: t("结果摘要"),
      dataIndex: "result_summary",
      width: 260,
      render: (summary: Record<string, unknown> | null | undefined, record) =>
        record.status === "failed" ? (
          <Text type="danger">{record.error_message ?? t("失败")}</Text>
        ) : (
          <span style={{ color: "var(--gray-11)", fontSize: 12 }}>{summarizeResult(summary)}</span>
        ),
    },
    {
      title: t("创建时间"),
      dataIndex: "create_date",
      width: 160,
      render: (v?: string | null) => formatDateTime(v),
    },
    {
      title: t("完成时间"),
      dataIndex: "finish_date",
      width: 160,
      render: (v?: string | null) => formatDateTime(v),
    },
    {
      title: t("操作"),
      key: "action",
      fixed: "right",
      width: 200,
      render: (_value, record) => (
        <ModoActionGroup
          actions={[
            {
              key: "detail",
              label: t("详情"),
              onClick: () => void handleOpenDetail(record),
            },
            {
              key: "download",
              label: t("下载产物"),
              disabled: !record.artifact_filename,
              title: record.artifact_filename ? undefined : t("暂无产物可下载"),
              onClick: () => void handleDownload(record),
            },
            {
              key: "reuse",
              label: t("复用为导入"),
              visible: record.kind === "export",
              onClick: () => handleReuse(record),
            },
          ]}
        />
      ),
    },
  ];

  if (!initializing && !canManage) {
    return (
      <div className="modo-page-card">
        <Alert
          type="warning"
          showIcon
          message={t("无访问权限")}
          description={
            <Text type="secondary">
              {!user
                ? t("请先登录后再访问基础数据包工具。")
                : t("当前账号无 platform_data.manage 权限，菜单与接口均不可用。")}
            </Text>
          }
        />
      </div>
    );
  }

  return (
    <div className="modo-page-card">
      {/* 导出区 */}
      <Card size="small" title={t("导出数据包")} style={{ marginBottom: 16 }}>
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label={t("类别")} style={{ marginBottom: 0 }}>
              <Checkbox.Group
                options={CATEGORY_OPTIONS as unknown as { label: string; value: string }[]}
                value={exportCategories}
                onChange={(values) => setExportCategories(values as string[])}
              />
            </Form.Item>
            {exportCategories.includes("atp_models") ? (
              <>
                <Form.Item label={t("电压")} style={{ marginBottom: 0 }}>
                  <Input
                    allowClear
                    style={{ width: 120 }}
                    placeholder={t("如 500kV")}
                    value={filterVoltage}
                    onChange={(e) => setFilterVoltage(e.target.value)}
                  />
                </Form.Item>
                <Form.Item label={t("塔型")} style={{ marginBottom: 0 }}>
                  <Input
                    allowClear
                    style={{ width: 140 }}
                    placeholder={t("如 酒杯")}
                    value={filterTower}
                    onChange={(e) => setFilterTower(e.target.value)}
                  />
                </Form.Item>
                <Form.Item label={t("场景")} style={{ marginBottom: 0 }}>
                  <Input
                    allowClear
                    style={{ width: 140 }}
                    placeholder={t("如 平原")}
                    value={filterScene}
                    onChange={(e) => setFilterScene(e.target.value)}
                  />
                </Form.Item>
              </>
            ) : null}
            <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                loading={exportLoading}
                disabled={exportBusy}
                onClick={() => void handleExport()}
              >
                {t("导出数据包")}
              </Button>
            </Form.Item>
          </Form>
        </div>
      </Card>

      {/* 导入区 */}
      <Card size="small" title={t("导入数据包")} style={{ marginBottom: 16 }}>
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label={t("上传包")} style={{ marginBottom: 0 }}>
              <Upload
                maxCount={1}
                beforeUpload={(file) => {
                  setImportFile(file as unknown as File);
                  return false;
                }}
                onRemove={() => setImportFile(null)}
                fileList={
                  importFile
                    ? ([{ uid: "-1", name: importFile.name, status: "done" }] as UploadFile[])
                    : []
                }
              >
                <Button icon={<UploadOutlined />}>{t("选择 ZIP")}</Button>
              </Upload>
            </Form.Item>
            <Form.Item label={t("复用历史导出")} style={{ marginBottom: 0 }}>
              <Select
                ref={importSelectRef as never}
                allowClear
                style={{ width: 260 }}
                placeholder={t("或选择某次已完成导出任务")}
                value={sourceJobId}
                onChange={(value) => setSourceJobId(value ?? null)}
                options={reuseJobs.map((j) => ({
                  value: j.id,
                  label: `${j.id.slice(0, 8)} · ${formatDateTime(j.finish_date)}`,
                }))}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
              <Button
                type="primary"
                icon={<InboxOutlined />}
                loading={importLoading}
                disabled={importBusy}
                onClick={() => void handleImport()}
              >
                {t("导入数据包")}
              </Button>
            </Form.Item>
          </Form>
        </div>
      </Card>

      {/* 任务列表区 */}
      <Card
        size="small"
        title={t("任务列表")}
        extra={
          <Space>
            <Select
              allowClear
              style={{ width: 120 }}
              placeholder={t("全部类型")}
              value={kindFilter}
              onChange={(value) => {
                setKindFilter(value ?? undefined);
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
              options={[
                { value: "export", label: t("导出") },
                { value: "import", label: t("导入") },
              ]}
            />
            <Select
              allowClear
              style={{ width: 120 }}
              placeholder={t("全部状态")}
              value={statusFilter}
              onChange={(value) => {
                setStatusFilter(value ?? undefined);
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
              options={(Object.keys(STATUS_META) as JobStatus[]).map((key) => ({
                value: key,
                label: STATUS_META[key].label,
              }))}
            />
            <Button icon={<ReloadOutlined />} onClick={() => void loadJobs()}>
              {t("刷新")}
            </Button>
          </Space>
        }
      >
        {jobsError ? (
          <Alert type="error" showIcon style={{ marginBottom: 12 }} message={t("加载失败")} description={jobsError} />
        ) : null}
        <div
          ref={tableScrollAnchorRef}
          className="admin-platform-data-table-anchor"
          style={{ "--admin-platform-data-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
        >
          <Table<JobSummary>
            rowKey="id"
            size="small"
            loading={jobsLoading}
            columns={columns}
            dataSource={jobs}
            scroll={{ x: 1200, y: tableScrollY }}
            pagination={modoTablePagination({
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: jobs.length,
              onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
            })}
            locale={{
              emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无任务记录")} />,
            }}
          />
        </div>
      </Card>

      {/* 详情抽屉 */}
      <PlatformDataDetailDrawer
        open={detailOpen}
        loading={detailLoading}
        data={detailData}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  );
}

function PlatformDataDetailDrawer({
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
