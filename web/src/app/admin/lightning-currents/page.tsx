"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Badge,
  Button,
  DatePicker,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip as AntTooltip,
  Typography,
  Upload,
} from "antd";
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  HistoryOutlined,
  InboxOutlined,
  MoreOutlined,
  NodeIndexOutlined,
  NumberOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SendOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import dynamic from "next/dynamic";

// recharts（约 400KB）按需加载：仅当打开详情且存在多回击数据时才下载图表库
const MultiReturnPeakChart = dynamic(() => import("@/components/lightning-currents/multi-return-peak-chart"), {
  ssr: false,
  loading: () => <div style={{ height: 320 }} />,
});

import { useI18n } from "@/lib/i18n";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { LightningCurrentBackfillHistoryTable } from "@/components/lightning-current-backfill-history";
import { Card } from "@/components/ui-antd";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { ApiError, downloadFileWithAuth, getApiBaseUrl, readApiError } from "@/lib/api";
import type {
  LightningAmplitudeBackfillLine,
  LightningAmplitudeBackfillLineListResponse,
  LightningAmplitudeImportResponse,
  LightningAmplitudeListResponse,
  LightningAmplitudeRecord,
  LightningAmplitudeStatusResponse,
  LightningAmplitudeUpdateRequest,
  LightningCurrentPreparationAsyncResponse,
  LightningTempUploadResponse,
  LightningPolarity,
} from "@/types/auth";
import { CHINESE_CITIES, type CityOption } from "@/data/chinese-cities";

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

type ImportFormValues = {
  sample_interval_us: number | null;
  city: string;
  location_tag: string;
  event_time: dayjs.Dayjs | null;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  sample_interval_us: 1,
  city: "",
  location_tag: "",
  event_time: null,
};

