"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  type TabsProps,
  type TableColumnsType,
  type UploadFile,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
  InboxOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { WindLightningDensityDetailView } from "@/components/wind-lightning-density-detail-view";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useI18n } from "@/lib/i18n";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { getJson, readApiError } from "@/lib/api";
import { generateWindLightningTemplate, generateWindTurbineTemplate } from "@/lib/excel-import-utils";
import type {
  WindLightningDensityBatchListResponse,
  WindLightningDensityBatchSummary,
  WindLightningDensityPreviewResponse,
} from "@/types/wind-lightning-density";

const { Text } = Typography;

const API_BASE = "/api/v1/wind-lightning-density";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

type CreateFormValues = {
  batch_name?: string;
  wind_farm_name?: string;
  notes?: string;
  grid_step_deg?: number;
  margin_deg?: number;
  years_source?: "auto" | "fixed";
};

type DetailTabData = {
  key: string;
  title: string;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

function formatDegDraft(value: number | undefined, fallback: number): string {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return formatDegDraft(fallback, fallback);
  }
  return number.toFixed(10).replace(/0+$/, "").replace(/\.$/, "") || "0";
}

/** 与后端 build_batch_name 同口径的草稿名（真正批次名以后端返回为准）。 */
function buildBatchNameDraft(
  values: Pick<CreateFormValues, "wind_farm_name" | "grid_step_deg" | "margin_deg" | "years_source">,
  turbineFileName: string,
  dataYears: number | null | undefined,
  now: Date = new Date(),
): string {
  let farm = (values.wind_farm_name || "").trim();
  if (!farm) {
    const stem = turbineFileName.split(/[\\/]/).pop() || "";
    farm = stem.replace(/\.[^.]*$/, "").trim();
  }
  const safeFarm =
    farm
      .replace(/[^\p{L}\p{N}_-]+/gu, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 20) || "未命名风电场";

  const fixed = values.years_source === "fixed";
  const years =
    fixed || dataYears === null || dataYears === undefined
      ? 6
      : Math.max(1, Math.round(dataYears));
  const pad = (input: number) => String(input).padStart(2, "0");
  const stamp = `${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(
    now.getMinutes(),
  )}`;
  return `${safeFarm}_Y${years}${fixed ? "F" : "A"}_G${formatDegDraft(
    values.grid_step_deg,
    0.01,
  )}_M${formatDegDraft(values.margin_deg, 0.01)}_${stamp}`.slice(0, 250);
}

const WIND_TABLE_MIN_SCROLL_Y = 180;
const WIND_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const WIND_TABLE_BOTTOM_GAP = 8;

