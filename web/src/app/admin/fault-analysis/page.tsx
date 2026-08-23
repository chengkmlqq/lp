"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Form,
  Modal,
  Progress,
  Segmented,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
  Input,
  Pagination,
  type MenuProps,
} from "antd";
import { MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { AnalysisCardList } from "@/components/fault-analysis/analysis-card-list";
import { AnalysisDetailView } from "@/components/fault-analysis/analysis-detail-view";
import { CreateAnalysisFormTab } from "@/components/fault-analysis/create-analysis-form-tab";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type {
  FaultAnalysisListResponse,
  FaultAnalysisCreateResponse,
  FaultAnalysisDetail,
} from "@/types/auth";
import type {
  FaultAnalysis,
  CreateFaultAnalysisFormValues,
  DetailTabItem,
} from "@/components/fault-analysis/types";

const { Text } = Typography;

/** 结果列表固定主 Tab（不可关闭），详情 Tab 依次追加在其后 */
const LIST_TAB_KEY = "list";
/** 新建表单固定 Tab key（唯一，重复点击去重） */
const CREATE_TAB_KEY = "create";
/** 编辑表单 Tab key 前缀：edit-{id}，按 id 去重 */
const EDIT_TAB_KEY_PREFIX = "edit-";

const FAULT_STATUS_META: Record<FaultAnalysis["status"], { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

const FAULT_RISK_META: Record<FaultAnalysis["risk_level"], { color: string; label: string }> = {
  low: { color: "success", label: "低风险" },
  medium: { color: "warning", label: "中风险" },
  high: { color: "error", label: "高风险" },
  critical: { color: "error", label: "严重" },
};

const FAULT_TABLE_MIN_SCROLL_Y = 180;
const FAULT_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const FAULT_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const FAULT_TABLE_BOTTOM_GAP = 8;

function formatNullable(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 90) return "#22C55E";
  if (confidence >= 70) return "#F97316";
  return "#EF4444";
}

/** Map backend FaultAnalysisSummary to the frontend FaultAnalysis type used by card components. */
function mapSummary(item: FaultAnalysisListResponse["items"][0]): FaultAnalysis {
  return {
    id: item.id,
    title: item.title ?? "",
    description: item.description ?? "",
    status: item.status as FaultAnalysis["status"],
    risk_level: item.risk_level as FaultAnalysis["risk_level"],
    tower_count: 0, // not stored in the current fault_analysis model
    line_name: item.line_name ?? "",
    fault_time: item.fault_time ?? "",
    fault_type: item.fault_type ?? "",
    confidence: item.confidence ?? 0,
    progress: item.progress ?? 0,
    created_at: item.create_date,
    updated_at: item.update_date,
    created_by: item.create_user ?? undefined,
  };
}

/** Build the scalar JSON body shared by create/edit requests. */
function buildFaultAnalysisBody(values: CreateFaultAnalysisFormValues): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (values.title) body.title = values.title;
  if (values.description) body.description = values.description;
  if (values.line_id) body.line_id = values.line_id;
  if (values.station_name) body.station = values.station_name;
  if (values.fault_time) body.fault_time = values.fault_time;
  if (values.fault_line_name) body.line_name = values.fault_line_name;
  if (values.fault_phase) body.fault_phase = values.fault_phase;
  if (values.fault_duration != null) body.fault_duration_ms = values.fault_duration;
  if (values.reclosure_status) body.reclosure_status = values.reclosure_status;
  if (values.fault_voltage != null) body.fault_voltage_v = values.fault_voltage;
  if (values.fault_current != null) body.fault_current_a = values.fault_current;
  if (values.max_zero_current != null) body.max_zero_current_a = values.max_zero_current;
  if (values.zero_compensation != null) body.zero_compensation = values.zero_compensation;
  if (values.fault_resistance != null) body.fault_resistance_ohm = values.fault_resistance;
  if (values.line_length != null) body.line_length_km = values.line_length;
  if (values.line_angle != null) body.line_angle_deg = values.line_angle;
  if (values.line_impedance != null) body.line_impedance_ohm = values.line_impedance;
  if (values.lightning_current) body.lightning_current_ka = parseFloat(values.lightning_current) || undefined;
  if (values.lightning_longitude != null) body.lightning_longitude = values.lightning_longitude;
  if (values.lightning_latitude != null) body.lightning_latitude = values.lightning_latitude;
  if (values.wave_distance != null) body.wave_distance_km = values.wave_distance;
  if (values.traveling_wave_distance != null) body.traveling_wave_distance_km = values.traveling_wave_distance;
  if (values.optical_position) body.optical_position = values.optical_position;
  if (values.optical_device_location) body.optical_device_location = values.optical_device_location;
  return body;
}