const STATUS_META: Record<string, { color: "default" | "processing" | "success" | "error" | "warning"; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "导入中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

function formatNullable(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
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

function formatPolarity(polarity: LightningPolarity, t: (s: string) => string): string {
  if (polarity === "positive") return t("正极性");
  if (polarity === "negative") return t("负极性");
  if (polarity === "mixed") return t("混合");
  return t("未知");
}

function truncateFileName(name: string, maxLength = 20, t: (s: string) => string): string {
  if (!name) {
    return t("未命名");
  }
  return name.length > maxLength ? `${name.slice(0, maxLength)}…` : name;
}

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const LIGHTNING_TABLE_BOTTOM_GAP = 8;

export default function AdminLightningCurrentsPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth, getAccessToken } = useAuth();
  const { modal: modalApi, message: messageApi } = App.useApp();
  const queryClient = useQueryClient();
  const [importForm] = Form.useForm<ImportFormValues>();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [backfillLinesOpen, setBackfillLinesOpen] = useState(false);
  const [backfillLinesRecord, setBackfillLinesRecord] = useState<LightningAmplitudeRecord | null>(null);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");

  // ---- 任务日志弹窗 ----
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logModalTaskId, setLogModalTaskId] = useState<string | null>(null);
  const [logModalTitle, setLogModalTitle] = useState(t("任务执行日志"));

  // ---- 编辑弹窗 ----
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editRecord, setEditRecord] = useState<LightningAmplitudeRecord | null>(null);
  const [editForm] = Form.useForm<ImportFormValues>();

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const openLogViewer = (taskId: string | null | undefined, label: string, fileName: string) => {
    if (!taskId || !canReadLogs) {
      return;
    }
    setLogModalTaskId(taskId);
    setLogModalTitle(`${label} - ${fileName}`);
    setLogModalOpen(true);
  };

  const trimmedKeyword = searchKeyword.trim();
  const listParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, trimmedKeyword]);
  const listPath = `/api/v1/lightning-currents/amplitudes?${listParams}`;

  const recordsQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    refetchInterval: false,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeListResponse;
    },
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);

  const listError = useMemo<ApiError | null>(() => recordsQuery.error instanceof Error ? new ApiError(recordsQuery.error.message) : null, [recordsQuery.error]);

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

  const refreshAll = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lightning-currents"),
    });
  }, [queryClient]);

  useTopicSubscription(
    "admin.lightning-amplitude",
    useCallback((event) => {
      const name = event.name;
      const payload = event.payload as {
        amplitude_id?: string;
        progress?: number;
        status?: string;
        error?: string;
        sample_count?: number;
        peak_abs_current_ka?: number;
      };
      if (name === "amplitude.import_started") {
        void refreshAll();
      } else if (name === "amplitude.import_progress") {
        void refreshAll();
      } else if (name === "amplitude.import_completed") {
        setSuccess(
          payload?.sample_count != null
            ? `${t("导入完成")}：${t("采样点")} ${payload.sample_count} ${t("个")}，${t("峰值")} ${formatNumber(payload.peak_abs_current_ka, 2)}kA`
            : t("导入完成"),
        );
        void refreshAll();
      } else if (name === "amplitude.import_failed") {
        setError(new ApiError(payload?.error || t("导入失败，请在列表中对失败记录执行重试")));
        void refreshAll();
      } else {
        void refreshAll();
      }
    }, [refreshAll]),
  );

  useTopicSubscription(
    "admin.lightning-current-backfill",
    useCallback((event) => {
      const name = event.name;
      const payload = event.payload as {
        backfill_task_id?: string;
        line_id?: string;
        task_id?: string;
        status?: string;
        progress?: number;
        error?: string;
        updated_tower_count?: number;
        sampled_event_count?: number;
        warning_count?: number;
        current_a?: number;
        current_b?: number;
      };
      if (name === "backfill.completed") {
        if (payload.sampled_event_count != null) {
          setSuccess(
            `${t("回填完成")}：${t("峰值")} A=${formatNumber(payload.current_a, 2)}kA，B=${formatNumber(payload.current_b, 2)}kA，${t("采样点")} ${payload.sampled_event_count} ${t("个")}`,
          );
        } else {
          setSuccess(t("回填完成"));
        }
        void refreshAll();
      } else if (name === "backfill.failed") {
        setError(new ApiError(payload?.error || t("线路回填失败")));
        void refreshAll();
      } else if (name === "backfill.started") {
        void refreshAll();
      } else {
        void refreshAll();
      }
    }, [refreshAll]),
  );

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    // 以可滚动容器（列表面板）的 padding-box 底边为准（LP-322 与线路管理页对齐）：
    // 用 window.innerHeight 会漏掉面板底部 padding 与页面底边距 → 表体过高，
    // 把列表分页的 margin-bottom 8px 挤溢出（实测溢出 7px）。2026-09-12 修复 + 2026-09-25 对齐
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-lightning-currents-list-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available = containerRect.bottom - containerPadBottom - anchorTop - LIGHTNING_TABLE_BOTTOM_GAP;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);

    const clampedHeight = Math.max(LIGHTNING_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [records.length, recordsQuery.isFetching, updateTableScrollY, viewMode]);

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
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollY, viewMode, records.length, recordsQuery.isFetching]);

  // 导入中进度直接通过订阅消息 + 表格“状态”列展示，不弹进度条轮询弹窗

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) {
        throw new Error(t("缺少 lightning.manage 权限"));
      }
      if (!tempFileId) {
        throw new Error(t("文件尚未上传完成，请等待上传后再确认导入"));
      }
      const values = importForm.getFieldsValue(true);
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      if (values.sample_interval_us !== null && values.sample_interval_us !== undefined) {
        formData.append("sample_interval_us", String(values.sample_interval_us));
      }
      if (values.city?.trim()) formData.append("city", values.city.trim());
      if (values.location_tag?.trim()) formData.append("location_tag", values.location_tag.trim());
      if (values.event_time) {
        const dt = values.event_time.format("YYYY-MM-DDTHH:mm:ss");
        if (dt) formData.append("event_time", dt);
      }

      const response = await fetchWithAuth("/api/v1/lightning-currents/import-async", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeImportResponse;
    },
    onSuccess: async (payload) => {
      setError(null);
      setSuccess(`${t("导入任务已提交（任务ID")}: ${payload.task_id}），${t("正在后台处理")}`);
      setImportModalOpen(false);
      importForm.resetFields();
      setSelectedFile(null);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : t("导入失败")));
    },
  });

  const handleTempUpload = useCallback(
    (file: File) => {
      setSelectedFile(file);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

      // 上传后立即做格式快速校验：雷电流幅值文件每行应为 1 个电流值，或「时间 电流」两列。
      // 检查前 20 行统计有效比例（<50% 才提示），避免首行是表头/注释的正常文件被误拦。
      let formatInvalid = false;
      const reader = new FileReader();
      reader.onload = () => {
        const head = String(reader.result ?? "").slice(0, 2000);
        const lines = head.split(/\r?\n/).map((ln) => ln.trim()).filter(Boolean).slice(0, 20);
        if (lines.length === 0) {
          return;
        }
        const valid = lines.filter((ln) => {
          const tokens = ln.split(/[\s,，]+/).filter(Boolean);
          const numbers = tokens.map(Number).filter((n) => Number.isFinite(n));
          return tokens.length >= 1 && numbers.length >= 1;
        }).length;
        if (valid / lines.length < 0.5) {
          formatInvalid = true;
          const badSample = lines.find((ln) => {
            const tokens = ln.split(/[\s,，]+/).filter(Boolean);
            const numbers = tokens.map(Number).filter((n) => Number.isFinite(n));
            return tokens.length < 1 || numbers.length < 1;
          }) ?? lines[0];
          setUploadError(
            `${t("文件格式疑似有误")}：${t("前")} ${lines.length} ${t("行仅")} ${valid} ${t("行可解析")}（${t("如")}「${badSample.slice(0, 80)}」）。` +
              t("雷电流幅值文件每行应为 1 个电流值（如「-15.3」），或「时间 电流」两列（如「0.0001 -15.3」）。"),
          );
        }
      };
      reader.readAsText(file);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getApiBaseUrl()}/api/v1/lightning-currents/upload-temp`);
      xhr.withCredentials = true;
      const token = getAccessToken();
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
        if (!event.lengthComputable || event.total <= 0) {
          return;
        }
        const percent = Math.min(99, Math.max(0, Math.round((event.loaded / event.total) * 100)));
        setUploadProgress(percent);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setUploadProgress(100);
          // 前端格式校验失败则不接受该临时文件（禁止提交导入）
          if (formatInvalid) {
            setTempFileId(null);
            return;
          }
          try {
            const payload = JSON.parse(xhr.responseText) as LightningTempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError(t("上传成功但响应解析失败，请重新选择文件"));
          }
          return;
        }
        let message = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) message = parsed.detail;
        } catch {
          // 忽略非 JSON 响应
        }
        setUploadError(message);
      };
      xhr.onerror = () => setUploadError(t("网络异常，上传失败"));
      xhr.onabort = () => setUploadError(t("上传已取消"));

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [getAccessToken],
  );

  const deleteMutation = useMutation({
    mutationFn: async (record: LightningAmplitudeRecord) => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${record.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return record.id;
    },
    onSuccess: async () => {
      setError(null);
      setSuccess(t("雷电流幅值记录已删除"));
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : t("删除失败")));
    },
  });

  const retryMutation = useMutation({
    mutationFn: async (record: LightningAmplitudeRecord) => {
      if (!canManage) {
        throw new Error(t("缺少 lightning.manage 权限"));
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${record.id}/retry`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeImportResponse;
    },
    onSuccess: async (payload) => {
      setError(null);
      setSuccess(`${t("重试任务已提交（任务ID")}: ${payload.task_id}）`);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : t("重试失败")));
    },
  });

  const editMutation = useMutation({
    mutationFn: async (values: Partial<LightningAmplitudeUpdateRequest>) => {
      if (!canManage) {
        throw new Error(t("缺少 lightning.manage 权限"));
      }
      if (!editRecord) {
        throw new Error(t("未选择记录"));
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${editRecord.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeRecord;
    },
    onSuccess: async () => {
      setError(null);
      setSuccess(t("雷电流幅值记录元信息已更新"));
      setEditModalOpen(false);
      setEditRecord(null);
      editForm.resetFields();
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? (candidate.message ?? t("更新失败")) : t("更新失败")));
    },
  });

  const openEditModal = useCallback((record: LightningAmplitudeRecord) => {
    setEditRecord(record);
    editForm.setFieldsValue({
      event_time: record.event_time ? dayjs(record.event_time) : undefined,
      sample_interval_us: record.sample_interval_us ?? 1,
      city: record.city || "",
      location_tag: record.location_tag || "",
    });
    setEditModalOpen(true);
  }, [editForm]);

  const openDetail = useCallback((record: LightningAmplitudeRecord) => {
    const key = record.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{truncateFileName(record.source_file_name, 20, t)}</span>,
          closable: true,
          children: (
            <AmplitudeDetailView
              record={record}
              canManage={canManage}
              onRetry={(recordToRetry) => retryMutation.mutate(recordToRetry)}
              retryLoading={retryMutation.isPending}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [canManage, retryMutation]);

  // 单条幅值记录的回填记录（动态 Tab）
  const openBackfillHistory = useCallback((record: LightningAmplitudeRecord) => {
    const key = `backfill-history-${record.id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{t("回填记录")} - {truncateFileName(record.source_file_name, 20, t)}</span>,
          closable: true,
          children: <LightningCurrentBackfillHistoryTable amplitudeId={record.id} />,
        },
      ];
    });
    setActiveTabKey(key);
  }, []);

  // 回填线路小窗查询
  const backfillLinesQuery = useQuery<LightningAmplitudeBackfillLineListResponse>({
    queryKey: ["lightning-currents", backfillLinesRecord?.id, "backfill-lines"],
    enabled: !!backfillLinesRecord,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/amplitudes/${backfillLinesRecord?.id}/backfill-lines`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeBackfillLineListResponse;
    },
  });

  // 幅值快照：取首行 line_amplitude_backfill 关联行的幅值字段，与线路无关，仅展示一次
  const backfillAmplitudeSnapshot = useMemo(() => {
    const first = backfillLinesQuery.data?.items?.[0];
    if (!first) {
      return null;
    }
    return {
      currentA: first.current_a,
      currentB: first.current_b,
      peakMax: first.peak_max,
      peakMin: first.peak_min,
      sampledEventCount: first.sampled_event_count,
    };
  }, [backfillLinesQuery.data]);

  const openBackfillLines = (record: LightningAmplitudeRecord) => {
    setBackfillLinesRecord(record);
    setBackfillLinesOpen(true);
  };

  const handleDownloadSource = useCallback(async (record: LightningAmplitudeRecord) => {
    try {
      await downloadFileWithAuth(
        `/api/v1/lightning-currents/amplitudes/${record.id}/source`,
        record.source_file_name || "lightning_amplitude.csv",
      );
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : t("下载源文件失败"));
    }
  }, [messageApi]);

  const handleTabsEdit = useCallback((targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    void queryClient.refetchQueries({ queryKey: [listPath] });
  };

  const renderRecordCard = (record: LightningAmplitudeRecord) => {
    const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };

    return (
      <Card
        key={record.id}
        size="small"
        hoverable
        className="admin-lightning-events-card"
        onClick={() => openDetail(record)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-events-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <div className="flex flex-1 min-w-0 flex-col">
                <Typography.Text strong className="truncate">{record.source_file_name || "-"}</Typography.Text>
              </div>
              <div className="flex flex-shrink-0 items-center gap-2">
                <Badge status={meta.color} />
                <Typography.Text type="secondary" className="text-xs">{t(meta.label)}</Typography.Text>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <NumberOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">{t("采样点数")}：{record.sample_count}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <ThunderboltOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">{t("峰值(kA)")}：{formatNumber(record.peak_abs_current_ka, 2)}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <SwapOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">{t("极性")}：{formatPolarity(record.polarity, t)}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <NodeIndexOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">
                {t("回填线路数")}：
                {(record.backfill_line_count ?? 0) > 0 ? (
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0, height: "auto", fontSize: 12 }}
                    onClick={(event) => {
                      event.stopPropagation();
                      openBackfillLines(record);
                    }}
                  >
                    {record.backfill_line_count} {t("条")}
                  </Button>
                ) : (
                  "-"
                )}
              </Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <HistoryOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">{t("导入时间")}：{formatDateTime(record.create_date) || "-"}</Typography.Text>
            </div>
          </div>

          <div className="admin-lightning-events-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {record.status === "processing" ? (
              <Progress percent={record.progress} size="small" className="flex-1 max-w-40" />
            ) : (
              <div />
            )}
            <Space size="small" className="shrink-0">
              <AntTooltip title={t("详情")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openDetail(record);
                  }}
                />
              </AntTooltip>
              {canManage && (
                <AntTooltip title={t("回填")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<SendOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      openBackfillHistory(record);
                    }}
                  />
                </AntTooltip>
              )}
              <Dropdown
                menu={{
                  items: [
                    ...(canManage
                      ? [
                          {
                            key: "edit",
                            label: t("编辑"),
                            onClick: (info) => {
                              info.domEvent?.stopPropagation();
                              openEditModal(record);
                            },
                          },
                        ]
                      : []),
                    ...(canRead
                      ? [
                          {
                            key: "download-source",
                            label: t("下载"),
                            onClick: (info) => {
                              info.domEvent?.stopPropagation();
                              void handleDownloadSource(record);
                            },
                          },
                        ]
                      : []),
                    ...(canReadLogs && record.task_id
                      ? [
                          {
                            key: "import-log",
                            label: t("日志"),
                            onClick: (info) => {
                              info.domEvent?.stopPropagation();
                              openLogViewer(record.task_id, t("日志"), record.source_file_name);
                            },
                          },
                        ]
                      : []),
                    ...(canManage
                      ? [
                          {
                            key: "delete",
                            label: t("删除"),
                            danger: true,
                            disabled: deleteMutation.isPending,
                            onClick: (info) => {
                              info.domEvent?.stopPropagation();
                              modalApi.confirm({
                                title: t("删除记录"),
                                content: `${t("确认删除记录")} ${record.source_file_name} ${t("吗？")}`,
                                okText: t("删除"),
                                cancelText: t("取消"),
                                okButtonProps: { danger: true },
                                onOk: async () => {
                                  await deleteMutation.mutateAsync(record);
                                },
                              });
                            },
                          },
                        ]
                      : []),
                  ],
                }}
                trigger={["click"]}
              >
                <AntTooltip title={t("更多")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    onClick={(event) => event.stopPropagation()}
                  />
                </AntTooltip>
              </Dropdown>
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  const columns = useMemo<ColumnsType<LightningAmplitudeRecord>>(
    () => [
      {
        title: t("文件名称"),
        dataIndex: "source_file_name",
        render: (value: string) => value || "-",
      },
      {
        title: t("采样点数"),
        dataIndex: "sample_count",
        width: 100,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("峰值(kA)"),
        dataIndex: "peak_abs_current_ka",
        width: 100,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: t("极性"),
        dataIndex: "polarity",
        width: 90,
        render: (value: LightningPolarity) => formatPolarity(value, t),
      },
      {
        title: t("回填状态"),
        dataIndex: "status",
        width: 160,
        render: (_: unknown, row) => {
          const meta = STATUS_META[row.status] ?? { color: "default", label: row.status };
          const failed = row.status === "failed";
          const statusTag = (
            <Tag color={meta.color}>{t(meta.label)}</Tag>
          );
          return (
            <Space size={6}>
              {failed && row.error_message ? (
                <AntTooltip title={row.error_message}>
                  {statusTag}
                </AntTooltip>
              ) : statusTag}
              {row.status === "processing" && (
                <Progress percent={row.progress} size="small" style={{ width: 80 }} />
              )}
            </Space>
          );
        },
      },
      {
        title: t("回填线路数"),
        dataIndex: "backfill_line_count",
        key: "backfill_line_count",
        width: 130,
        render: (_: unknown, row) => {
          const count = row.backfill_line_count ?? 0;
          if (count === 0) {
            return <Typography.Text type="secondary">-</Typography.Text>;
          }
          return (
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openBackfillLines(row)}>
              {count} {t("条")}
            </Button>
          );
        },
      },
      {
        title: t("导入时间"),
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 160,
        fixed: "right",
      render: (_: unknown, row) => {
          // 统一 UI 规范：默认仅展示 2 个直接按钮（详情/回填），其余操作收进 ⋯ 三点下拉
          return (
            <ModoActionGroup
              actions={[
                { key: "detail", label: t("详情"), onClick: () => openDetail(row) },
                {
                  key: "backfill",
                  label: t("回填"),
                  visible: canManage,
                  onClick: () => openBackfillHistory(row),
                },
                {
                  key: "edit",
                  label: t("编辑"),
                  visible: canManage,
                  disabled: editMutation.isPending,
                  onClick: () => openEditModal(row),
                },
                {
                  key: "download-source",
                  label: t("下载"),
                  visible: canRead,
                  onClick: () => {
                    void handleDownloadSource(row);
                  },
                },
                {
                  key: "import-log",
                  label: t("日志"),
                  visible: canReadLogs && Boolean(row.task_id),
                  onClick: () => openLogViewer(row.task_id, t("日志"), row.source_file_name),
                },
                {
                  key: "delete",
                  label: t("删除"),
                  danger: true,
                  visible: canManage,
                  disabled: deleteMutation.isPending,
                  onClick: () => {
                    modalApi.confirm({
                      title: t("删除记录"),
                      content: `${t("确认删除记录")} ${row.source_file_name} ${t("吗？")}`,
                      okText: t("删除"),
                      cancelText: t("取消"),
                      okButtonProps: { danger: true },
                      onOk: async () => {
                        await deleteMutation.mutateAsync(row);
                      },
                    });
                  },
                },
              ]}
            />
          );
        },
      },
    ],
    [canManage, canRead, handleDownloadSource, deleteMutation, editMutation, openEditModal, openDetail, openBackfillLines, openBackfillHistory, canReadLogs, openLogViewer, modalApi],
  );

  if (initializing) {
    return (
      <AdminPageLoading minHeightClassName="min-h-[280px]"
      />
    );
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            {t("请先登录后再访问雷电流幅值统计页面。")}
          </Typography.Text>
          <Button>
            <Link href="/">{t("返回首页")}</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">{t("你没有访问该页面的权限（需要 `lightning.read`）。")}</Typography.Text>
          <Button>
            <Link href="/">{t("返回首页")}</Link>
          </Button>
        </Space>
      </Card>
    );
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
          <Space size={8}>
            {canManage ? (
              <Button type="primary" onClick={() => setImportModalOpen(true)}>
                {t("导入")}
              </Button>
            ) : null}
          </Space>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("雷电流幅值统计")}</>,
            closable: false,
            children: (
              <div className="modo-page-card admin-lightning-currents-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("按文件名/事件编号搜索")}
                        value={keywordInput}
                        onChange={(event) => handleKeywordChange(event.target.value)}
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                      <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn" loading={recordsQuery.isFetching}>
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

                {viewMode === "list" ? (
                  <div
                    ref={tableScrollAnchorRef}
                    className="lightning-table-anchor"
                    style={{ "--lightning-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<LightningAmplitudeRecord>
                      rowKey={(row) => row.id}
                      columns={columns}
                      dataSource={records}
                      loading={recordsQuery.isFetching}
                      tableLayout="fixed"
                      pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total: recordsQuery.data?.total ?? 0,
                        showSizeChanger: true,
                        pageSizeOptions: [10, 20, 50, 100],
                        showTotal: () => `${t("共")} ${recordsQuery.data?.total ?? 0} ${t("条")}`,
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
                            description={t("未找到符合筛选条件的记录。")}
                          />
                        ),
                      }}
                    />
                  </div>
                ) : (
                  <div className="admin-lightning-events-card-view">
                    {recordsQuery.isLoading && records.length === 0 ? (
                      <div className="admin-lightning-events-card-view-state">
                        <Spin />
                      </div>
                    ) : records.length === 0 ? (
                      <div className="admin-lightning-events-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("未找到符合筛选条件的记录。")}
                        />
                      </div>
                    ) : (
                      <>
                        <div className="admin-lightning-events-card-scroll">
                          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                            {records.map((record) => renderRecordCard(record))}
                          </div>
                        </div>
                        <div className="admin-lightning-events-pagination">
                          <ModoPagination
                            current={pagination.current}
                            pageSize={pagination.pageSize}
                            total={recordsQuery.data?.total ?? 0}
                            onChange={(page, pageSize) => {
                              setPagination({ current: page, pageSize });
                            }}
                            showSizeChanger
                            showTotal={(total) => `${t("共")} ${total} ${t("条")}`}
                          />
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title={t("导入雷电流幅值数据")}
        open={importModalOpen}
        onCancel={() => {
          setImportModalOpen(false);
          importForm.resetFields();
          setSelectedFile(null);
          setTempFileId(null);
          setUploadProgress(0);
          setUploadError("");
        }}
        footer={null}
        width={560}
        destroyOnHidden
      >
        <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={INITIAL_IMPORT_VALUES}>
          <div className="flex flex-col gap-3">
            <Form.Item name="city" label={t("采样城市")}>
              <Select
                showSearch
                placeholder={t("请搜索选择城市")}
                filterOption={(input, option) => {
                  const keyword = input.toLowerCase().trim();
                  const data = option?.["data-data"] as CityOption | undefined;
                  if (!data) return false;
                  return (
                    data.label.includes(input)
                    || data.pinyin.includes(keyword)
                    || data.initials.includes(keyword)
                  );
                }}
                options={CHINESE_CITIES.map((item) => ({
                  label: item.label,
                  value: item.label,
                  "data-data": item,
                }))}
              />
            </Form.Item>
            <Form.Item name="location_tag" label={t("采样地点")} rules={[{ max: 255, message: t("采样地点最多 255 个字符") }]}>
              <Input placeholder={t("例如 XX变电站、XX区域")} />
            </Form.Item>
            <Form.Item name="sample_interval_us" label={t("采样间隔(us)")} rules={[{ type: "number", min: 0.000001, message: t("采样间隔必须大于 0") }]}>
              <InputNumber style={{ width: "100%" }} min={0.000001} precision={6} />
            </Form.Item>
            <Form.Item name="event_time" label={t("采样时间")}>
              <DatePicker className="w-full" showTime placeholder={t("选择日期时间")} />
            </Form.Item>
          </div>
          <div style={{ marginBottom: 16 }}>
            <Form.Item label={t("数据文件")} required>
              <Upload.Dragger
                accept=".txt,.csv,text/plain,text/csv"
                showUploadList={false}
                beforeUpload={(file) => {
                  const maxMB = 50;
                  const allowedExts = ["csv", "txt"];
                  const ext = file.name.split(".").pop()?.toLowerCase() || "";
                  if (file.size > maxMB * 1024 * 1024) {
                    messageApi.error(`${t("文件大小超过")} ${maxMB}MB ${t("限制，请压缩后重新上传")}`);
                    return Upload.LIST_IGNORE;
                  }
                  if (!allowedExts.includes(ext)) {
                    messageApi.error(`${t("不支持的文件格式，仅支持")} .${allowedExts.join("/")}`);
                    return Upload.LIST_IGNORE;
                  }
                  return true;
                }}
                customRequest={({ file }) => handleTempUpload(file as File)}
                onRemove={() => {
                  setSelectedFile(null);
                  setTempFileId(null);
                  setUploadProgress(0);
                  setUploadError("");
                }}
              >
                {selectedFile ? (
                  <>
                    <p className="ant-upload-text">{selectedFile.name}</p>
                    {uploadProgress < 100 ? (
                      <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                    ) : tempFileId ? (
                      <Typography.Text type="success">
                        <CheckCircleOutlined /> {t("上传完成，可以确认导入")}
                      </Typography.Text>
                    ) : uploadError ? (
                      <Typography.Text type="danger">{t("格式校验未通过，请更换文件")}</Typography.Text>
                    ) : (
                      <Typography.Text type="warning">{t("上传中…")}</Typography.Text>
                    )}
                  </>
                ) : (
                  <>
                    <InboxOutlined style={{ fontSize: 40, color: "#999" }} />
                    <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                      {t("点击或拖拽文件到此区域上传")}
                    </p>
                    <Typography.Text type="secondary">
                      {t("支持单列电流序列（每行一个值）或双列 time,current 格式。选择文件后立即上传到临时存储。")}
                    </Typography.Text>
                  </>
                )}
                {uploadError && (
                  <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                    {uploadError}
                  </Typography.Text>
                )}
              </Upload.Dragger>
            </Form.Item>
          </div>
          <div style={{ textAlign: "right", borderTop: "1px solid var(--ant-color-border-secondary)", paddingTop: 16 }}>
            <Button
              type="primary"
              disabled={!tempFileId}
              loading={importMutation.isPending}
              onClick={async () => {
                try {
                  await importForm.validateFields();
                  importMutation.mutate();
                } catch {
                  // 表单校验失败时不触发导入
                }
              }}
            >
              {t("确认导入")}
            </Button>
          </div>
        </Form>
      </Modal>

      {/* 回填线路小窗 */}
      <Modal
        title={backfillLinesRecord ? `${t("使用此幅值的线路")} - ${backfillLinesRecord.source_file_name}` : t("使用此幅值的线路")}
        open={backfillLinesOpen}
        onCancel={() => {
          setBackfillLinesOpen(false);
          setBackfillLinesRecord(null);
        }}
        footer={null}
        width={640}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {backfillAmplitudeSnapshot && (
            <Descriptions size="small" bordered column={4}>
              <Descriptions.Item label="current_a(kA)">
                {formatNumber(backfillAmplitudeSnapshot.currentA, 3)}
              </Descriptions.Item>
              <Descriptions.Item label="current_b(kA)">
                {formatNumber(backfillAmplitudeSnapshot.currentB, 3)}
              </Descriptions.Item>
              <Descriptions.Item label={t("峰值max(kA)")}>
                {formatNumber(backfillAmplitudeSnapshot.peakMax, 3)}
              </Descriptions.Item>
              <Descriptions.Item label={t("峰值min(kA)")}>
                {formatNumber(backfillAmplitudeSnapshot.peakMin, 3)}
              </Descriptions.Item>
              <Descriptions.Item label={t("采样数")} span={4}>
                {backfillAmplitudeSnapshot.sampledEventCount}
              </Descriptions.Item>
            </Descriptions>
          )}
          <Table<LightningAmplitudeBackfillLine>
            rowKey="line_id"
            size="small"
            loading={backfillLinesQuery.isFetching}
            dataSource={backfillLinesQuery.data?.items ?? []}
            tableLayout="fixed"
            pagination={false}
            scroll={{ y: 260 }}
            columns={[
              {
                title: t("线路编号"),
                dataIndex: "line_code",
                key: "line_code",
                width: 120,
                render: (value: string | null) => value || "-",
              },
              {
                title: t("线路名称"),
                dataIndex: "line_name",
                key: "line_name",
                ellipsis: true,
                render: (value: string | null) => value || "-",
              },
              {
                title: t("电压(kV)"),
                dataIndex: "voltage_kv",
                key: "voltage_kv",
                width: 90,
                render: (value: number | null) => (value == null ? "-" : value),
              },
              {
                title: t("回填时间"),
                dataIndex: "prepared_at",
                key: "prepared_at",
                width: 150,
                render: (value: string | null) => formatDateTime(value),
              },
            ]}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("该幅值尚未被任何线路回填使用")}
                />
              ),
            }}
          />
        </Space>
      </Modal>

      {/* 编辑雷电流幅值元信息 */}
      <Modal
        title={editRecord ? `${t("编辑元信息")} - ${editRecord.source_file_name}` : t("编辑元信息")}
        open={editModalOpen}
        forceRender
        onCancel={() => {
          setEditModalOpen(false);
          setEditRecord(null);
          editForm.resetFields();
        }}
        onOk={async () => {
          try {
            const values = await editForm.validateFields();
            // 仅提交编辑表单保留字段；后端对未传字段（None）保持原值
            const payload: Partial<LightningAmplitudeUpdateRequest> = {
              event_time: values.event_time ? values.event_time.format("YYYY-MM-DDTHH:mm:ss") : null,
              sample_interval_us: values.sample_interval_us ?? null,
              city: values.city || null,
              location_tag: values.location_tag || null,
            };
            editMutation.mutate(payload);
          } catch {
            // 表单校验失败时不提交
          }
        }}
        confirmLoading={editMutation.isPending}
        okText={t("保存")}
        cancelText={t("取消")}
        width={560}
        destroyOnHidden
      >
        <Form<ImportFormValues> form={editForm} layout="vertical" initialValues={INITIAL_IMPORT_VALUES}>
          <div className="flex flex-col gap-3">
            <Form.Item name="city" label={t("采样城市")}>
              <Select
                showSearch
                placeholder={t("请搜索选择城市")}
                filterOption={(input, option) => {
                  const keyword = input.toLowerCase().trim();
                  const data = option?.["data-data"] as CityOption | undefined;
                  if (!data) return false;
                  return (
                    data.label.includes(input)
                    || data.pinyin.includes(keyword)
                    || data.initials.includes(keyword)
                  );
                }}
                options={CHINESE_CITIES.map((item) => ({
                  label: item.label,
                  value: item.label,
                  "data-data": item,
                }))}
              />
            </Form.Item>
            <Form.Item name="location_tag" label={t("采样地点")} rules={[{ max: 255, message: t("采样地点最多 255 个字符") }]}>
              <Input placeholder={t("例如 XX变电站、XX区域")} />
            </Form.Item>
            <Form.Item name="sample_interval_us" label={t("采样间隔(us)")} rules={[{ type: "number", min: 0.000001, message: t("采样间隔必须大于 0") }]}>
              <InputNumber style={{ width: "100%" }} min={0.000001} precision={6} />
            </Form.Item>
            <Form.Item name="event_time" label={t("采样时间")}>
              <DatePicker className="w-full" showTime placeholder={t("选择日期时间")} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <TaskLogViewerDrawer
        taskId={logModalTaskId}
        title={logModalTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
      />

    </div>
  );
}

