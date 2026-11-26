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
  type ReactNode,
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
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  type MenuProps,
  type TabsProps,
  type TableColumnsType,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileTextOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { WindTurbineCalcDetailView } from "@/components/wind-turbine-calc-detail-view";
import { getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcCreateResponse,
  WindTurbineCalcJobListResponse,
  WindTurbineCalcJobSummary,
} from "@/types/wind-turbine-calc";
import { DEFAULT_ANGLES, DEFAULT_RADII } from "@/types/wind-turbine-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

type DetailTabData = {
  key: string;
  title: string;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function parseNumberList(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((v) => v.trim())
    .filter(Boolean)
    .map(Number);
}

const WIND_MODELS_BASE = "/api/v1/wind-models";

/** 机组/叶片型号下拉项：value 用后端主键，hubHeight/bladeLength 为型号映射的数值。 */
type WindModelOption = {
  value: string;
  label: string;
  hubHeight?: number;
  bladeLength?: number;
};

function toFinitePositive(value: unknown): number | undefined {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num : undefined;
}

/**
 * 后端的列表响应可能是数组，也可能是 { items: [...] } 包装；两种都兼容。
 * 型号缺少可解析的映射数值时无法自动带出参数，直接排除，避免选中后表单为空。
 */
function toModelOptions(raw: unknown): WindModelOption[] {
  const container = raw as { items?: unknown } | null;
  const items = Array.isArray(raw) ? raw : Array.isArray(container?.items) ? container.items : [];
  return items.flatMap((item): WindModelOption[] => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const code = typeof record.code === "string" ? record.code : "";
    const name = typeof record.name === "string" ? record.name : "";
    const rawId = record.id ?? (code || name);
    const value = rawId === null || rawId === undefined ? "" : String(rawId);
    const label = name && code && name !== code ? `${name}（${code}）` : name || code;
    if (!value || !label) return [];
    const option: WindModelOption = {
      value,
      label,
      hubHeight: toFinitePositive(record.hub_height_m),
      bladeLength: toFinitePositive(record.blade_length_m),
    };
    return [option];
  });
}

async function fetchModelOptions(
  fetchWithAuth: (path: string, init?: RequestInit) => Promise<Response>,
  kind: "turbines" | "blades",
  metric: "hubHeight" | "bladeLength",
): Promise<WindModelOption[]> {
  const response = await fetchWithAuth(`${WIND_MODELS_BASE}/${kind}?enabled=true`);
  if (!response.ok) throw new Error(await readApiError(response));
  return toModelOptions(await response.json()).filter((option) => option[metric] !== undefined);
}

const WIND_TABLE_MIN_SCROLL_Y = 180;
const WIND_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const WIND_TABLE_BOTTOM_GAP = 8;