/** 从临时上传文件列表中提取首个已完成的 temp_file_id。 */
function pickTempFileId(list: { temp_file_id?: string; status?: string }[] | undefined): string | undefined {
  const item = list?.find((it) => it.temp_file_id);
  return item?.temp_file_id;
}

/** 从临时上传文件列表中提取所有已完成的 temp_file_id。 */
function pickTempFileIds(list: { temp_file_id?: string; status?: string }[] | undefined): string[] | undefined {
  const ids = list?.filter((it) => it.temp_file_id).map((it) => it.temp_file_id as string);
  return ids?.length ? ids : undefined;
}

/** 检查是否仍存在未完成上传的文件（提交前阻塞）。 */
function hasPendingUploads(files: { status?: string; temp_file_id?: string }[] | undefined): boolean {
  return (files ?? []).some((it) => it.status === "uploading" || (!it.temp_file_id && it.status !== "done"));
}

/** 创建请求是否携带判别输入文件（有文件时走 multipart 上传接口）。 */
function hasUploadFiles(values: CreateFaultAnalysisFormValues): boolean {
  return [
    values.wave_data_file,
    values.lightning_data_file,
    values.ledger_data_file,
    values.traveling_wave_file,
    values.optical_data_file,
  ].some((fileList) => (fileList?.length ?? 0) > 0);
}

