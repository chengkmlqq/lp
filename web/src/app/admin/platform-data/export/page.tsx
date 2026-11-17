"use client";

/**
 * 基础数据包「导出」页（交付人员用）。
 *
 * 保留：导出表单（类别 + ATP 模型维度筛选）+ 任务列表（状态轮询 + 下载产物 + 详情）。
 * 导入组件已拆到 /admin/platform-data/import。
 *
 * 端点（LP-14 既有）：
 *   POST /admin/platform-data/export        异步导出
 *   GET  /admin/platform-data/jobs          历史任务列表
 *   GET  /admin/platform-data/jobs/{id}     任务详情
 *   GET  /admin/platform-data/jobs/{id}/download  重新下载产物
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DownloadOutlined, ReloadOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { modoTablePagination } from "@/components/biz/modo-pagination";
import { readApiError } from "@/lib/api";
import { measureTableScrollY } from "@/lib/table-scroll-y";
import type { DimensionItemListResponse } from "@/types/dimension";
import {
  CATEGORY_LABEL,
  CATEGORY_OPTIONS,
  EMPTY_EXPORT_DIMENSION_OPTIONS,
  EXPORT_DIMENSION_TYPE_CODES,
  POLL_INTERVAL_MS,
  STATUS_FALLBACK,
  STATUS_META,
  TABLE_MIN_SCROLL_Y,
  PlatformDataDetailDrawer,
  flattenDimensionTypes,
  formatDateTime,
  summarizeResult,
  type ExportDimensionField,
  type ExportDimensionOptions,
  type JobDetail,
  type JobKind,
  type JobStatus,
  type JobSummary,
  type DimensionOption,
} from "../shared";

const { Text } = Typography;

export default function PlatformDataExportPage() {
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
  const [filterVoltage, setFilterVoltage] = useState<string[]>([]);
  const [filterTower, setFilterTower] = useState<string[]>([]);
  const [filterScene, setFilterScene] = useState<string[]>([]);
  const [dimensionOptions, setDimensionOptions] = useState<ExportDimensionOptions>(EMPTY_EXPORT_DIMENSION_OPTIONS);
  const [exportLoading, setExportLoading] = useState(false);

  const atpModelsSelected = exportCategories.includes("atp_models");

  // 仅在勾选「ATP 模型」类别时按需加载维度选项（types/tree + 每维度一次 dimensions）
  const dimensionOptionsLoadedRef = useRef(false);
  useEffect(() => {
    if (!atpModelsSelected || !canManage || dimensionOptionsLoadedRef.current) return;
    dimensionOptionsLoadedRef.current = true;
    void (async () => {
      try {
        const treeResponse = await fetchWithAuth("/api/v1/dimensions/types/tree");
        if (!treeResponse.ok) return;
        const types = (await treeResponse.json()) as import("@/types/auth").DimensionTypeTreeItem[];
        const flatTypes = flattenDimensionTypes(types);
        const fields = Object.keys(EXPORT_DIMENSION_TYPE_CODES) as ExportDimensionField[];
        const loaded = await Promise.all(
          fields.map(async (field): Promise<[ExportDimensionField, DimensionOption[]]> => {
            const typeId = flatTypes.find((t) => t.code === EXPORT_DIMENSION_TYPE_CODES[field])?.id;
            if (!typeId) return [field, []];
            const params = new URLSearchParams();
            params.set("type_id", typeId);
            params.set("enabled", "true");
            params.set("limit", "200");
            const response = await fetchWithAuth(`/api/v1/dimensions?${params.toString()}`);
            if (!response.ok) return [field, []];
            const data = (await response.json()) as DimensionItemListResponse;
            const options = (data.items ?? [])
              .map((item) => ({ label: item.name, value: item.code }))
              .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
            return [field, options];
          }),
        );
        setDimensionOptions(Object.fromEntries(loaded) as ExportDimensionOptions);
      } catch {
        /* 维度选项加载失败不阻断导出，下拉保持空选项 */
      }
    })();
  }, [atpModelsSelected, canManage, fetchWithAuth]);

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

  // 初始加载
  useEffect(() => {
    if (!canManage) return;
    void loadJobs();
  }, [canManage, loadJobs]);

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

  // ── 导出 ──────────────────────────────────────────────────────────
  const handleExport = async () => {
    if (exportCategories.length === 0) {
      message.warning(t("请至少勾选一个导出类别"));
      return;
    }
    const filters: Record<string, string[]> = {};
    if (atpModelsSelected) {
      if (filterVoltage.length) filters.voltage_level = filterVoltage;
      if (filterTower.length) filters.tower_type = filterTower;
      if (filterScene.length) filters.scene = filterScene;
    }
    setExportLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categories: exportCategories, filters }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("已创建导出任务，正在打包…"));
      void loadJobs();
      setPagination((prev) => ({ ...prev, current: 1 }));
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setExportLoading(false);
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
      width: 160,
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
            {atpModelsSelected ? (
              <>
                <Form.Item label={t("电压")} style={{ marginBottom: 0 }}>
                  <Select
                    mode="multiple"
                    allowClear
                    style={{ width: 200 }}
                    placeholder={t("请选择电压等级")}
                    value={filterVoltage}
                    onChange={(values) => setFilterVoltage(values ?? [])}
                    options={dimensionOptions.voltage_level}
                    maxTagCount="responsive"
                  />
                </Form.Item>
                <Form.Item label={t("塔型")} style={{ marginBottom: 0 }}>
                  <Select
                    mode="multiple"
                    allowClear
                    style={{ width: 200 }}
                    placeholder={t("请选择塔型")}
                    value={filterTower}
                    onChange={(values) => setFilterTower(values ?? [])}
                    options={dimensionOptions.tower_type}
                    maxTagCount="responsive"
                  />
                </Form.Item>
                <Form.Item label={t("场景")} style={{ marginBottom: 0 }}>
                  <Select
                    mode="multiple"
                    allowClear
                    style={{ width: 200 }}
                    placeholder={t("请选择场景")}
                    value={filterScene}
                    onChange={(values) => setFilterScene(values ?? [])}
                    options={dimensionOptions.scene}
                    maxTagCount="responsive"
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
                label: t(STATUS_META[key].label),
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
            scroll={{ x: 1150, y: tableScrollY }}
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
