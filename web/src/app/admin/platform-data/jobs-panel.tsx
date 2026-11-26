"use client";

/**
 * 基础数据包任务列表面板（导出页与导入页共用）。
 *
 * 布局对齐线路管理页：筛选栏（关键字 / 类型 / 状态 / 查询）+ 卡片-列表视图切换 +
 * 共用分页状态。任务详情由外层 ModoTabs 以可关闭 Tab 承载，本组件只负责列表与
 * 下载产物。
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  ClockCircleOutlined,
  ExportOutlined,
  FileZipOutlined,
  GlobalOutlined,
  ImportOutlined,
  SearchOutlined,
  TagsOutlined,
} from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { readApiError } from "@/lib/api";
import {
  CATEGORY_LABEL,
  POLL_INTERVAL_MS,
  STATUS_FALLBACK,
  STATUS_META,
  TABLE_MIN_SCROLL_Y,
  formatBytes,
  formatDateTime,
  jobFileSize,
  type JobKind,
  type JobStatus,
  type JobSummary,
} from "./shared";

const { Text } = Typography;

export type PlatformDataJobsPanelHandle = {
  /** 重新拉取列表；resetPage=true 时回到第 1 页（新建任务成功后使用）。 */
  reload: (options?: { resetPage?: boolean }) => void;
};

type PlatformDataJobsPanelProps = {
  /** 固定任务类型：导入页只看导入任务；导出页留空展示全部并开放类型筛选。 */
  fixedKind?: JobKind;
  defaultView?: "card" | "list";
  onOpenDetail: (job: JobSummary) => void;
};

