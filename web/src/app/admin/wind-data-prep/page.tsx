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
  App,
  Button,
  Card,
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
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
  InboxOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { WindDataPrepDetailView } from "@/components/wind-data-prep-detail-view";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useI18n } from "@/lib/i18n";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { generateWindLightningTemplate, generateWindTurbineTemplate } from "@/lib/excel-import-utils";
import type {
  WindDataPrepBatchListResponse,
  WindDataPrepBatchSummary,
  WindDataPrepImportResponse,
} from "@/types/wind-data-prep";

const { Text } = Typography;

const API_BASE = "/api/v1/wind-data-prep";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

type WizardValues = {
  name?: string;
  wind_farm_name?: string;
  remark?: string;
  start_lon?: number;
  start_lat?: number;
  grid_nx?: number;
  grid_ny?: number;
  grid_step_deg?: number;
  risk_base_s?: number;
  terrain_mode?: "zero" | "tif";
};

type DetailTabData = {
  key: string;
  title: string;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatNumber(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

/** 0.01° 对齐校验（与后端 wind_grid.is_aligned 同口径）。 */
function isAligned(value: number | undefined): boolean {
  if (value === undefined || !Number.isFinite(value)) return false;
  return Math.abs(value * 100 - Math.round(value * 100)) < 1e-6;
}

const WIND_TABLE_MIN_SCROLL_Y = 180;
const WIND_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const WIND_TABLE_BOTTOM_GAP = 8;

export default function WindDataPrepListPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_data_prep.read") || hasPermission("wind_data_prep.manage");
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

  const [wizardOpen, setWizardOpen] = useState(false);
  const [form] = Form.useForm<WizardValues>();
  // 地形模式需响应式控制 tif 上传区显隐（替代原分步里只在父级渲染时读取快照的写法）
  const terrainMode = Form.useWatch("terrain_mode", form);
  const [turbineFiles, setTurbineFiles] = useState<UploadFile[]>([]);
  const [lightningFiles, setLightningFiles] = useState<UploadFile[]>([]);
  const [terrainFiles, setTerrainFiles] = useState<UploadFile[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-data-prep", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    // 查询/翻页时保留上一份数据作占位，卡片/列表不清空，仅叠加 loading 遮罩，避免闪空。
    // 后台同 key 轮询属于静默刷新，不触发占位态。
    placeholderData: (previousData) => previousData,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (statusFilter) params.set("status", statusFilter);
      return getJson<WindDataPrepBatchListResponse>(`${API_BASE}?${params.toString()}`);
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
    void queryClient.invalidateQueries({ queryKey: ["wind-data-prep"] });
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
        children: <WindDataPrepDetailView batchId={tab.key} onClose={() => closeDetailTab(tab.key)} />,
      })),
    [closeDetailTab, detailTabsData],
  );

  const openWizard = useCallback(() => {
    setTurbineFiles([]);
    setLightningFiles([]);
    setTerrainFiles([]);
    form.resetFields();
    form.setFieldsValue({
      grid_step_deg: 0.01,
      risk_base_s: 1,
      terrain_mode: "zero",
    });
    setWizardOpen(true);
  }, [form]);

  const buildFormData = useCallback(
    async (values: WizardValues, requireFiles: boolean): Promise<FormData | null> => {
      const lon = values.start_lon;
      const lat = values.start_lat;
      const nx = values.grid_nx;
      const ny = values.grid_ny;
      if (lon === undefined || lat === undefined || nx === undefined || ny === undefined) {
        message.warning(t("请填写完整的区域参数"));
        return null;
      }
      if (!isAligned(lon) || !isAligned(lat)) {
        message.error(t("起始经纬度必须是 0.01° 的整数倍（例如 119.34）"));
        return null;
      }
      if (nx > 100 || ny > 100 || nx < 1 || ny < 1) {
        message.error(t("经向/纬向网格数必须在 1–100 之间（核心程序 NMAX=100）"));
        return null;
      }
      const turbineFile = turbineFiles[0]?.originFileObj as File | undefined;
      const lightningFile = lightningFiles[0]?.originFileObj as File | undefined;
      if (requireFiles && !turbineFile) {
        message.warning(t("请选择风机文件"));
        return null;
      }
      if (requireFiles && !lightningFile) {
        message.warning(t("请选择雷电 CSV 文件"));
        return null;
      }
      const terrainFile = terrainFiles[0]?.originFileObj as File | undefined;
      if (values.terrain_mode === "tif" && requireFiles && !terrainFile) {
        message.warning(t("已选择 tif 地形，请上传 tif 文件"));
        return null;
      }
      const formData = new FormData();
      if (turbineFile) formData.append("turbine_file", turbineFile);
      if (lightningFile) formData.append("lightning_file", lightningFile);
      if (terrainFile) formData.append("terrain_file", terrainFile);
      formData.append("name", (values.name || "").trim());
      formData.append("wind_farm_name", (values.wind_farm_name || "").trim());
      formData.append("remark", (values.remark || "").trim());
      formData.append("start_lon", String(lon));
      formData.append("start_lat", String(lat));
      formData.append("grid_nx", String(nx));
      formData.append("grid_ny", String(ny));
      formData.append("grid_step_deg", String(values.grid_step_deg ?? 0.01));
      formData.append("risk_base_s", String(values.risk_base_s ?? 1));
      formData.append("terrain_mode", values.terrain_mode ?? "zero");
      return formData;
    },
    [lightningFiles, message, t, terrainFiles, turbineFiles],
  );

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    const formData = await buildFormData(values, true);
    if (!formData) return;
    setSubmitting(true);
    try {
      const response = await fetchWithAuth(API_BASE, { method: "POST", body: formData });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindDataPrepImportResponse;
      message.success(t("已提交数据准备任务，正在后台生成五文件"));
      setWizardOpen(false);
      setTurbineFiles([]);
      setLightningFiles([]);
      setTerrainFiles([]);
      form.resetFields();
      refreshList();
      openDetail(result.batch_id, (values.name || values.wind_farm_name || "").trim() || result.batch_id);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [buildFormData, fetchWithAuth, form, message, openDetail, refreshList, t]);

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

  const handleDelete = useCallback(
    (record: WindDataPrepBatchSummary) => {
      modal.confirm({
        title: t("删除该批次？"),
        content: t("删除后列表不再展示，原始文件与产物文件保留在对象存储中。"),
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

  const handleDownloadPackage = useCallback(
    (record: WindDataPrepBatchSummary) => {
      void downloadFileWithAuth(
        `${API_BASE}/${record.id}/package`,
        `${record.name || "wind-data-prep"}-five-files.zip`,
      );
    },
    [],
  );

  const columns = useMemo<TableColumnsType<WindDataPrepBatchSummary>>(
    () => [
      {
        title: t("批次名称"),
        dataIndex: "name",
        key: "name",
        width: 220,
        render: (_value, record) => (
          <Space direction="vertical" size={0}>
            <Button
              type="link"
              style={{ padding: 0, height: "auto" }}
              onClick={() => openDetail(record.id, record.name || record.id)}
            >
              {record.name || record.id}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {record.wind_farm_name || "-"}
            </Text>
          </Space>
        ),
      },
      {
        title: t("风机数"),
        dataIndex: "turbine_count",
        key: "turbine_count",
        width: 90,
      },
      {
        title: t("网格"),
        key: "grid",
        width: 120,
        render: (_value, record) => `${record.grid_nx} × ${record.grid_ny}`,
      },
      {
        title: t("范围内落雷数"),
        dataIndex: "lightning_in_scope",
        key: "lightning_in_scope",
        width: 120,
        render: (value: number, record) => (
          <Tooltip title={`${t("雷电总数")} ${record.lightning_total} / ${t("有效")} ${record.lightning_valid}`}>
            <span>{value}</span>
          </Tooltip>
        ),
      },
      {
        title: t("产物齐全度"),
        key: "files_ready",
        width: 110,
        render: (_value, record) => (
          <Tag color={record.files_ready === 5 ? "success" : record.files_ready > 0 ? "warning" : "default"}>
            {record.files_ready}/5
          </Tag>
        ),
      },
      {
        title: t("S 基准值"),
        dataIndex: "risk_base_s",
        key: "risk_base_s",
        width: 100,
        render: (value: number) => formatNumber(value, 3),
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
              {value === "processing" || value === "pending" ? (
                <Progress percent={record.progress} size="small" showInfo={false} />
              ) : null}
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
        width: 150,
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
                onClick: () => openDetail(record.id, record.name || record.id),
              },
              {
                key: "log",
                label: t("日志"),
                icon: <FileTextOutlined />,
                visible: Boolean(canReadLogs && record.task_id),
                onClick: () =>
                  openLogViewer(record.task_id, t("任务执行日志"), record.name || record.id),
              },
              {
                key: "package",
                label: t("下载 zip"),
                icon: <DownloadOutlined />,
                visible: record.status === "completed",
                onClick: () => handleDownloadPackage(record),
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
    [canDelete, canReadLogs, openLogViewer, handleDelete, handleDownloadPackage, openDetail, t],
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

  const renderRecordCard = (record: WindDataPrepBatchSummary) => {
    const meta = STATUS_META[record.status] ?? STATUS_META.pending;
    return (
      <Card
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={() => openDetail(record.id, record.name || record.id)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <CloudUploadOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Tooltip title={record.name || record.id}>
                <Text strong className="truncate min-w-0">
                  {record.name || record.id}
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
              {t("风机数")}：{record.turbine_count} · {t("网格")}：{record.grid_nx} × {record.grid_ny}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("范围内落雷数")}：{record.lightning_in_scope}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("产物齐全度")}：{record.files_ready}/5 · {t("S 基准值")}：{formatNumber(record.risk_base_s, 3)}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("创建时间")}：{formatDateTime(record.create_date)}
            </Text>
            {record.status === "failed" && record.error_message ? (
              <Text type="danger" className="text-xs" ellipsis={{ tooltip: record.error_message }}>
                {record.error_message}
              </Text>
            ) : null}
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
                    openDetail(record.id, record.name || record.id);
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
                      openLogViewer(record.task_id, t("任务执行日志"), record.name || record.id);
                    }}
                  />
                </Tooltip>
              ) : null}
              <Dropdown
                menu={{
                  items: [
                    ...(record.status === "completed"
                      ? [
                          {
                            key: "package",
                            label: (
                              <Space size={4}>
                                <DownloadOutlined />
                                <span>{t("下载 zip")}</span>
                              </Space>
                            ),
                            onClick: (event) => {
                              event.domEvent.stopPropagation();
                              handleDownloadPackage(record);
                            },
                          },
                        ]
                      : []),
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

  if (initializing) return null;

  const wizardContent = (
    <>
      <Form<WizardValues> form={form} layout="vertical" initialValues={{ grid_step_deg: 0.01, risk_base_s: 1, terrain_mode: "zero" }}>
        <div className="fl-create-form-grid">
          <Form.Item label={t("批次名称")} name="name">
            <Input placeholder={t("留空时默认使用风电场名称或风机文件名")} maxLength={128} />
          </Form.Item>
          <Form.Item label={t("风电场名称")} name="wind_farm_name">
            <Input placeholder={t("例如：福建B1风电场")} maxLength={128} />
          </Form.Item>
          <Form.Item
            label={t("起始经度（0.01° 对齐）")}
            name="start_lon"
            rules={[{ required: true, message: t("请填写起始经度") }]}
            tooltip={t("必须是 0.01° 的整数倍，例如 119.34；P0.abc 头部以坐标×100 存为 2 字节整数")}
          >
            <InputNumber style={{ width: "100%" }} step={0.01} precision={6} placeholder="119.34" />
          </Form.Item>
          <Form.Item
            label={t("起始纬度（0.01° 对齐）")}
            name="start_lat"
            rules={[{ required: true, message: t("请填写起始纬度") }]}
            tooltip={t("起始经纬度必须是 0.01° 的整数倍（例如 119.34）")}
          >
            <InputNumber style={{ width: "100%" }} step={0.01} precision={6} placeholder="25.23" />
          </Form.Item>
          <Form.Item
            label={t("经向网格数 nx（≤100）")}
            name="grid_nx"
            rules={[{ required: true, message: t("请填写经向网格数") }]}
            tooltip={t("经向/纬向网格数必须在 1–100 之间（核心程序 NMAX=100）")}
          >
            <InputNumber min={1} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            label={t("纬向网格数 ny（≤100）")}
            name="grid_ny"
            rules={[{ required: true, message: t("请填写纬向网格数") }]}
            tooltip={t("经向/纬向网格数必须在 1–100 之间（核心程序 NMAX=100）")}
          >
            <InputNumber min={1} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item label={t("网格步长（度）")} name="grid_step_deg" tooltip={t("固定 0.01°，与核心程序一致")}>
            <InputNumber min={0.001} max={1} step={0.001} style={{ width: "100%" }} disabled />
          </Form.Item>
          <Form.Item label={t("风险基准 S")} name="risk_base_s" rules={[{ required: true, message: t("请填写风险基准 S") }]} tooltip={t("写入 file_1 头部的风险基准 S，必须大于 0")}>
            <InputNumber min={0.000001} style={{ width: "100%" }} step={0.1} />
          </Form.Item>
          <Form.Item label={t("统计年限")} tooltip={t("固定 6 年，与地闪密度模块一致；界面只读，实际时间跨度在预览中提示")}>
            <Input value="6" readOnly />
          </Form.Item>
          <Form.Item label={t("地形模式")} name="terrain_mode" tooltip={t("零高程：按研究区域生成全 0 的 P0.abc；上传 tif：需 EPSG:4326、0.01° 分辨率并覆盖研究区域")}>
            <Select
              options={[
                { label: t("零高程（按研究区域生成）"), value: "zero" },
                { label: t("上传 tif 地形"), value: "tif" },
              ]}
            />
          </Form.Item>
          <Form.Item className="fl-span-2" label={t("备注")} name="remark">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>

          <Form.Item className="fl-span-2" label={t("风机文件（file_2.txt 11 列 / Excel / DMS 合并 / 十进制）")} required>
            <Upload.Dragger
              accept=".txt,.csv,.xlsx,.xlsm"
              maxCount={1}
              fileList={turbineFiles}
              beforeUpload={() => false}
              onChange={({ fileList }) => setTurbineFiles(fileList.slice(-1))}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">{t("点击或拖拽风机文件到此区域")}</p>
              <p className="ant-upload-hint">{t("表格预览可在结果页查看每台风机高度/叶片长度/动静状态/回路号")}</p>
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
          <Form.Item className="fl-span-2" label={t("雷电 CSV（LONGITUDE / LATITUDE）")} required>
            <Upload.Dragger
              accept=".csv,.txt"
              maxCount={1}
              fileList={lightningFiles}
              beforeUpload={() => false}
              onChange={({ fileList }) => setLightningFiles(fileList.slice(-1))}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">{t("点击或拖拽雷电定位 CSV 到此区域")}</p>
              <p className="ant-upload-hint">{t("自动识别经纬度列，UTF-8 / GBK 兼容；不按 CG/IC/NB 筛选")}</p>
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
          {terrainMode === "tif" ? (
            <Form.Item className="fl-span-2" label={t("地形 tif（EPSG:4326、0.01° 分辨率、覆盖研究区域）")} required>
              <Upload.Dragger
                accept=".tif,.tiff"
                maxCount={1}
                fileList={terrainFiles}
                beforeUpload={() => false}
                onChange={({ fileList }) => setTerrainFiles(fileList.slice(-1))}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">{t("点击或拖拽 tif 地形到此区域")}</p>
                <p className="ant-upload-hint">{t("不做重采样；分辨率不符或未覆盖研究区域将直接阻断")}</p>
              </Upload.Dragger>
            </Form.Item>
          ) : null}
        </div>
      </Form>
    </>
  );

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
          <Button icon={<PlusOutlined />} type="primary" onClick={() => openWizard()}>
            {t("新建数据准备")}
          </Button>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("风电场数据准备")}</>,
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
                            description={t("暂无数据准备批次，点击「新建数据准备」上传风机与雷电数据")}
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
                  <Table<WindDataPrepBatchSummary>
                    rowKey="id"
                    size="middle"
                    loading={listQuery.isLoading || listQuery.isPlaceholderData}
                    columns={columns}
                    dataSource={records}
                    pagination={false}
                    scroll={{ x: 1240, y: tableScrollY }}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无数据准备批次，点击「新建数据准备」上传风机与雷电数据")}
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
        title={t("新建风电场数据准备")}
        width={760}
        open={wizardOpen}
        destroyOnHidden
        onCancel={() => setWizardOpen(false)}
        styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
        footer={
          <Space style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
            <Button onClick={() => setWizardOpen(false)}>{t("取消")}</Button>
            <Button type="primary" onClick={() => void handleSubmit()} loading={submitting}>
              {t("提交并生成")}
            </Button>
          </Space>
        }
      >
        {wizardContent}
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