export default function AdminFaultAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [tableScrollY, setTableScrollY] = useState(FAULT_TABLE_MIN_SCROLL_Y);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [messageApi, contextHolder] = message.useMessage();
  const [wsProgressMap, setWsProgressMap] = useState<Record<string, { progress: number; status: string; error?: string; step?: string }>>({});

  // 提交进行中的 Tab key 集合（LP-348：提交中禁止关闭对应表单 Tab）
  const [submittingTabKeys, setSubmittingTabKeys] = useState<Set<string>>(() => new Set());

  // closeTab 可能被 Tab 内回调（onSuccess/onLoadError）以较早的闭包触发，
  // 故用 ref 始终读取最新的 detailTabs/activeTabKey，避免关闭/回退位置错乱。
  const detailTabsRef = useRef(detailTabs);
  detailTabsRef.current = detailTabs;
  const activeTabKeyRef = useRef(activeTabKey);
  activeTabKeyRef.current = activeTabKey;
  const searchKeywordCacheRef = useRef(searchKeyword);
  searchKeywordCacheRef.current = searchKeyword;
  const wsProgressCacheRef = useRef(wsProgressMap);
  wsProgressCacheRef.current = wsProgressMap;

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage");

  const analysesQuery = useQuery({
    queryKey: ["/api/v1/fault-analysis", searchKeyword],
    enabled: !!user && canRead,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "100");
      if (searchKeyword.trim()) {
        params.set("keyword", searchKeyword.trim());
      }
      const response = await fetchWithAuth(`/api/v1/fault-analysis?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisListResponse;
    },
  });

  useTopicSubscription(
    "admin.fault-analysis",
    useCallback((event) => {
      const payload = (event?.payload ?? {}) as Record<string, unknown>;
      const analysisId = typeof payload.analysis_id === "string" ? payload.analysis_id : undefined;
      // 处理进度/开始/完成/失败事件时，直接用 WS 推送覆盖该条记录的实时进度，避免整表重渲染。
      if (
        event.name === "analysis.diagnosis_progress" ||
        event.name === "analysis.diagnosis_started" ||
        event.name === "analysis.diagnosis_completed" ||
        event.name === "analysis.diagnosis_failed"
      ) {
        if (analysisId) {
          const progress =
            event.name === "analysis.diagnosis_failed"
              ? 0
              : event.name === "analysis.diagnosis_completed"
                ? 100
                : Number(payload.progress);
          const status =
            event.name === "analysis.diagnosis_completed"
              ? "completed"
              : event.name === "analysis.diagnosis_failed"
                ? "failed"
                : typeof payload.status === "string" && payload.status
                  ? payload.status
                  : event.name === "analysis.diagnosis_started"
                    ? "processing"
                    : "processing";
          setWsProgressMap((previous) => ({
            ...previous,
            [analysisId]: {
              progress: Number.isNaN(progress) ? 0 : Math.max(0, Math.min(100, progress)),
              status,
              error: typeof payload.error === "string" ? payload.error : undefined,
              step: typeof payload.step === "string" ? payload.step : undefined,
            },
          }));
        }
        // 进度事件密集，只增量更新，不整表刷新
        void queryClient.setQueryData<FaultAnalysisListResponse>(["/api/v1/fault-analysis", searchKeywordCacheRef.current], (old) => {
          if (!old?.items) return old;
          return {
            ...old,
            items: old.items.map((item) => {
              if (item.id !== analysisId || !analysisId) return item;
              const meta = wsProgressCacheRef.current[analysisId];
              const progress = meta ? meta.progress : item.progress ?? 0;
              const status = meta ? meta.status : item.status;
              return { ...item, progress, status: status as typeof item.status };
            }),
          };
        });
      } else {
        void queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
      }
    }, [queryClient]),
  );

  const analyses = useMemo(
    () => (analysesQuery.data?.items ?? []).map(mapSummary).map((item) => {
      const meta = wsProgressMap[item.id];
      if (meta) {
        return {
          ...item,
          progress: meta.progress,
          status: meta.status as FaultAnalysis["status"],
        };
      }
      return item;
    }),
    [analysesQuery.data?.items, wsProgressMap],
  );
  const filteredAnalyses = useMemo(() => {
    if (!searchKeyword.trim()) {
      return analyses;
    }
    // Backend already filters by keyword; this is just in case we need client-side filtering
    return analyses;
  }, [analyses, searchKeyword]);

  const paginatedAnalyses = useMemo(() => {
    const start = (pagination.current - 1) * pagination.pageSize;
    const end = start + pagination.pageSize;
    return filteredAnalyses.slice(start, end);
  }, [filteredAnalyses, pagination]);

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorHeight = anchor.getBoundingClientRect().height;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? FAULT_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? FAULT_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - FAULT_TABLE_BOTTOM_GAP);
    const clampedHeight = Math.max(FAULT_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollHeight);
  }, [analysesQuery.error, analysesQuery.isFetching, filteredAnalyses.length, updateTableScrollHeight, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    if (viewMode !== "list") {
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
  }, [updateTableScrollHeight, viewMode]);

  // ---- LP-348: 新建/编辑表单改用动态选项卡 ----

  // 移除指定 Tab 并按「左邻 → 最左 → 列表主 Tab」回退 activeKey（与详情 Tab 关闭逻辑一致）。
  // 通过 ref 读取最新状态，兼容 Tab 内回调以较早闭包触发的场景。
  const closeTab = useCallback((tabKey: string) => {
    const previous = detailTabsRef.current;
    const removedIndex = previous.findIndex((tab) => tab.key === tabKey);
    const next = previous.filter((tab) => tab.key !== tabKey);
    setDetailTabs(next);
    if (activeTabKeyRef.current === tabKey) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, []);

  // 提交进行中的 Tab 状态（LP-348：提交中禁止关闭对应表单 Tab）。
  const setTabSubmitting = useCallback((tabKey: string, submitting: boolean) => {
    setSubmittingTabKeys((previous) => {
      const next = new Set(previous);
      if (submitting) {
        next.add(tabKey);
      } else {
        next.delete(tabKey);
      }
      return next;
    });
  }, []);

  // 新建提交请求（两段式：先传临时目录拿到 temp_file_id，提交时携带 ID 列表）。
  const submitCreate = useCallback(async (values: CreateFaultAnalysisFormValues) => {
    const body = buildFaultAnalysisBody(values);

    if (hasUploadFiles(values)) {
      if (hasPendingUploads(values.wave_data_file)
        || hasPendingUploads(values.lightning_data_file) || hasPendingUploads(values.ledger_data_file)
        || hasPendingUploads(values.traveling_wave_file) || hasPendingUploads(values.optical_data_file)) {
        throw new Error("仍有文件在上传中，请等待上传完成后提交");
      }

      const formData = new FormData();
      for (const [key, value] of Object.entries(body)) {
        if (value !== undefined) {
          formData.set(key, String(value));
        }
      }

      const fileFields: Array<[string, { temp_file_id?: string }[] | undefined]> = [
        ["wave_data_temp_file_id", values.wave_data_file],
        ["lightning_data_temp_file_id", values.lightning_data_file],
        ["ledger_data_temp_file_id", values.ledger_data_file],
        ["traveling_wave_temp_file_id", values.traveling_wave_file],
        ["optical_data_temp_file_id", values.optical_data_file],
      ];
      for (const [field, list] of fileFields) {
        if (field === "traveling_wave_temp_file_id") {
          const tempFileIds = pickTempFileIds(list);
          if (tempFileIds) {
            for (const tempFileId of tempFileIds) {
              formData.append(field, tempFileId);
            }
          }
          continue;
        }
        const tempFileId = pickTempFileId(list);
        if (tempFileId) {
          formData.set(field, tempFileId);
        }
      }

      const response = await fetchWithAuth("/api/v1/fault-analysis/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisCreateResponse;
    }

    const response = await fetchWithAuth("/api/v1/fault-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    return (await response.json()) as FaultAnalysisCreateResponse;
  }, [fetchWithAuth]);

  // 新建成功：刷新列表并关闭新建 Tab（回到列表）。
  const handleCreateSuccess = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
    closeTab(CREATE_TAB_KEY);
    messageApi.success("故障分析创建成功");
  }, [queryClient, closeTab, messageApi]);

  // 点击「新建分析」→ 打开/激活唯一的新建 Tab（固定 key "create"，重复点击去重）。
  const openCreateTab = useCallback(() => {
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === CREATE_TAB_KEY)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: CREATE_TAB_KEY,
          label: <span>新建故障分析</span>,
          closable: true,
          children: (
            <CreateAnalysisFormTab
              mode="create"
              submitRequest={submitCreate}
              onSuccess={handleCreateSuccess}
              onError={(error) => messageApi.error(error instanceof Error ? error.message : "创建失败")}
              onSubmittingChange={(submitting) => setTabSubmitting(CREATE_TAB_KEY, submitting)}
            />
          ),
        } satisfies DetailTabItem,
      ];
    });
    setActiveTabKey(CREATE_TAB_KEY);
  }, [submitCreate, handleCreateSuccess, setTabSubmitting, messageApi]);

  // --- Edit handlers ---

  // 更新提交请求（与改造前 updateMutation 行为一致）。
  const submitUpdate = useCallback(async (id: string, values: CreateFaultAnalysisFormValues) => {
    const body = buildFaultAnalysisBody(values);

    const response = await fetchWithAuth(`/api/v1/fault-analysis/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    return (await response.json()) as FaultAnalysisDetail;
  }, [fetchWithAuth]);

  // 更新成功：刷新列表并关闭对应编辑 Tab（回到列表）。
  const handleUpdateSuccess = useCallback(async (tabKey: string) => {
    await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
    closeTab(tabKey);
    messageApi.success("故障分析更新成功");
  }, [queryClient, closeTab, messageApi]);

  // 点击卡片/列表「编辑」→ 打开/激活编辑 Tab（key 用 edit-{id} 去重），
  // 表单内按 id 加载详情并预填（见 CreateAnalysisFormTab）。
  const handleEdit = useCallback((id: string, title?: string) => {
    const tabKey = `${EDIT_TAB_KEY_PREFIX}${id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: tabKey,
          label: <span>{title ? `编辑：${title}` : "编辑故障分析"}</span>,
          closable: true,
          children: (
            <CreateAnalysisFormTab
              mode="edit"
              editId={id}
              submitRequest={(values) => submitUpdate(id, values)}
              onSuccess={() => handleUpdateSuccess(tabKey)}
              onError={(error) => messageApi.error(error instanceof Error ? error.message : "更新失败")}
              onSubmittingChange={(submitting) => setTabSubmitting(tabKey, submitting)}
              onLoadError={() => closeTab(tabKey)}
            />
          ),
        } satisfies DetailTabItem,
      ];
    });
    setActiveTabKey(tabKey);
  }, [submitUpdate, handleUpdateSuccess, closeTab, setTabSubmitting, messageApi]);

  const handleDelete = useCallback((id: string) => {
    Modal.confirm({
      title: "确认删除",
      content: "确定要删除该故障分析记录吗？此操作不可撤销。",
      okText: "确认删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          const response = await fetchWithAuth(`/api/v1/fault-analysis/${id}`, {
            method: "DELETE",
          });
          if (!response.ok) {
            throw new Error(await readApiError(response));
          }
          await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
          messageApi.success("故障分析已删除");
        } catch (error) {
          messageApi.error(error instanceof Error ? error.message : "删除失败");
        }
      },
    });
  }, [fetchWithAuth, messageApi, queryClient]);

  // ---- LP-275: 动态详情选项卡 ----
  // 点击卡片「查看」时新增/激活对应详情 Tab；以分析 id 去重，
  // 同一分析反复点击不会叠加重复 Tab，便于多开对比。
  const openDetail = useCallback((record: { id: string; title?: string; fault_type?: string }, defaultView?: "report" | "process" | "artifacts") => {
    const tabKey = defaultView ? `${record.id}-${defaultView}` : record.id;
    const tabLabel = defaultView
      ? `${record.title || `故障分析 ${record.id.slice(0, 8)}`} - ${defaultView === "process" ? "计算过程" : defaultView === "artifacts" ? "产物" : "报告"}`
      : record.title || `故障分析 ${record.id.slice(0, 8)}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: tabKey,
          label: <span>{tabLabel}</span>,
          closable: true,
          children: (
            <AnalysisDetailView
              analysisId={record.id}
              tabKey={tabKey}
              defaultView={defaultView || "report"}
            />
          ),
        } satisfies DetailTabItem,
      ];
    });
    setActiveTabKey(tabKey);
  }, []);

  // 关闭 Tab：移除对应 tab，关闭的是当前激活 Tab 时按相邻回退规则切换 activeKey
  //（优先左邻，其次最左，兜底回列表主 Tab），与地闪密度统计/防雷分析页一致。
  const handleTabsEdit = useCallback((
    targetKey: ReactMouseEvent | ReactKeyboardEvent | string,
    action: "add" | "remove",
  ) => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    // LP-348：提交进行中的表单 Tab 禁止关闭，避免丢失已填内容。
    if (submittingTabKeys.has(key)) {
      return;
    }
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey, submittingTabKeys]);

  const columns = useMemo<ColumnsType<FaultAnalysis>>(
    () => [
      {
        title: "线路名称",
        dataIndex: "line_name",
        width: 160,
        ellipsis: true,
        render: (value: string) => formatNullable(value),
      },
      {
        title: "故障类型",
        dataIndex: "fault_type",
        width: 140,
        ellipsis: true,
        render: (value: string) => formatNullable(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 220,
        render: (value: FaultAnalysis["status"], row: FaultAnalysis) => {
          const meta = FAULT_STATUS_META[value] ?? { color: "default", label: value };
          const statusTag = <Tag color={meta.color}>{meta.label}</Tag>;
          const step = wsProgressMap[row.id]?.step;
          return (
            <Space size={6} direction="vertical" className="w-full" style={{ gap: 2 }}>
              <Space size={6}>
                {statusTag}
                {row.status === "processing" && (
                  <Progress percent={Math.round(row.progress)} size="small" style={{ width: 80 }} />
                )}
              </Space>
              {row.status === "processing" && step
                ? (
                    <Typography.Text type="secondary" className="text-xs block">
                      {step}
                    </Typography.Text>
                  )
                : null}
            </Space>
          );
        },
      },
      {
        title: "风险等级",
        dataIndex: "risk_level",
        width: 100,
        render: (value: FaultAnalysis["risk_level"]) => {
          const meta = FAULT_RISK_META[value] ?? { color: "default", label: value };
          return <Tag color={meta.color}>{meta.label}</Tag>;
        },
      },
      {
        title: "综合置信度",
        dataIndex: "confidence",
        width: 110,
        render: (value: number) => (
          <Text style={{ color: getConfidenceColor(value) }} strong>
            {value ?? 0}%
          </Text>
        ),
      },
      {
        title: "故障时间",
        dataIndex: "fault_time",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "操作",
        key: "actions",
        width: 180,
        fixed: "right",
        render: (_: unknown, row) => {
          // 统一 UI 规范：默认仅展示 2 个直接按钮（详情/计算过程），其余操作收进 ⋯ 三点下拉
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "artifacts",
              label: "产物",
              onClick: () => openDetail(row, "artifacts"),
            },
            ...(canManage
              ? [
                  {
                    key: "edit",
                    label: "编辑",
                    onClick: () => handleEdit(row.id, row.title),
                  },
                ]
              : []),
            {
              key: "delete",
              label: "删除",
              danger: true,
              onClick: () => handleDelete(row.id),
            },
          ];

          return (
            <Space wrap>
              <Button size="small" onClick={() => openDetail(row)}>
                详情
              </Button>
              <Button size="small" onClick={() => openDetail(row, "process")}>
                计算过程
              </Button>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, handleDelete, handleEdit, openDetail],
  );

  if (!initializing && !user) {
    return (
      <Alert
        type="warning"
        showIcon
        message="请先登录后查看故障分析。"
      />
    );
  }

  if (!initializing && !canRead) {
    return (
      <Alert
        type="error"
        showIcon
        message="当前账号缺少线路读取权限，无法查看故障分析。"
      />
    );
  }

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col">
        <Tabs
          type="editable-card"
          hideAdd
          activeKey={activeTabKey}
          onChange={setActiveTabKey}
          onEdit={handleTabsEdit}
          className="admin-fault-analysis-tabs"
          tabBarExtraContent={
            canManage ? (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={openCreateTab}
              >
                新建分析
              </Button>
            ) : null
          }
          items={[
            {
              key: LIST_TAB_KEY,
              label: <span className="admin-fault-analysis-tab-title">故障分析</span>,
              closable: false,
              children: (
                <div className="admin-fault-analysis-list-pane">
                  <div className="admin-filter-bar">
                    <Form layout="inline">
                      <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                        <Input
                          placeholder="搜索分析名称、线路名称或描述"
                          value={keywordInput}
                          onChange={(e) => setKeywordInput(e.target.value)}
                          allowClear
                          onPressEnter={() => {
                            setSearchKeyword(keywordInput);
                            setPagination((prev) => ({ ...prev, current: 1 }));
                            void queryClient.refetchQueries({ queryKey: ["/api/v1/fault-analysis"] });
                          }}
                        />
                      </Form.Item>
                      <Form.Item style={{ marginBottom: 0 }}>
                        <Button
                          htmlType="button"
                          icon={<SearchOutlined />}
                          onClick={() => {
                            setSearchKeyword(keywordInput);
                            setPagination((prev) => ({ ...prev, current: 1 }));
                            void queryClient.refetchQueries({ queryKey: ["/api/v1/fault-analysis"] });
                          }}
                          className="admin-search-btn"
                        >
                          查询
                        </Button>
                      </Form.Item>
                    </Form>
                    <Segmented
                      value={viewMode}
                      onChange={(value) => setViewMode(value as "card" | "list")}
                      options={[
                        { label: "卡片视图", value: "card" },
                        { label: "列表视图", value: "list" },
                      ]}
                    />
                  </div>

                  {analysesQuery.error && (
                    <Alert
                      type="error"
                      showIcon
                      message={
                        analysesQuery.error instanceof Error
                          ? analysesQuery.error.message
                          : "加载失败"
                      }
                    />
                  )}

                  {viewMode === "list" ? (
                    <div
                      ref={tableScrollAnchorRef}
                      className="admin-fault-analysis-table-anchor"
                      style={{ "--admin-fault-analysis-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                    >
                      <Table<FaultAnalysis>
                        rowKey={(row) => row.id}
                        columns={columns}
                        dataSource={filteredAnalyses}
                        loading={analysesQuery.isFetching}
                        tableLayout="fixed"
                        pagination={{
                          current: pagination.current,
                          pageSize: pagination.pageSize,
                          total: Math.max(filteredAnalyses.length, 1),
                          showSizeChanger: true,
                          pageSizeOptions: [6, 12, 24, 48],
                          showTotal: () => `共 ${filteredAnalyses.length} 条`,
                          hideOnSinglePage: false,
                          onChange: (page, pageSize) => {
                            setPagination({ current: page, pageSize });
                          },
                        }}
                        scroll={{ x: 1200, y: tableScrollY }}
                        locale={{
                          emptyText: (
                            <Empty
                              image={Empty.PRESENTED_IMAGE_SIMPLE}
                              description="暂无故障分析记录"
                            />
                          ),
                        }}
                      />
                    </div>
                  ) : (
                    <div className="admin-fault-analysis-card-view">
                      <div className="admin-fault-analysis-card-scroll">
                        <AnalysisCardList
                          analyses={paginatedAnalyses}
                          selectedId={null}
                          loading={analysesQuery.isLoading}
                          onView={(id) => {
                            const record = analyses.find((item) => item.id === id);
                            openDetail(record ?? { id });
                          }}
                          onProcess={(id) => {
                            const record = analyses.find((item) => item.id === id);
                            openDetail(record ?? { id }, "process");
                          }}
                          onArtifacts={(id) => {
                            const record = analyses.find((item) => item.id === id);
                            openDetail(record ?? { id }, "artifacts");
                          }}
                          onEdit={canManage ? handleEdit : undefined}
                          onDelete={canManage ? handleDelete : undefined}
                        />
                      </div>

                      <div className="admin-fault-analysis-pagination">
                        <Pagination
                          current={pagination.current}
                          pageSize={pagination.pageSize}
                          total={Math.max(filteredAnalyses.length, 1)}
                          onChange={(page, pageSize) => {
                            setPagination({ current: page, pageSize });
                          }}
                          showSizeChanger
                          showTotal={() => `共 ${filteredAnalyses.length} 条`}
                          pageSizeOptions={[6, 12, 24, 48]}
                        />
                      </div>
                    </div>
                  )}
                </div>
              ),
            },
            ...detailTabs,
          ]}
        />
      </div>
    </>
  );
}