export const PlatformDataJobsPanel = forwardRef<PlatformDataJobsPanelHandle, PlatformDataJobsPanelProps>(
  function PlatformDataJobsPanel({ fixedKind, defaultView = "card", onOpenDetail }, ref) {
    const { t } = useI18n();
    const { fetchWithAuth } = useAuth();
    const { message } = App.useApp();

    const [jobs, setJobs] = useState<JobSummary[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [keywordInput, setKeywordInput] = useState("");
    const [keyword, setKeyword] = useState("");
    const [kindFilter, setKindFilter] = useState<JobKind | undefined>(undefined);
    const [statusFilter, setStatusFilter] = useState<JobStatus | undefined>(undefined);
    const [viewMode, setViewMode] = useState<"card" | "list">(defaultView);
    const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
    const [reloadNonce, setReloadNonce] = useState(0);
    const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
    const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

    const loadJobs = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        params.set("limit", "200");
        params.set("offset", "0");
        const effectiveKind = fixedKind ?? kindFilter;
        if (effectiveKind) params.set("kind", effectiveKind);
        if (statusFilter) params.set("status", statusFilter);
        const response = await fetchWithAuth(`/api/v1/admin/platform-data/jobs?${params.toString()}`);
        if (!response.ok) throw new Error(await readApiError(response));
        const data = (await response.json()) as { items: JobSummary[]; total: number };
        setJobs(data.items ?? []);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        setJobs([]);
      } finally {
        setLoading(false);
      }
    }, [fetchWithAuth, fixedKind, kindFilter, statusFilter]);

    useImperativeHandle(
      ref,
      () => ({
        reload: (options) => {
          if (options?.resetPage) setPagination((prev) => ({ ...prev, current: 1 }));
          setReloadNonce((nonce) => nonce + 1);
        },
      }),
      [],
    );

    useEffect(() => {
      void loadJobs();
    }, [loadJobs, reloadNonce]);

    // 状态轮询：存在非终态任务时每 3s 刷新，全部终态后停止
    const hasActive = useMemo(
      () => jobs.some((job) => job.status === "pending" || job.status === "running"),
      [jobs],
    );
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

    const filteredJobs = useMemo(() => {
      const needle = keyword.trim().toLowerCase();
      if (!needle) return jobs;
      return jobs.filter((job) => {
        const haystack = [
          job.id,
          job.artifact_filename ?? "",
          job.source_site ?? "",
          ...(job.categories ?? []).map((code) => `${code} ${t(CATEGORY_LABEL[code] ?? code)}`),
        ]
          .join(" ")
          .toLowerCase();
        return haystack.includes(needle);
      });
    }, [jobs, keyword, t]);

    const total = filteredJobs.length;
    const pageItems = useMemo(() => {
      const start = (pagination.current - 1) * pagination.pageSize;
      return filteredJobs.slice(start, start + pagination.pageSize);
    }, [filteredJobs, pagination]);

    // 表格高度自适应：口径与线路管理页一致 —— 用「列表面板 padding-box 底边」推导表体高度，
    // 不用锚点自身高度反推（会被表体 min-height 撑大 → 正反馈），也不漏分页器高度。
    const updateTableScrollHeight = useCallback(() => {
      if (typeof window === "undefined") return TABLE_MIN_SCROLL_Y;
      const anchor = tableScrollAnchorRef.current;
      if (!anchor) return TABLE_MIN_SCROLL_Y;
      const anchorTop = anchor.getBoundingClientRect().top;
      const pane = anchor.closest<HTMLElement>(".admin-platform-data-list-pane");
      const container = pane ?? document.documentElement;
      const containerRect = container.getBoundingClientRect();
      const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
      const header = anchor.querySelector<HTMLElement>(".ant-table-header");
      const pagination = pane?.querySelector<HTMLElement>(".admin-list-view-pagination");
      const headerHeight = header?.getBoundingClientRect().height ?? 56;
      const paginationHeight = pagination?.getBoundingClientRect().height ?? 56;
      const available = containerRect.bottom - containerPadBottom - anchorTop;
      return Math.max(TABLE_MIN_SCROLL_Y, Math.floor(available - headerHeight - paginationHeight - 20));
    }, []);

    useEffect(() => {
      if (typeof window === "undefined") return;
      const recompute = () => {
        window.requestAnimationFrame(() => setTableScrollY(updateTableScrollHeight()));
      };
      recompute();
      window.addEventListener("resize", recompute);
      return () => window.removeEventListener("resize", recompute);
    }, [updateTableScrollHeight, pageItems.length, viewMode]);

    const handleSearch = () => {
      setKeyword(keywordInput);
      setPagination((prev) => ({ ...prev, current: 1 }));
      // 条件未变时也强制重新拉取（与「查询」按钮语义一致）
      setReloadNonce((nonce) => nonce + 1);
    };

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
      } catch (caught) {
        message.error(caught instanceof Error ? caught.message : String(caught));
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
        render: (status: JobStatus, record) => {
          const meta = STATUS_META[status] ?? STATUS_FALLBACK;
          return (
            <div>
              <Tag color={meta.color}>{t(meta.label)}</Tag>
              {status === "failed" && record.error_message ? (
                <div style={{ color: "#cf1322", fontSize: 12, marginTop: 2, maxWidth: 280, wordBreak: "break-all" }}>
                  {record.error_message}
                </div>
              ) : null}
            </div>
          );
        },
      },
      {
        title: t("类别"),
        dataIndex: "categories",
        width: 180,
        render: (categories?: string[] | null) =>
          categories && categories.length
            ? categories.map((code) => t(CATEGORY_LABEL[code] ?? code)).join(" / ")
            : "—",
      },
      {
        title: t("产物文件"),
        dataIndex: "artifact_filename",
        width: 200,
        render: (filename?: string | null) => filename ?? "—",
      },
      {
        title: t("包大小"),
        key: "file_size",
        width: 110,
        render: (_value, record) => formatBytes(jobFileSize(record)),
      },
      {
        title: t("来源站点"),
        dataIndex: "source_site",
        width: 120,
        render: (site?: string | null) => site ?? "—",
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        width: 160,
        render: (value?: string | null) => formatDateTime(value),
      },
      {
        title: t("完成时间"),
        dataIndex: "finish_date",
        width: 160,
        render: (value?: string | null) => formatDateTime(value),
      },
      {
        title: t("操作"),
        key: "action",
        fixed: "right",
        width: 160,
        render: (_value, record) => (
          <ModoActionGroup
            actions={[
              { key: "detail", label: t("详情"), onClick: () => onOpenDetail(record) },
              {
                key: "download",
                label: t("下载产物"),
                disabled: !record.artifact_filename,
                title: record.artifact_filename ? undefined : t("暂无产物可下载"),
                onClick: () => void handleDownload(record),
              },
            ]}
          />
        ),
      },
    ];

    return (
      <>
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Input
                allowClear
                value={keywordInput}
                onChange={(event) => setKeywordInput(event.target.value)}
                placeholder={t("按任务 ID/类别/来源站点筛选")}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            {fixedKind ? null : (
              <Form.Item label={t("类型")} style={{ marginBottom: 0 }}>
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
              </Form.Item>
            )}
            <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
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
                  label: t(STATUS_META[key].label),
                }))}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                htmlType="button"
                icon={<SearchOutlined />}
                onClick={handleSearch}
                loading={loading}
                className="admin-search-btn"
              >
                {t("查询")}
              </Button>
            </Form.Item>
          </Form>
          <Segmented
            value={viewMode}
            onChange={(value) => setViewMode(value as "card" | "list")}
            options={[
              { label: t("卡片视图"), value: "card" },
              { label: t("列表视图"), value: "list" },
            ]}
          />
        </div>

        {error ? (
          <Alert type="error" showIcon style={{ marginBottom: 12 }} message={t("加载失败")} description={error} />
        ) : null}

        {filteredJobs.length === 0 ? (
          loading ? (
            <div className="flex w-full flex-1 items-center justify-center">
              <Spin />
            </div>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无任务记录")} />
          )
        ) : (
          <div className="relative flex min-h-0 flex-1 flex-col">
            {viewMode === "card" ? (
              <>
                <div className="admin-platform-data-card-scroll">
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {pageItems.map((job) => (
                      <PlatformDataJobCard
                        key={job.id}
                        job={job}
                        onDetail={onOpenDetail}
                        onDownload={(record) => void handleDownload(record)}
                      />
                    ))}
                  </div>
                </div>
                {loading ? (
                  <div className="absolute inset-0 z-10 flex items-center justify-center bg-[color-mix(in_srgb,var(--ant-color-bg-layout)_60%,transparent)]">
                    <Spin />
                  </div>
                ) : null}
              </>
            ) : (
              <div
                ref={tableScrollAnchorRef}
                className="admin-platform-data-table-view"
                style={{ "--admin-platform-data-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
              >
                <Table<JobSummary>
                  rowKey="id"
                  size="small"
                  loading={loading}
                  columns={columns}
                  dataSource={pageItems}
                  pagination={false}
                  scroll={{ x: 1320, y: tableScrollY }}
                  locale={{
                    emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无任务记录")} />,
                  }}
                />
              </div>
            )}
            <ModoPagination
              current={pagination.current}
              pageSize={pagination.pageSize}
              total={total}
              onChange={(page, pageSize) => setPagination({ current: page, pageSize })}
              containerClassName="admin-list-view-pagination"
            />
          </div>
        )}
      </>
    );
  },
);