export default function WindTurbineCalcListPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_turbine_calc.read") || hasPermission("wind_turbine_calc.manage");
  const canManage = hasPermission("wind_turbine_calc.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");

  const [logOpen, setLogOpen] = useState(false);
  const [logTaskId, setLogTaskId] = useState<string | null>(null);
  const [logTitle, setLogTitle] = useState("");

  const openLogViewer = useCallback(
    (taskId: string | null | undefined, taskTitle: string) => {
      if (!taskId || !canReadLogs) {
        return;
      }
      setLogTaskId(taskId);
      setLogTitle(`${t("运行日志")} - ${taskTitle}`);
      setLogOpen(true);
    },
    [canReadLogs, t],
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
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  // 型号下拉与「手动输入参数」兜底：默认按型号带出 h/R，型号接口不可用时仍可手填提交。
  const [manualParams, setManualParams] = useState(false);
  const [turbineOptions, setTurbineOptions] = useState<WindModelOption[]>([]);
  const [bladeOptions, setBladeOptions] = useState<WindModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsFailed, setModelsFailed] = useState(false);

  useEffect(() => {
    if (!createOpen) return;
    let cancelled = false;
    setModelsLoading(true);
    void Promise.all([
      fetchModelOptions(fetchWithAuth, "turbines", "hubHeight"),
      fetchModelOptions(fetchWithAuth, "blades", "bladeLength"),
    ])
      .then(([turbines, blades]) => {
        if (cancelled) return;
        setTurbineOptions(turbines);
        setBladeOptions(blades);
        setModelsFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setTurbineOptions([]);
        setBladeOptions([]);
        setModelsFailed(true);
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [createOpen, fetchWithAuth]);

  useEffect(() => setPage(1), [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-turbine-calc", keyword, statusFilter, page, pageSize],
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
      return getJson<WindTurbineCalcJobListResponse>(`${API_BASE}?${params.toString()}`);
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
    void queryClient.invalidateQueries({ queryKey: ["wind-turbine-calc"] });
  }, [queryClient]);

  const openDetail = useCallback((jobId: string, title: string) => {
    setDetailTabsData((previous) =>
      previous.some((tab) => tab.key === jobId) ? previous : [...previous, { key: jobId, title }],
    );
    setActiveTabKey(jobId);
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
      if (action !== "remove") return;
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
        children: <WindTurbineCalcDetailView jobId={tab.key} />,
      })),
    [detailTabsData],
  );

  const openCreate = useCallback(() => {
    form.resetFields();
    setManualParams(false);
    form.setFieldsValue({
      name: "",
      turbine_model: undefined,
      blade_model: undefined,
      hub_height: undefined,
      receptor_radii: DEFAULT_RADII.join(", "),
      blade_length: undefined,
      start_current: 1,
      angle_list: DEFAULT_ANGLES.join(", "),
    });
    setCreateOpen(true);
  }, [form]);

  const handleManualParamsChange = useCallback(
    (checked: boolean) => {
      setManualParams(checked);
      if (checked) {
        // 手填模式清空型号选择，数值保留为可编辑起点（未带出时给回原默认值）。
        const currentHubHeight = form.getFieldValue("hub_height");
        form.setFieldsValue({
          turbine_model: undefined,
          blade_model: undefined,
          hub_height: currentHubHeight ?? 105.5,
        });
      } else {
        // 回到型号模式时清空数值，必须重新选择型号带出。
        form.setFieldsValue({ hub_height: undefined, blade_length: undefined });
      }
    },
    [form],
  );

  const handleTurbineModelChange = useCallback(
    (value: string | undefined) => {
      const option = turbineOptions.find((item) => item.value === value);
      form.setFieldsValue({ hub_height: option?.hubHeight });
    },
    [form, turbineOptions],
  );

  const handleBladeModelChange = useCallback(
    (value: string | undefined) => {
      const option = bladeOptions.find((item) => item.value === value);
      form.setFieldsValue({ blade_length: option?.bladeLength });
    },
    [bladeOptions, form],
  );

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    const radii = parseNumberList(values.receptor_radii);
    const angles = parseNumberList(values.angle_list);
    if (radii.length === 0) {
      message.error(t("接闪器径向位置不能为空"));
      return;
    }
    if (angles.length === 0 || angles.length > 36) {
      message.error(t("旋转角数量须在 1~36 之间"));
      return;
    }

    // 二选一校验：型号模式按映射取值，手填模式取输入值；最终 h/R 必须是有限正数。
    let hubHeight: number | undefined;
    let bladeLength: number | null = null;
    if (manualParams) {
      hubHeight = toFinitePositive(values.hub_height);
      bladeLength = values.blade_length === undefined || values.blade_length === null
        ? null
        : toFinitePositive(values.blade_length) ?? null;
      if (values.blade_length !== undefined && values.blade_length !== null && bladeLength === null) {
        message.error(t("R 必须为有限正数"));
        return;
      }
      if (hubHeight === undefined) {
        message.error(t("h 必须为有限正数"));
        return;
      }
    } else {
      const turbine = turbineOptions.find((item) => item.value === values.turbine_model);
      const blade = bladeOptions.find((item) => item.value === values.blade_model);
      if (!turbine) {
        message.error(t("请选择机组型号"));
        return;
      }
      if (!blade) {
        message.error(t("请选择叶片型号"));
        return;
      }
      hubHeight = turbine.hubHeight;
      bladeLength = blade.bladeLength ?? null;
      if (hubHeight === undefined) {
        message.error(t("h 必须为有限正数"));
        return;
      }
      if (bladeLength === null) {
        message.error(t("R 必须为有限正数"));
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        name: values.name || "",
        hub_height: hubHeight,
        receptor_radii: radii,
        blade_length: bladeLength,
        start_current: Number(values.start_current),
        angle_list: angles,
      };
      const response = await fetchWithAuth(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindTurbineCalcCreateResponse;
      message.success(t("已提交单风机计算任务"));
      setCreateOpen(false);
      refreshList();
      openDetail(result.job_id, (values.name || "").trim() || t("未命名任务"));
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [bladeOptions, fetchWithAuth, form, manualParams, message, openDetail, refreshList, t, turbineOptions]);

  const handleCancel = useCallback(
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("取消该计算任务？"),
        content: t("取消会真正终止 MATLAB Runtime 进程组，已产生的结果不会保留。"),
        okText: t("取消任务"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}/cancel`, { method: "POST" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已发送取消请求"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const handleDelete = useCallback(
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("删除该计算任务？"),
        content: t("删除后不可恢复。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}`, { method: "DELETE" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已删除"));
          closeDetailTab(record.id);
          refreshList();
        },
      });
    },
    [closeDetailTab, fetchWithAuth, message, modal, refreshList, t],
  );

  const handleExportCsv = useCallback((record: WindTurbineCalcJobSummary) => {
    window.location.href = `${API_BASE}/${record.id}/export?type=csv`;
  }, []);

  const columns = useMemo<TableColumnsType<WindTurbineCalcJobSummary>>(
    () => [
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        width: 200,
        // 超长任务名省略收尾 + 悬浮显示全名，避免压到相邻「参数摘要」列（参考线路管理页）。
        ellipsis: { showTitle: true },
        render: (_value, record) => {
          const label = record.name || t("未命名任务");
          return (
            <Tooltip title={label}>
              <Button
                type="link"
                style={{
                  padding: 0,
                  height: "auto",
                  maxWidth: "100%",
                  display: "inline-block",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  verticalAlign: "bottom",
                }}
                onClick={() => openDetail(record.id, label)}
              >
                {label}
              </Button>
            </Tooltip>
          );
        },
      },
      {
        title: t("参数摘要"),
        key: "params",
        render: (_: unknown, record) => (
          <div style={{ fontSize: 12, lineHeight: 1.5 }}>
            <div>
              {t("轮毂高度")} {record.hub_height} · {t("叶片长度")} {record.blade_length} · {t("起始雷电流")} {record.start_current}
            </div>
            {record.turbine_model_name || record.blade_model_name ? (
              <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
                {t("机组型号")} {record.turbine_model_name || "-"} · {t("叶片型号")} {record.blade_model_name || "-"}
              </Text>
            ) : null}
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              {t("接闪器径向位置")}：[{record.receptor_radii?.join(", ")}]
            </Text>
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              {t("旋转角")}：[{record.angle_list?.join(", ")}]
            </Text>
          </div>
        ),
      },
      {
        title: t("平均失效率"),
        dataIndex: "mean_failure_rate",
        key: "mean_failure_rate",
        render: (v: number | null) => (v === null ? "-" : v.toExponential(9)),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        render: (status: string, record) => (
          <Space direction="vertical" size={0}>
            <Tag color={STATUS_META[status]?.color ?? "default"}>{STATUS_META[status]?.label ?? status}</Tag>
            {(record.status === "processing" || record.status === "pending") && (
              <Progress percent={record.progress} size="small" style={{ width: 90 }} showInfo={false} />
            )}
          </Space>
        ),
      },
      {
        title: t("耗时"),
        dataIndex: "duration_seconds",
        key: "duration_seconds",
        render: (v: number | null) => formatDuration(v),
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        render: (v: string | null) => formatDateTime(v),
      },
      {
        title: t("操作"),
        key: "actions",
        fixed: "right",
        render: (_: unknown, record) => {
          const active = record.status === "processing" || record.status === "pending";
          const label = record.name || t("未命名任务");
          return (
            <ModoActionGroup
              actions={[
                { key: "detail", label: t("详情"), icon: <EyeOutlined />, onClick: () => openDetail(record.id, label) },
                ...(canReadLogs && record.task_id
                  ? [{
                      key: "log",
                      label: t("日志"),
                      icon: <FileTextOutlined />,
                      onClick: () => openLogViewer(record.task_id, label),
                    }]
                  : []),
                { key: "export", label: t("导出"), icon: <DownloadOutlined />, onClick: () => handleExportCsv(record) },
                ...(active && canManage
                  ? [{
                      key: "cancel",
                      label: t("取消"),
                      icon: <StopOutlined />,
                      danger: true,
                      onClick: () => handleCancel(record),
                    }]
                  : []),
                ...(!active && canManage
                  ? [{
                      key: "delete",
                      label: t("删除"),
                      icon: <DeleteOutlined />,
                      danger: true,
                      onClick: () => handleDelete(record),
                    }]
                  : []),
              ]}
            />
          );
        },
      },
    ],
    [canManage, canReadLogs, handleCancel, handleDelete, handleExportCsv, openDetail, openLogViewer, t],
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

  const renderRecordCard = (record: WindTurbineCalcJobSummary) => {
    const meta = STATUS_META[record.status] ?? STATUS_META.pending;
    const active = record.status === "processing" || record.status === "pending";
    const title = record.name || t("未命名任务");
    const taskId = record.task_id;
    const canLog = canReadLogs && Boolean(taskId);

    // 卡片操作最多平铺两个图标按钮：详情固定第一，第二位按状态取最相关动作，
    // 其余收进「更多」下拉（参考风电场计算 / 线路管理卡片范式）。
    type CardAction = {
      key: string;
      label: string;
      icon: ReactNode;
      danger?: boolean;
      onClick: () => void;
    };
    const candidateActions: CardAction[] = [
      {
        key: "detail",
        label: t("详情"),
        icon: <EyeOutlined />,
        onClick: () => openDetail(record.id, title),
      },
      ...(canLog && taskId
        ? [
            {
              key: "log",
              label: t("运行日志"),
              icon: <FileTextOutlined />,
              onClick: () => openLogViewer(taskId, title),
            },
          ]
        : []),
      {
        key: "export",
        label: t("导出 CSV"),
        icon: <DownloadOutlined />,
        onClick: () => handleExportCsv(record),
      },
      ...(active && canManage
        ? [
            {
              key: "cancel",
              label: t("取消"),
              icon: <StopOutlined />,
              danger: true,
              onClick: () => handleCancel(record),
            },
          ]
        : []),
      ...(!active && canManage
        ? [
            {
              key: "delete",
              label: t("删除"),
              icon: <DeleteOutlined />,
              danger: true,
              onClick: () => handleDelete(record),
            },
          ]
        : []),
    ];
    const preferredKey =
      record.status === "failed"
        ? "log"
        : record.status === "completed"
          ? "export"
          : active
            ? "cancel"
            : undefined;
    const rank = (key: string) => (key === "detail" ? 0 : key === preferredKey ? 1 : 2);
    const actions = [...candidateActions].sort((a, b) => rank(a.key) - rank(b.key));
    const primaryActions = actions.slice(0, 2);
    const overflowActions = actions.slice(2);
    const overflowMenuItems: MenuProps["items"] = overflowActions.map((action) => ({
      key: action.key,
      label: action.label,
      icon: action.icon,
      danger: action.danger,
      onClick: (info) => {
        info.domEvent?.stopPropagation();
        action.onClick();
      },
    }));

    return (
      <Card
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={() => openDetail(record.id, title)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Tooltip title={title}>
                <Text strong className="truncate min-w-0">
                  {title}
                </Text>
              </Tooltip>
              <Tag color={meta.color} style={{ marginInlineEnd: 0, flexShrink: 0 }}>
                {t(meta.label)}
              </Tag>
            </div>
          </div>

          <div className="flex flex-col gap-1 px-4 py-3">
            <Text type="secondary" className="text-xs">
              {t("轮毂高度")} {record.hub_height} · {t("叶片长度")} {record.blade_length} · {t("起始雷电流")} {record.start_current}
            </Text>
            {record.turbine_model_name || record.blade_model_name ? (
              <Text type="secondary" className="text-xs">
                {t("机组型号")} {record.turbine_model_name || "-"} · {t("叶片型号")} {record.blade_model_name || "-"}
              </Text>
            ) : null}
            <Text type="secondary" className="text-xs">
              {t("角度数")}：{record.angle_count} · {t("接闪器径向位置")}：[{record.receptor_radii?.join(", ")}]
            </Text>
            <Text type="secondary" className="text-xs">
              {t("耗时")}：{formatDuration(record.duration_seconds)} · {t("创建时间")}：{formatDateTime(record.create_date)}
            </Text>
          </div>

          <div className="admin-lightning-distribution-event-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {active ? <Progress percent={record.progress} size="small" className="flex-1 max-w-40" /> : <div />}
            <Space size="small" className="flex-wrap">
              {primaryActions.map((action) => (
                <Tooltip key={action.key} title={action.label}>
                  <Button
                    type="text"
                    size="small"
                    danger={action.danger}
                    icon={action.icon}
                    onClick={(event) => {
                      event.stopPropagation();
                      action.onClick();
                    }}
                  />
                </Tooltip>
              ))}
              {overflowActions.length > 0 ? (
                <Dropdown menu={{ items: overflowMenuItems }} trigger={["click"]}>
                  <Tooltip title={t("更多操作")}>
                    <Button
                      type="text"
                      size="small"
                      icon={<MoreOutlined />}
                      onClick={(event) => {
                        event.stopPropagation();
                      }}
                    />
                  </Tooltip>
                </Dropdown>
              ) : null}
            </Space>
          </div>
        </div>
      </Card>
    );
  };

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
          canManage && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {t("新建计算")}
            </Button>
          )
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("单风机计算")}</>,
            closable: false,
            children: (
              <div className="modo-page-card admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("搜索任务名称 / ID")}
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={() => setKeyword(keywordInput.trim())}
                      />
                    </Form.Item>
                    <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={(value) => setStatusFilter(value)}
                        options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: t(meta.label) }))}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Space>
                        <Button icon={<SearchOutlined />} onClick={() => setKeyword(keywordInput.trim())}>
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
                            description={t("暂无计算任务，点击「新建计算」提交单风机计算")}
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
                  <Table<WindTurbineCalcJobSummary>
                    rowKey="id"
                    size="middle"
                    loading={listQuery.isLoading || listQuery.isPlaceholderData}
                    columns={columns}
                    dataSource={records}
                    pagination={false}
                    scroll={{ x: 1040, y: tableScrollY }}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无计算任务，点击「新建计算」提交单风机计算")}
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
        open={createOpen}
        title={t("新建单风机计算")}
        onCancel={() => setCreateOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={t("提交")}
        cancelText={t("取消")}
        width={520}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label={t("任务名称")}
            name="name"
            tooltip={t("可选，留空时使用默认名称")}
          >
            <Input placeholder={t("可选")} />
          </Form.Item>
          <Form.Item
            label={t("手动输入参数")}
            tooltip={t("默认按机组型号/叶片型号自动带出轮毂高度与叶片长度；需要自定义数值时开启")}
          >
            <Space>
              <Switch checked={manualParams} onChange={handleManualParamsChange} />
              <Text type="secondary">
                {manualParams
                  ? t("手动填写轮毂高度与叶片长度")
                  : t("按机组型号与叶片型号自动带出")}
              </Text>
            </Space>
          </Form.Item>
          {!manualParams && (
            <>
              <Form.Item
                label={t("机组型号")}
                name="turbine_model"
                tooltip={t("选择机组型号后自动带出轮毂高度")}
                rules={[{ required: true, message: t("请选择机组型号") }]}
              >
                <Select
                  showSearch
                  allowClear
                  loading={modelsLoading}
                  optionFilterProp="label"
                  placeholder={t("请选择机组型号")}
                  options={turbineOptions.map((item) => ({ value: item.value, label: item.label }))}
                  notFoundContent={modelsLoading ? <Spin size="small" /> : t("暂无可用机组型号")}
                  onChange={handleTurbineModelChange}
                />
              </Form.Item>
              <Form.Item
                label={t("叶片型号")}
                name="blade_model"
                tooltip={t("选择叶片型号后自动带出叶片长度")}
                rules={[{ required: true, message: t("请选择叶片型号") }]}
              >
                <Select
                  showSearch
                  allowClear
                  loading={modelsLoading}
                  optionFilterProp="label"
                  placeholder={t("请选择叶片型号")}
                  options={bladeOptions.map((item) => ({ value: item.value, label: item.label }))}
                  notFoundContent={modelsLoading ? <Spin size="small" /> : t("暂无可用叶片型号")}
                  onChange={handleBladeModelChange}
                />
              </Form.Item>
              {modelsFailed ? (
                <Form.Item style={{ marginBottom: 12 }}>
                  <Text type="warning">{t("型号数据加载失败，可开启「手动输入参数」继续填写")}</Text>
                </Form.Item>
              ) : null}
            </>
          )}
          <Form.Item
            label={t("轮毂高度 h (m)")}
            name="hub_height"
            tooltip={manualParams ? t("轮毂高度，单位 m，必须大于 0") : t("由所选机组型号自动带出")}
            rules={manualParams
              ? [{ required: true, message: t("请输入轮毂高度") }, { type: "number", min: 0.0001, message: t("h 必须大于 0") }]
              : []}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={0.0001}
              step={0.1}
              disabled={!manualParams}
              placeholder={manualParams ? undefined : t("选择机组型号后自动带出")}
            />
          </Form.Item>
          <Form.Item
            label={t("接闪器径向位置 r_list (m)")}
            name="receptor_radii"
            tooltip={t("逗号分隔，须严格递增；0 < r ≤ R")}
            rules={[{ required: true, message: t("请输入接闪器径向位置") }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t("叶片长度 R (m)")}
            name="blade_length"
            tooltip={manualParams ? t("留空则取 max(r_list)") : t("由所选叶片型号自动带出")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={0.0001}
              step={0.1}
              disabled={!manualParams}
              placeholder={manualParams ? undefined : t("选择叶片型号后自动带出")}
            />
          </Form.Item>
          <Form.Item
            label={t("起始雷电流 Ic (kA)")}
            name="start_current"
            tooltip={t("起始雷电流，单位 kA，必须大于 0")}
            rules={[{ required: true, message: t("请输入起始雷电流") }, { type: "number", min: 0.0001, message: t("Ic 必须大于 0") }]}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("旋转角列表 (deg)")}
            name="angle_list"
            tooltip={t("逗号分隔，最多 36 个，默认 0–110 步长 10；角度击距公式只在 0–90° 拟合，其余姿态按外推处理")}
            rules={[{ required: true, message: t("请输入旋转角列表") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <TaskLogViewerDrawer
        taskId={logTaskId}
        title={logTitle || t("运行日志")}
        open={logOpen}
        onClose={() => setLogOpen(false)}
        variant="drawer"
      />
    </div>
  );
}