function AmplitudeDetailView({
  record,
  canManage,
  onRetry,
  retryLoading,
}: {
  record: LightningAmplitudeRecord;
  canManage: boolean;
  onRetry: (record: LightningAmplitudeRecord) => void;
  retryLoading: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="admin-lightning-currents-detail-pane modo-page-card">
      <div>
        <Typography.Title level={5}>{t("基本信息")}</Typography.Title>
        <Descriptions bordered size="small" column={2} className="admin-lightning-currents-meta-table">
          <Descriptions.Item label={t("采样城市")}>{formatNullable(record.city)}</Descriptions.Item>
          <Descriptions.Item label={t("采样地点")}>{formatNullable(record.location_tag)}</Descriptions.Item>
          <Descriptions.Item label={t("采样时间")}>{formatNullable(record.event_time)}</Descriptions.Item>
          <Descriptions.Item label={t("采样点数")}>{record.sample_count}</Descriptions.Item>
          <Descriptions.Item label={t("采样间隔(us)")}>{formatNumber(record.sample_interval_us, 6)}</Descriptions.Item>
        </Descriptions>
      </div>

      <div>
        <Typography.Title level={5}>{t("波形特征参数")}</Typography.Title>
        <Descriptions bordered size="small" column={2} className="admin-lightning-currents-meta-table">
          <Descriptions.Item label={
            <span>
              {t("峰值电流(kA)")}{" "}
              <AntTooltip title={t("波形序列中绝对值最大的电流值（kA），代表该次雷击的最强瞬间。是衡量雷击强度的核心指标。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.peak_current_ka, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={t("绝对峰值(kA)")}>{formatNumber(record.peak_abs_current_ka, 3)}</Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("波形分类")}{" "}
              <AntTooltip title={t("将实际波形的波前时间（T1）和半峰值时间（T2）与 IEC 标准波形模板匹配，归入最接近的分类：10/350（T1=10μs, T2=350μs，典型直击雷波形）、8/20（T1=8μs, T2=20μs，典型感应雷/测试波形）、1.2/50（T1=1.2μs, T2=50μs，典型操作冲击波形）。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNullable(record.wave_shape)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("极性")}{" "}
              <AntTooltip title={t("雷电流的主导方向。自然界约 90% 为负极性雷击，正极性雷击虽少但峰值更大、危害更强。正极性：正峰值大于负峰值；负极性：负峰值大于正峰值；混合：正负峰值相近。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatPolarity(record.polarity, t)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("波前时间 T1(us)")}{" "}
              <AntTooltip title={t("电流从峰值的 10% 上升到 90% 所需时间的 1.25 倍（μs），反映雷电流上升的陡度。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.wavefront_time_t1_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("半峰值时间 T2(us)")}{" "}
              <AntTooltip title={t("从虚拟零点到电流下降到峰值 50% 的时间（μs），反映脉冲宽度。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.half_value_time_t2_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("陡度(kA/us)")}{" "}
              <AntTooltip title={t("波形中电流变化率的最大值（kA/μs），影响感应过电压的大小。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.steepness_ka_per_us, 6)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              {t("I²t 作用积分(J/Ω)")}{" "}
              <AntTooltip title={t("电流平方对时间的积分（J/Ω），衡量雷电流的热效应能量。")}>
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.action_integral_j_ohm, 3)}
          </Descriptions.Item>
        </Descriptions>
      </div>

      {record.stroke_peaks_json && record.stroke_peaks_json.length > 0 && (
        <div>
          <Typography.Title level={5}>{t("多回击峰值分布")}</Typography.Title>
          <MultiReturnPeakChart peaks={record.stroke_peaks_json as Record<string, unknown>[]} />
        </div>
      )}

      {record.status === "failed" && (
        <div>
          <Typography.Title level={5}>{t("失败原因")}</Typography.Title>
          <Typography.Paragraph type="danger">
            {record.error_message || t("未知错误")}
          </Typography.Paragraph>
          {canManage && (
            <Button danger loading={retryLoading} onClick={() => onRetry(record)}>
              {t("重试")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