function PlatformDataJobCard({
  job,
  onDetail,
  onDownload,
}: {
  job: JobSummary;
  onDetail: (job: JobSummary) => void;
  onDownload: (job: JobSummary) => void;
}) {
  const { t } = useI18n();
  const meta = STATUS_META[job.status] ?? STATUS_FALLBACK;
  const isExport = job.kind === "export";
  const categories =
    job.categories && job.categories.length
      ? job.categories.map((code) => t(CATEGORY_LABEL[code] ?? code)).join(" / ")
      : "—";

  return (
    <Card
      size="small"
      hoverable
      className="admin-platform-data-job-card"
      onClick={() => onDetail(job)}
    >
      <div className="flex flex-col">
        <div className="admin-platform-data-job-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          {isExport ? (
            <ExportOutlined className="text-base text-gray-500" />
          ) : (
            <ImportOutlined className="text-base text-gray-500" />
          )}
          <div className="flex min-w-0 flex-1 items-center justify-between gap-2">
            <Typography.Text strong className="truncate">
              {isExport ? t("导出任务") : t("导入任务")} · {job.id.slice(0, 8)}
            </Typography.Text>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Badge status={job.status === "success" ? "success" : job.status === "failed" ? "error" : job.status === "running" ? "processing" : "default"} />
              <Typography.Text type="secondary" className="text-xs">
                {t(meta.label)}
              </Typography.Text>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <TagsOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs truncate">
              {t("类别")}：{categories}
            </Text>
          </div>
          <div className="flex items-center gap-2">
            <FileZipOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs truncate">
              {t("包大小")}：{formatBytes(jobFileSize(job))}
            </Text>
          </div>
          <div className="flex items-center gap-2">
            <FileZipOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs truncate" title={job.artifact_filename ?? undefined}>
              {t("产物文件")}：{job.artifact_filename ?? "—"}
            </Text>
          </div>
          <div className="flex items-center gap-2">
            <GlobalOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs truncate">
              {t("来源站点")}：{job.source_site ?? "—"}
            </Text>
          </div>
          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">
              {t("创建时间")}：{formatDateTime(job.create_date)}
            </Text>
          </div>
          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">
              {t("完成时间")}：{formatDateTime(job.finish_date)}
            </Text>
          </div>
          {job.status === "failed" && job.error_message ? (
            <Text type="danger" className="text-xs" style={{ wordBreak: "break-all" }}>
              {job.error_message}
            </Text>
          ) : null}
        </div>

        <div className="admin-platform-data-job-card-actions flex items-center justify-end px-4 py-2 border-t border-gray-200">
          <Space size={4}>
            <Button
              type="link"
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                onDetail(job);
              }}
            >
              {t("详情")}
            </Button>
            <Button
              type="link"
              size="small"
              disabled={!job.artifact_filename}
              title={job.artifact_filename ? undefined : t("暂无产物可下载")}
              onClick={(event) => {
                event.stopPropagation();
                onDownload(job);
              }}
            >
              {t("下载产物")}
            </Button>
          </Space>
        </div>
      </div>
    </Card>
  );
}