export default function WindLightningDensityListPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_lightning_density.read") || hasPermission("wind_lightning_density.manage");
  // 删除口径对齐线路管理写操作（菜单可见即可操作）：有页面访问权限即可删除，
  // 接口层同步放开 read||manage，避免"按钮可见但接口 403"。
  const canDelete = canRead;
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");
  const [logOpen, setLogOpen] = useState(false);
  const [logTaskId, setLogTaskId] = useState<string | null>(null);
  const [logTitle, setLogTitle] = useState(t("任务执行日志"));
  const openLogViewer = useCallback(
    (taskId: string | null | undefined, label: string, title: string) => {
      if (!taskId || !canReadLogs) {
        return;
      }
      setLogTaskId(taskId);
      setLogTitle(label ? `${label} - ${title}` : title);
      setLogOpen(true);
    },
    [canReadLogs],
  );

  const queryClient = useQueryClient();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");

  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [detailTabsData, setDetailTabsData] = useState<DetailTabData[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<CreateFormValues>();
  const [turbineFiles, setTurbineFiles] = useState<UploadFile[]>([]);
  const [lightningFiles, setLightningFiles] = useState<UploadFile[]>([]);
  const [preview, setPreview] = useState<WindLightningDensityPreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-lightning-density", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    // 查询/翻页时保留上一份数据作占位，列表/卡片不清空，仅叠加 loading 遮罩，避免闪空。
    // 后台同 key 轮询属于静默刷新，不触发占位态。
    placeholderData: (previousData) => previousData,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) {
        params.set("keyword", keyword.trim());
      }
      if (statusFilter) {
        params.set("status", statusFilter);
      }
      return getJson<WindLightningDensityBatchListResponse>(`${API_BASE}?${params.toString()}`);
    },
    refetchInterval: (queryResult) => {
      const items = queryResult.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing") ? 4000 : false;
    },
  });

  const records = listQuery.data?.items ?? [];

  // 列表视图分页钉底（参考线路管理 pages/power-lines）：动态算表体高度，
  // 让分页条始终固定在页面右下角，表格体在剩余空间内滚动（不产生整页滚动条）。
  const [tableScrollY, setTableScrollY] = useState(WIND_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return WIND_TABLE_MIN_SCROLL_Y;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return WIND_TABLE_MIN_SCROLL_Y;
    }
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-lightning-distribution-list-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    // 分页器是卡片/列表共用的外置 ModoPagination，不在锚点内部；按面板取其实测高度，
    // 避免 anchor.querySelector(".ant-table-pagination") 落空后用 64px 回退而少算表体高度。
    const pagination = pane?.querySelector<HTMLElement>(".admin-list-view-pagination")
      ?? anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? WIND_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = pagination?.getBoundingClientRect().height ?? WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available = containerRect.bottom - containerPadBottom - anchorTop - WIND_TABLE_BOTTOM_GAP;
    // 与故障分析页一致：分页钉在面板底部，预留 16px 上方间距 + 4px 余量（共 20px）。
    // available 已扣除面板底部 8px 余量，这里加回后再扣分页高度与 20px 间距，避免表格下方留白。
    const nextHeight = Math.floor(available - headerHeight - paginationHeight + WIND_TABLE_BOTTOM_GAP - 20);
    return Math.max(WIND_TABLE_MIN_SCROLL_Y, nextHeight);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => window.requestAnimationFrame(updateTableScrollHeight);
    window.addEventListener("resize", onViewportChange);
    return () => window.removeEventListener("resize", onViewportChange);
  }, [updateTableScrollHeight]);
  useEffect(() => {
    if (viewMode !== "list") {
      return;
    }
    setTableScrollY(updateTableScrollHeight());
    const raf = window.requestAnimationFrame(() => setTableScrollY(updateTableScrollHeight()));
    return () => window.cancelAnimationFrame(raf);
  }, [viewMode, records.length, updateTableScrollHeight]);


  const refreshList = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-lightning-density"] });
  }, [queryClient]);

  const openDetail = useCallback((batchId: string, title: string) => {
    setDetailTabsData((previous) =>
      previous.some((tab) => tab.key === batchId) ? previous : [...previous, { key: batchId, title }],
    );
    setActiveTabKey(batchId);
  }, []);

  const closeDetailTab = useCallback(
    (key: string) => {
      const removedIndex = detailTabsData.findIndex((tab) => tab.key === key);
      const next = detailTabsData.filter((tab) => tab.key !== key);
      setDetailTabsData(next);
      if (activeTabKey === key) {
        const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
        setActiveTabKey(fallback);
      }
    },
    [activeTabKey, detailTabsData],
  );

  const handleTabsEdit = useCallback(
    (targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
      if (action !== "remove") {
        return;
      }
      closeDetailTab(String(targetKey));
    },
    [closeDetailTab],
  );

  const detailTabs = useMemo<NonNullable<TabsProps["items"]>>(
    () =>
      detailTabsData.map((tab) => ({
        key: tab.key,
        label: (
          <Tooltip title={tab.title}>
            <span>{tab.title.length > 14 ? `${tab.title.slice(0, 14)}...` : tab.title}</span>
          </Tooltip>
        ),
        closable: true,
        children: <WindLightningDensityDetailView batchId={tab.key} onClose={() => closeDetailTab(tab.key)} />,
      })),
    [closeDetailTab, detailTabsData],
  );

  const buildCreateFormData = useCallback(
    (values: CreateFormValues): FormData | null => {
      const turbineFile = turbineFiles[0]?.originFileObj as File | undefined;
      const lightningFile = lightningFiles[0]?.originFileObj as File | undefined;
      if (!turbineFile) {
        message.warning(t("请选择风机点位文件"));
        return null;
      }
      if (!lightningFile) {
        message.warning(t("请选择雷电定位 CSV 文件"));
        return null;
      }
      const formData = new FormData();
      formData.append("turbine_file", turbineFile);
      formData.append("lightning_file", lightningFile);
      formData.append("batch_name", (values.batch_name || "").trim());
      formData.append("wind_farm_name", (values.wind_farm_name || "").trim());
      formData.append("notes", (values.notes || "").trim());
      formData.append("grid_step_deg", String(values.grid_step_deg ?? 0.01));
      formData.append("margin_deg", String(values.margin_deg ?? 0.01));
      formData.append("years_source", values.years_source ?? "auto");
      return formData;
    },
    [lightningFiles, message, t, turbineFiles],
  );

  // 草稿名：字段/文件/预览结果变化时联动刷新；最终名称由后端生成并覆盖。
  const syncDraftName = useCallback(
    (incomingPreview?: WindLightningDensityPreviewResponse | null) => {
      const values = form.getFieldsValue(true) as CreateFormValues;
      const source = incomingPreview === undefined ? preview : incomingPreview;
      const draft = buildBatchNameDraft(values, turbineFiles[0]?.name || "", source?.data_years);
      form.setFieldsValue({ batch_name: draft });
      return draft;
    },
    [form, preview, turbineFiles],
  );

  useEffect(() => {
    if (createOpen) {
      syncDraftName();
    }
  }, [createOpen, syncDraftName]);

  const handlePreview = useCallback(async () => {
    const values = await form.validateFields();
    const formData = buildCreateFormData(values);
    if (!formData) {
      return;
    }
    setPreviewing(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/preview`, { method: "POST", body: formData });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as WindLightningDensityPreviewResponse;
      setPreview(data);
      syncDraftName(data); // 预览成功后用真实统计年限刷新草稿名
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setPreviewing(false);
    }
  }, [buildCreateFormData, fetchWithAuth, form, message, syncDraftName]);

  const handleDownloadTurbineTemplate = useCallback(() => {
    try {
      generateWindTurbineTemplate();
      message.success(t("风机点位模板下载成功"));
    } catch {
      message.error(t("风机点位模板下载失败"));
    }
  }, [message, t]);

  const handleDownloadLightningTemplate = useCallback(() => {
    try {
      generateWindLightningTemplate();
      message.success(t("雷电定位数据模板下载成功"));
    } catch {
      message.error(t("雷电定位数据模板下载失败"));
    }
  }, [message, t]);

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    values.batch_name = syncDraftName(); // 提交前再同步一次表单值
    const formData = buildCreateFormData(values);
    if (!formData) {
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetchWithAuth(API_BASE, { method: "POST", body: formData });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      message.success(t("已提交统计任务，正在后台计算"));
      setCreateOpen(false);
      setPreview(null);
      setTurbineFiles([]);
      setLightningFiles([]);
      form.resetFields();
      // 提交后停留在列表页：回到第 1 页并清空状态筛选，确保新批次可见；
      // 列表已有 4 秒轮询，进度会自动推进，无需跳转详情。
      setStatusFilter(undefined);
      setPage(1);
      setActiveTabKey(LIST_TAB_KEY);
      refreshList();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [buildCreateFormData, fetchWithAuth, form, message, refreshList, syncDraftName, t]);

  const handleDelete = useCallback(
    (record: WindLightningDensityBatchSummary) => {
      modal.confirm({
        title: t("删除该批次？"),
        content: t("删除后列表不再展示，原始文件保留在对象存储中。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("取消"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}`, { method: "DELETE" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已删除"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const columns = useMemo<TableColumnsType<WindLightningDensityBatchSummary>>(
    () => [
      {
        title: t("批次名称"),
        dataIndex: "batch_name",
        key: "batch_name",
        width: 240,
        render: (_value, record) => {
          const batchName = record.batch_name || record.id;
          return (
            <Button
              type="link"
              title={batchName}
              style={{
                padding: 0,
                height: "auto",
                display: "inline-block",
                maxWidth: "100%",
                overflow: "hidden",
                verticalAlign: "middle",
              }}
              styles={{
                content: {
                  display: "block",
                  maxWidth: "100%",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                },
              }}
              onClick={() => openDetail(record.id, batchName)}
            >
              {batchName}
            </Button>
          );
        },
      },
      {
        title: t("风电场"),
        dataIndex: "wind_farm_name",
        key: "wind_farm_name",
        width: 160,
        render: (_value, record) => record.wind_farm_name || "-",
      },
      {
        title: t("风机数"),
        dataIndex: "turbine_count",
        key: "turbine_count",
        width: 90,
      },
      {
        title: t("有效落雷"),
        dataIndex: "valid_records",
        key: "valid_records",
        width: 110,
        render: (value: number, record) => (
          <Tooltip title={`${t("总记录")} ${record.total_records} / ${t("跳过")} ${record.skipped_records}`}>
            <span>{value}</span>
          </Tooltip>
        ),
      },
      {
        title: t("统计年限"),
        dataIndex: "data_years",
        key: "data_years",
        width: 120,
        render: (value: number | null) => (value ? `${value} ${t("年")}` : "-"),
      },
      {
        title: t("整体密度"),
        dataIndex: "overall_density",
        key: "overall_density",
        width: 130,
        render: (value: number | null) => formatNumber(value),
      },
      {
        title: t("峰值密度"),
        dataIndex: "peak_density",
        key: "peak_density",
        width: 130,
        render: (value: number | null) => formatNumber(value),
      },
      {
        title: t("网格"),
        dataIndex: "grid_x_count",
        key: "grid",
        width: 110,
        render: (_value, record) => `${record.grid_x_count} × ${record.grid_y_count}`,
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        width: 170,
        render: (value: string, record) => {
          const meta = STATUS_META[value] ?? STATUS_META.pending;
          return (
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Tag color={meta.color}>{t(meta.label)}</Tag>
              {value === "failed" && record.error_message ? (
                <Text type="danger" style={{ fontSize: 12 }} ellipsis={{ tooltip: record.error_message }}>
                  {record.error_message}
                </Text>
              ) : null}
            </Space>
          );
        },
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 160,
        fixed: "right",
        render: (_value, record) => (
          <ModoActionGroup
            actions={[
              {
                key: "detail",
                label: t("详情"),
                icon: <EyeOutlined />,
                onClick: () => openDetail(record.id, record.batch_name || record.id),
              },
              {
                key: "log",
                label: t("日志"),
                icon: <FileTextOutlined />,
                visible: Boolean(canReadLogs && record.task_id),
                onClick: () =>
                  openLogViewer(record.task_id, t("任务执行日志"), record.batch_name || record.id),
              },
              {
                key: "delete",
                label: t("删除"),
                icon: <DeleteOutlined />,
                danger: true,
                visible: canDelete,
                onClick: () => handleDelete(record),
              },
            ]}
          />
        ),
      },
    ],
    [canDelete, canReadLogs, openLogViewer, handleDelete, openDetail, t],
  );

  const paginationNode = (
    <ModoPagination
      current={page}
      pageSize={pageSize}
      total={listQuery.data?.total ?? 0}
      showSizeChanger
      pageSizeOptions={[10, 20, 50, 100]}
      onChange={(nextPage, nextSize) => {
        setPage(nextPage);
        if (nextSize && nextSize !== pageSize) {
          setPageSize(nextSize);
          setPage(1);
        }
      }}
      containerClassName="admin-list-view-pagination"
    />
  );

  const renderRecordCard = (record: WindLightningDensityBatchSummary) => {
    const meta = STATUS_META[record.status] ?? STATUS_META.pending;
    return (
      <Card
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={() => openDetail(record.id, record.batch_name || record.id)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Tooltip title={record.batch_name || record.id}>
                <Text strong className="truncate min-w-0">
                  {record.batch_name || record.id}
                </Text>
              </Tooltip>
              <Tag color={meta.color} style={{ marginInlineEnd: 0, flexShrink: 0 }}>
                {t(meta.label)}
              </Tag>
            </div>
          </div>

          <div className="flex flex-col gap-1 px-4 py-3">
            <Text type="secondary" className="text-xs truncate">
              {t("风电场")}：{record.wind_farm_name || "-"}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("风机数")}：{record.turbine_count} · {t("有效落雷")}：{record.valid_records}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("统计年限")}：{record.data_years ? `${record.data_years} ${t("年")}` : "-"}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("整体密度")}：{formatNumber(record.overall_density)} · {t("峰值密度")}：
              {formatNumber(record.peak_density)}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("创建时间")}：{formatDateTime(record.create_date)}
            </Text>
          </div>

          <div className="admin-lightning-distribution-event-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {record.status === "processing" || record.status === "pending" ? (
              <Progress percent={record.progress} size="small" className="flex-1 max-w-40" />
            ) : (
              <div />
            )}
            <Space size="small" className="flex-wrap">
              <Tooltip title={t("详情")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openDetail(record.id, record.batch_name || record.id);
                  }}
                />
              </Tooltip>
              {canReadLogs && record.task_id ? (
                <Tooltip title={t("运行日志")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<FileTextOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      openLogViewer(record.task_id, t("任务执行日志"), record.batch_name || record.id);
                    }}
                  />
                </Tooltip>
              ) : null}
              <Dropdown
                menu={{
                  items: [
                    ...(canDelete
                      ? [
                          {
                            key: "delete",
                            label: (
                              <Space size={4}>
                                <DeleteOutlined />
                                <span>{t("删除")}</span>
                              </Space>
                            ),
                            danger: true,
                            onClick: (event) => {
                              event.domEvent.stopPropagation();
                              handleDelete(record);
                            },
                          },
                        ]
                      : []),
                  ],
                }}
                trigger={["click"]}
              >
                <Tooltip title={t("更多")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    onClick={(event) => event.stopPropagation()}
                  />
                </Tooltip>
              </Dropdown>
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  if (initializing) {
    return null;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="modo-page-tabs"
        tabBarExtraContent={
          <Button
            icon={<PlusOutlined />}
            type="primary"
            onClick={() => {
              setPreview(null);
              setCreateOpen(true);
            }}
          >
            {t("新建统计")}
          </Button>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("地闪密度统计")}</>,
            closable: false,
            children: (
              <div className="modo-page-card admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("批次名称 / 风电场")}
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={() => setKeyword(keywordInput)}
                      />
                    </Form.Item>
                    <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={(value) => setStatusFilter(value)}
                        options={[
                          { label: t("待处理"), value: "pending" },
                          { label: t("处理中"), value: "processing" },
                          { label: t("已完成"), value: "completed" },
                          { label: t("失败"), value: "failed" },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Space>
                        <Button icon={<SearchOutlined />} onClick={() => setKeyword(keywordInput)}>
                          {t("查询")}
                        </Button>
                      </Space>
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

                <div className="relative flex min-h-0 flex-1 flex-col">
                {viewMode === "card" ? (
                    <div className="admin-lightning-distribution-card-scroll">
                      {listQuery.isLoading && records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Spin />
                        </div>
                      ) : records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("暂无统计批次，点击「新建统计」上传风机点位与雷电定位数据")}
                          />
                        </div>
                      ) : (
                        /* 查询/轮询刷新时不清空已有卡片，仅叠加 loading 遮罩 */
                        <Spin spinning={listQuery.isLoading || listQuery.isPlaceholderData} className="admin-card-view-spin">
                          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                            {records.map(renderRecordCard)}
                          </div>
                        </Spin>
                      )}
                    </div>
                ) : (
                  <div ref={tableScrollAnchorRef} className="admin-wind-table-view" style={{ "--admin-wind-table-body-min-height": `${tableScrollY}px` } as CSSProperties}>
                  <Table<WindLightningDensityBatchSummary>
                    rowKey="id"
                    size="middle"
                    loading={listQuery.isLoading || listQuery.isPlaceholderData}
                    columns={columns}
                    dataSource={records}
                    pagination={false}
                    scroll={{ x: 1590, y: tableScrollY }}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无统计批次，点击「新建统计」上传风机点位与雷电定位数据")}
                        />
                      ),
                    }}
                  />
                  </div>
                )}
                  {paginationNode}
                </div>
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title={t("新建地闪密度统计")}
        width={760}
        open={createOpen}
        destroyOnHidden
        onCancel={() => {
          setCreateOpen(false);
          setPreview(null);
        }}
        styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
        footer={
          <Space style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button onClick={() => setCreateOpen(false)}>{t("取消")}</Button>
            <Button type="primary" onClick={handleSubmit} loading={submitting}>
              {t("提交统计")}
            </Button>
          </Space>
        }
      >
        <Form<CreateFormValues>
          form={form}
          layout="vertical"
          initialValues={{ grid_step_deg: 0.01, margin_deg: 0.01, years_source: "auto" }}
          onValuesChange={(_changed, allValues) => {
            form.setFieldsValue({
              batch_name: buildBatchNameDraft(
                allValues,
                turbineFiles[0]?.name || "",
                preview?.data_years,
              ),
            });
          }}
        >
          <div className="fl-create-form-grid">
            <Form.Item
              className="fl-span-2"
              label={t("批次名称")}
              name="batch_name"
              tooltip={t("系统根据风电场、年限和布场参数自动生成，同名时自动加序号")}
            >
              <Input readOnly />
            </Form.Item>
            <Form.Item label={t("风电场名称")} name="wind_farm_name">
              <Input placeholder={t("例如：江苏A3风电场")} maxLength={128} />
            </Form.Item>
            <Form.Item
              label={t("网格步长（度）")}
              name="grid_step_deg"
              tooltip={t("默认 0.01°（约 1km），与核心程序一致；单边网格数超过 500 会被拒绝")}
            >
              <InputNumber min={0.001} max={1} step={0.001} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item
              label={t("外扩边距（度）")}
              name="margin_deg"
              tooltip={t("统计范围为风机经/纬度 min/max 四周各外扩该值，默认 0.01°")}
            >
              <InputNumber min={0} max={0.5} step={0.005} style={{ width: "100%" }} />
            </Form.Item>

            <Form.Item
              label={t("统计年限来源")}
              name="years_source"
              tooltip={t("自动：能从时间列推断则用实际覆盖年数，否则 6 年；固定：始终 6 年")}
            >
              <Select
                options={[
                  { label: t("自动（优先实际覆盖年份）"), value: "auto" },
                  { label: t("固定 6 年"), value: "fixed" },
                ]}
              />
            </Form.Item>

            <Form.Item className="fl-span-2" label={t("备注")} name="notes">
              <Input.TextArea rows={2} maxLength={500} />
            </Form.Item>

            <Form.Item
              className="fl-span-2"
              required
              label={t("风机点位文件（txt 11 列 / Excel）")}
            >
              <Upload.Dragger
                accept=".txt,.csv,.xlsx,.xlsm"
                maxCount={1}
                fileList={turbineFiles}
                beforeUpload={() => false}
                onChange={({ fileList }) => setTurbineFiles(fileList.slice(-1))}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">{t("点击或拖拽 file_2.txt / 风机点位表到此区域")}</p>
                <p className="ant-upload-hint">
                  {t("txt 按 11 列空白分隔（前 6 列为经纬度度分秒）；Excel 支持「经度/纬度」或「经度度/分/秒」列名")}
                </p>
                <div className="flex items-center justify-center gap-2">
                  <Button
                    type="link"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      handleDownloadTurbineTemplate();
                    }}
                  >
                    {t("下载模板")}
                  </Button>
                </div>
              </Upload.Dragger>
            </Form.Item>

            <Form.Item
              className="fl-span-2"
              required
              label={t("雷电定位 CSV（LONGITUDE / LATITUDE）")}
            >
              <Upload.Dragger
                accept=".csv,.txt"
                maxCount={1}
                fileList={lightningFiles}
                beforeUpload={() => false}
                onChange={({ fileList }) => setLightningFiles(fileList.slice(-1))}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">{t("点击或拖拽雷电定位 CSV 到此区域")}</p>
                <p className="ant-upload-hint">{t("支持 UTF-8 / GBK 编码，含 DATETIME 列时可自动推断统计年限")}</p>
                <div className="flex items-center justify-center gap-2">
                  <Button
                    type="link"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      handleDownloadLightningTemplate();
                    }}
                  >
                    {t("下载模板")}
                  </Button>
                </div>
              </Upload.Dragger>
            </Form.Item>
          </div>
        </Form>

        {preview ? (
          <Card size="small" title={t("提交前预览")} style={{ marginTop: 8 }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label={t("风机数")}>{preview.turbine_count}</Descriptions.Item>
              <Descriptions.Item label={t("跳过风机")}>{preview.turbine_skipped}</Descriptions.Item>
              <Descriptions.Item label={t("雷电记录")}>{preview.total_records}</Descriptions.Item>
              <Descriptions.Item label={t("范围内落雷")}>{preview.in_range_records}</Descriptions.Item>
              <Descriptions.Item label={t("网格数")} span={2}>
                {preview.grid_x_count} × {preview.grid_y_count}
              </Descriptions.Item>
              <Descriptions.Item label={t("统计范围")} span={2}>
                {preview.bbox_min_lon?.toFixed(4)} ~ {preview.bbox_max_lon?.toFixed(4)}（{t("经度")}）
                <br />
                {preview.bbox_min_lat?.toFixed(4)} ~ {preview.bbox_max_lat?.toFixed(4)}（{t("纬度")}）
              </Descriptions.Item>
              <Descriptions.Item label={t("统计年限")}>{preview.data_years} {t("年")}</Descriptions.Item>
              <Descriptions.Item label={t("面积（km²）")}>{formatNumber(preview.area_km2, 3)}</Descriptions.Item>
            </Descriptions>
            {preview.warnings.length ? (
              <Alert
                style={{ marginTop: 12 }}
                type="warning"
                showIcon
                message={t("提示")}
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.warnings.map((warning) => (
                      <li key={warning}>{t(warning)}</li>
                    ))}
                  </ul>
                }
              />
            ) : null}
          </Card>
        ) : null}
      </Modal>

      <TaskLogViewerDrawer
        taskId={logTaskId}
        title={logTitle}
        open={logOpen}
        onClose={() => setLogOpen(false)}
      />
    </div>
  );
}
