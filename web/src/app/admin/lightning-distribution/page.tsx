"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import {
  App,
  Button,
  Badge,
  Card,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Image,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
} from "antd";
import {
  CheckCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EnvironmentOutlined,
  EyeOutlined,
  FileTextOutlined,
  InboxOutlined,
  MoreOutlined,
  NumberOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  SendOutlined,
  TagOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, type RefAttributes } from "react";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { getApiBaseUrl, readApiError } from "@/lib/api";
import type {
  LightningDistributionImportResponse,
  LightningDistributionRecord,
  LightningDistributionListResponse,
  LightningDistributionStatusResponse,
  LightningDensityBackfillTowerDetail,
  LightningDensityBackfillTowersResponse,
  LightningDensityBackfillTaskSummary,
  LightningDensityBackfillHistoryResponse,
  LightningLpDrawResponse,
  LightningLinkedLineSummary,
  LightningLinkedLinesResponse,
  LightningTempUploadResponse,
  LineSummary,
  LineListResponse,
} from "@/types/auth";
import { CHINESE_CITIES, type CityOption } from "@/data/chinese-cities";

type ImportFormValues = {
  event_year: number;
  region_id: string;
  city: string;
  notes: string;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  event_year: new Date().getFullYear(),
  region_id: "",
  city: "",
  notes: "",
};

const STATUS_META: Record<string, { color: "default" | "processing" | "success" | "error"; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const LIGHTNING_TABLE_BOTTOM_GAP = 8;

const FIELD_HELP_TOOLTIPS = {
  overallNg: "地闪密度：区域内单位面积、单位时间内的落雷次数，即有效落雷数 ÷（面积 km² × 统计年数），单位为 次/(km²·年)。数值越高表示该区域雷击活动越频繁。",
  maxCurrent: "区域内落雷电流绝对值的最大值（kA），反映该区域最强一次雷击的电流强度。",
  avgCurrent: "区域内落雷电流绝对值的平均值（kA），反映该区域雷击电流的总体强度水平。",
} as const;

function FieldHelpTooltip({ content }: { content: string }) {
  return (
    <Tooltip title={content}>
      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px", marginLeft: 4 }} />
    </Tooltip>
  );
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

/** 图片加载失败时的占位图（data URI SVG，灰色底 + 提示文案） */
const IMAGE_LOAD_ERROR_FALLBACK =
  "data:image/svg+xml;charset=utf-8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">' +
      '<rect width="100%" height="100%" fill="#fafafa"/>' +
      '<g fill="#bfbfbf" font-family="sans-serif" text-anchor="middle">' +
      '<circle cx="320" cy="150" r="40"/>' +
      '<path d="M280 240c8-40 24-56 40-56s32 16 40 56z"/>' +
      '<text x="320" y="290" font-size="16">图片加载失败</text>' +
      "</g></svg>",
  );

/**
 * 详情页密度图统一渲染：
 * - 请求中显示骨架屏（Skeleton.Image）
 * - 请求失败显示错误提示 + 重试按钮
 * - 图片加载中显示骨架 placeholder，加载失败显示 fallback 占位图（避免破图小图标）
 * - 无数据时显示空态
 */
function DistributionImagePane({
  query,
  alt,
  emptyText,
}: {
  query: UseQueryResult<string | null, Error>;
  alt: string;
  emptyText: string;
}) {
  if (query.isPending) {
    return (
      <div className="admin-lightning-distribution-image-skeleton">
        <Skeleton.Image active style={{ width: "100%", maxWidth: 640, height: 360 }} />
      </div>
    );
  }

  if (query.isError) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="密度图加载失败">
        <Button size="small" onClick={() => query.refetch()}>
          重新加载
        </Button>
      </Empty>
    );
  }

  if (query.data) {
    return (
      <Image
        src={query.data}
        alt={alt}
        placeholder={
          <div className="admin-lightning-distribution-image-skeleton">
            <Skeleton.Image active style={{ width: "100%", maxWidth: 640, height: 360 }} />
          </div>
        }
        fallback={IMAGE_LOAD_ERROR_FALLBACK}
        preview={false}
        style={{ maxWidth: "100%", border: "1px solid #f0f0f0", borderRadius: 6 }}
      />
    );
  }

  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function truncateFileName(name: string, maxLength = 20): string {
  if (!name) {
    return "未命名";
  }
  return name.length > maxLength ? `${name.slice(0, maxLength)}…` : name;
}

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

export default function AdminLightningDistributionPage() {
  const { user, initializing, hasPermission, fetchWithAuth, getAccessToken } = useAuth();
  const { modal: modalApi, message: messageApi } = App.useApp();
  const queryClient = useQueryClient();
  const [importForm] = Form.useForm<ImportFormValues>();

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [lpDrawRow, setLpDrawRow] = useState<LightningDistributionRecord | null>(null);
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);

  const openLpDrawModal = useCallback((record: LightningDistributionRecord) => {
    setLpDrawRow(record);
  }, []);

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeImportId, setActiveImportId] = useState<string | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // ---- 任务日志弹窗 ----
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logModalTaskId, setLogModalTaskId] = useState<string | null>(null);
  const [logModalTitle, setLogModalTitle] = useState("任务执行日志");

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");

  const openLogViewer = (taskId: string | null | undefined, label: string, fileName: string) => {
    if (!taskId || !canReadLogs) {
      return;
    }
    setLogModalTaskId(taskId);
    setLogModalTitle(`${label} - ${fileName}`);
    setLogModalOpen(true);
  };

  // ---- 地闪分布列表 ----
  const trimmedKeyword = searchKeyword.trim();
  const distributionsPath = useMemo(() => {
    const params = new URLSearchParams();
    if (trimmedKeyword) params.set("keyword", trimmedKeyword);
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    return `/api/v1/lightning-currents/distributions?${params.toString()}`;
  }, [trimmedKeyword, paginationCurrent, paginationPageSize]);

  const distributionsQuery = useQuery({
    queryKey: [distributionsPath],
    enabled: !!user && canRead,
    // 列表不再单点依赖 WebSocket：存在 pending/processing 记录时按 ~5s 轮询，
    // 保证 WS 断开/403 时进度也能推进到最终态；全部完成后停止轮询。
    refetchInterval: (query) => {
      const items = (query.state.data as LightningDistributionListResponse | undefined)?.items ?? [];
      const hasActive = items.some((row) => row.status === "pending" || row.status === "processing");
      return hasActive ? 5000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(distributionsPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionListResponse;
    },
  });

  const records = useMemo(() => distributionsQuery.data?.items ?? [], [distributionsQuery.data?.items]);
  const total = distributionsQuery.data?.total ?? 0;
  const listError = distributionsQuery.error instanceof Error ? distributionsQuery.error.message : "";

  // ---- 导入任务进度轮询 ----
  const importStatusPath = activeImportId
    ? `/api/v1/lightning-currents/distributions/${activeImportId}/status`
    : null;
  const importStatusQuery = useQuery({
    queryKey: [importStatusPath],
    enabled: !!importStatusPath,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 5000;
    },
    queryFn: async () => {
      if (!importStatusPath) return null;
      const response = await fetchWithAuth(importStatusPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionStatusResponse;
    },
  });

  const activeRecord = importStatusQuery.data?.record ?? null;
  const activeStatus = importStatusQuery.data?.status;

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(""),
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
    "admin.lightning-distribution",
    useCallback((event) => {
      const name = event.name;
      const payload = event.payload as {
        distribution_id?: string;
        stage?: string;
        progress?: number;
        status?: string;
        error?: string;
      };
      if (name === "distribution.import_started") {
        if (payload?.distribution_id) setActiveImportId(payload.distribution_id);
        void refreshAll();
      } else if (name === "distribution.import_progress") {
        void refreshAll();
      } else if (name === "distribution.import_completed") {
        setActiveImportId(null);
        void refreshAll();
      } else if (name === "distribution.import_failed") {
        setActiveImportId(null);
        setError(payload?.error || "分布导入失败，请查看记录详情后重试");
        void refreshAll();
      } else if (name === "distribution.lp_draw_completed") {
        setError("");
        setSuccess("LP 分区密度图绘制完成，可在详情弹窗查看。");
        void refreshAll();
      } else if (name === "distribution.lp_draw_failed") {
        setError(payload?.error || "LP 分区密度图绘制失败");
        void refreshAll();
      }
    }, [refreshAll]),
  );

  // ---- 导入 ----
  const importMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      if (!tempFileId) {
        throw new Error("文件尚未上传完成，请等待上传后再确认导入");
      }
      const values = importForm.getFieldsValue(true);
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      formData.append("event_year", String(values.event_year));
      formData.append("region_id", values.region_id.trim());
      formData.append("city", values.city.trim());
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());

      const response = await fetchWithAuth("/api/v1/lightning-currents/import-distribution", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionImportResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess("分布导入已提交，正在后台解析统计…");
      setActiveImportId(payload.distribution_id);
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
      setError(candidate instanceof Error ? candidate.message : "分布导入失败");
    },
  });

  const handleTempUpload = useCallback(
    (file: File) => {
      setSelectedFile(file);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

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
          try {
            const payload = JSON.parse(xhr.responseText) as LightningTempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError("上传成功但响应解析失败，请重新选择文件");
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
      xhr.onerror = () => setUploadError("网络异常，上传失败");
      xhr.onabort = () => setUploadError("上传已取消");

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [getAccessToken],
  );

  // 导入任务完成/失败时的反馈
  useEffect(() => {
    if (!activeImportId) return;
    if (activeStatus === "completed") {
      if (activeRecord) {
        setSuccess(
          `导入完成：有效 ${activeRecord.valid_count} 条，跳过 ${activeRecord.skipped_count} 条，`
          + `Ng=${formatNumber(activeRecord.overall_ng, 4)}，Imax=${formatNumber(activeRecord.max_abs_current, 2)}kA`,
        );
      } else {
        setSuccess("分布导入完成");
      }
      setActiveImportId(null);
    } else if (activeStatus === "failed") {
      setError(activeRecord?.error_message || "分布导入失败，请查看记录详情后重试");
      setActiveImportId(null);
    }
  }, [activeStatus, activeImportId, activeRecord]);

  // ---- 删除 ----
  const deleteMutation = useMutation({
    mutationFn: async (record: LightningDistributionRecord) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/distributions/${record.id}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return response.json();
    },
    onSuccess: async (data: { success?: boolean }) => {
      if (data?.success === false) {
        setSuccess("");
        setError("删除失败：记录不存在");
        return;
      }
      setError("");
      setSuccess("分布记录已删除");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const openDetail = useCallback((record: LightningDistributionRecord) => {
    const key = record.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{truncateFileName(record.source_file_name)}</span>,
          closable: true,
          children: (
            <DistributionDetailView
              record={record}
              fetchWithAuth={fetchWithAuth}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth]);

  const openLinkedLinesModal = useCallback((record: LightningDistributionRecord) => {
    // 回填记录改为动态 Tab 展示（对齐 fl-analysis 详情 Tab 交互）
    const key = `backfill-${record.id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{truncateFileName(record.source_file_name)} - 回填记录</span>,
          closable: true,
          children: (
            <BackfillRecordsView
              record={record}
              fetchWithAuth={fetchWithAuth}
              canReadLogs={canReadLogs}
              onOpenLog={openLogViewer}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth, canReadLogs, openLogViewer]);

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

  const closeImportModal = () => {
    setImportModalOpen(false);
    importForm.resetFields();
    setSelectedFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
  };

  const handleImportConfirm = async () => {
    try {
      await importForm.validateFields();
      importMutation.mutate();
    } catch {
      // 表单校验失败时不触发导入
    }
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    void queryClient.refetchQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lightning-currents/distributions"),
    });
  };

  // ---- 表格高度自适应（锚点高度算法，与线路管理页一致）----
  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - LIGHTNING_TABLE_BOTTOM_GAP);

    const clampedHeight = Math.max(LIGHTNING_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const frameId = window.requestAnimationFrame(updateTableScrollY);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollY, viewMode, records.length]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
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
  }, [updateTableScrollY, viewMode, records.length]);

  // ---- 表格列 ----
  const columns = useMemo<ColumnsType<LightningDistributionRecord>>(
    () => [
      {
        title: "文件名",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 160,
        render: (_: unknown, row) => {
          const meta = STATUS_META[row.status] ?? { color: "default", label: row.status };
          return (
            <Space size={6}>
              <Tag color={meta.color}>{meta.label}</Tag>
              {row.status === "processing" && (
                <Progress percent={row.progress} size="small" style={{ width: 80 }} />
              )}
            </Space>
          );
        },
      },
      {
        title: "有效点数",
        dataIndex: "valid_count",
        width: 90,
        render: (value: number) => value,
      },
      {
        title: (
          <span>
            整体Ng
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.overallNg} />
          </span>
        ),
        dataIndex: "overall_ng",
        width: 130,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: (
          <span style={{ whiteSpace: "nowrap" }}>
            最大电流(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.maxCurrent} />
          </span>
        ),
        dataIndex: "max_abs_current",
        width: 130,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: (
          <span style={{ whiteSpace: "nowrap" }}>
            平均电流(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.avgCurrent} />
          </span>
        ),
        dataIndex: "avg_abs_current",
        width: 130,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "关联线路",
        key: "linked_lines",
        width: 110,
        render: (_: unknown, row) => (
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => openLinkedLinesModal(row)}
          >
            {row.linked_line_count ?? 0} 条
          </Button>
        ),
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_: unknown, row) => {
          // 统一 UI 规范：默认仅展示 2 个直接按钮（详情/回填），其余操作收进 ⋯ 三点下拉（与雷电流幅值统计页一致）
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "backfill-history",
              label: "回填记录",
              onClick: () => openLinkedLinesModal(row),
            },
            ...(canReadLogs && row.task_id
              ? [
                  {
                    key: "import-log",
                    label: "导入日志",
                    onClick: () => openLogViewer(row.task_id, "导入日志", row.source_file_name),
                  },
                ]
              : []),
            ...(canManage
              ? [
                  {
                    key: "delete",
                    label: "删除",
                    danger: true,
                    disabled: deleteMutation.isPending,
                    onClick: () => {
                      modalApi.confirm({
                        title: "确认删除该地闪分布记录？",
                        content: "将同时删除 MinIO 上的原始文件与密度图，此操作不可恢复。",
                        onOk: () => deleteMutation.mutate(row),
                        okText: "确认删除",
                        cancelText: "取消",
                        okButtonProps: { danger: true },
                      });
                    },
                  },
                ]
              : []),
          ];

          return (
            <Space wrap>
              <Button size="small" onClick={() => openDetail(row)}>
                详情
              </Button>
              {canManage && (
                <Button size="small" onClick={() => openLpDrawModal(row)}>
                  回填
                </Button>
              )}
              {moreMenuItems.length > 0 && (
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Tooltip title="更多操作">
                    <Button size="small" icon={<MoreOutlined />} />
                  </Tooltip>
                </Dropdown>
              )}
            </Space>
          );
        },
      },
    ],
    [canManage, deleteMutation, openDetail, openLinkedLinesModal, openLogViewer, openLpDrawModal, canReadLogs],
  );

  const renderRecordCard = (record: LightningDistributionRecord) => {
    const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };

    return (
      <AntCard
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={(event) => {
          if ((event.target as HTMLElement | null)?.closest(".ant-dropdown")) {
            return;
          }
          openDetail(record);
        }}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Typography.Text strong className="truncate min-w-0">
                {record.source_file_name || "未命名文件"}
              </Typography.Text>
              <div className="flex flex-shrink-0 items-center gap-2">
                <Badge status={meta.color} />
                <Typography.Text type="secondary" className="text-xs">{meta.label}</Typography.Text>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <EnvironmentOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">
                城市：{record.city || "-"}
              </Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <TagOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">
                地点标签：{record.location_tag || "-"}
              </Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <NumberOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">
                有效点数：{record.valid_count}
              </Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <ThunderboltOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">
                整体 Ng：{formatNumber(record.overall_ng, 4)}
              </Typography.Text>
            </div>
          </div>

          <div className="admin-lightning-distribution-event-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {record.status === "processing" ? (
              <Progress percent={record.progress} size="small" className="flex-1 max-w-40" />
            ) : (
              <div />
            )}
            <Space size="small" className="flex-wrap">
              <Tooltip title="查看详情">
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openDetail(record);
                  }}
                />
              </Tooltip>
              {canManage && (
                <Tooltip title="回填">
                  <Button
                    type="text"
                    size="small"
                    icon={<SendOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      openLpDrawModal(record);
                    }}
                  />
                </Tooltip>
              )}
              {(() => {
                const extraActions: MenuProps["items"] = [
                  {
                    key: "backfill-history",
                    label: "回填记录",
                    icon: <FileTextOutlined />,
                    onClick: (info) => {
                      info.domEvent?.stopPropagation();
                      openLinkedLinesModal(record);
                    },
                  },
                  ...(canReadLogs && record.task_id
                    ? [
                        {
                          key: "import-log",
                          label: "导入日志",
                          icon: <FileTextOutlined />,
                          onClick: (info) => {
                            info.domEvent?.stopPropagation();
                            openLogViewer(record.task_id, "导入日志", record.source_file_name);
                          },
                        },
                      ]
                    : []),
                  ...(canManage
                    ? [
                        {
                          key: "delete",
                          label: "删除",
                          danger: true,
                          icon: <DeleteOutlined />,
                          onClick: (info) => {
                            info.domEvent?.stopPropagation();
                            modalApi.confirm({
                              title: "确认删除",
                              content: "确认删除该地闪分布记录？此操作不可恢复。",
                              okText: "确认删除",
                              cancelText: "取消",
                              okButtonProps: { danger: true },
                              onOk: () => deleteMutation.mutate(record),
                            });
                          },
                        },
                      ]
                    : []),
                ];
                return extraActions.length > 0 ? (
                  <Dropdown menu={{ items: extraActions }} trigger={["click"]}>
                    <Button
                      type="text"
                      size="small"
                      icon={<MoreOutlined />}
                      onClick={(event) => {
                        event.stopPropagation();
                      }}
                    />
                  </Dropdown>
                ) : null;
              })()}
            </Space>
          </div>
        </div>
      </AntCard>
    );
  };

  if (initializing) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问地闪密度统计页面。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `lightning.read`）。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="admin-lightning-distribution-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" onClick={() => setImportModalOpen(true)}>
              导入
            </Button>
          ) : null
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-lightning-distribution-tab-title">地闪密度统计</span>,
            closable: false,
            children: (
              <div className="admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder="按地点/标签/文件名筛选"
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
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

                {viewMode === "card" ? (
                  <>
                    <div className="admin-lightning-distribution-card-scroll">
                      {distributionsQuery.isLoading && records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Spin />
                        </div>
                      ) : records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到符合筛选条件的地闪分布记录。"
                          />
                        </div>
                      ) : (
                        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                          {records.map((record) => renderRecordCard(record))}
                        </div>
                      )}
                    </div>
                    {records.length > 0 && (
                      <div className="admin-lightning-distribution-pagination">
                        <Pagination
                          current={pagination.current}
                          pageSize={pagination.pageSize}
                          total={total}
                          onChange={(page, pageSize) => {
                            setPagination({ current: page, pageSize });
                          }}
                          showSizeChanger
                          showTotal={(totalCount) => `共 ${totalCount} 条`}
                        />
                      </div>
                    )}
                  </>
                ) : (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-lightning-distribution-table-anchor"
                    style={{ "--admin-lightning-distribution-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<LightningDistributionRecord>
                      rowKey="id"
                      columns={columns}
                      dataSource={records}
                      loading={distributionsQuery.isFetching}
                      tableLayout="fixed"
                      pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total,
                        showSizeChanger: true,
                        pageSizeOptions: [10, 20, 50, 100],
                        showTotal: (totalCount) => `共 ${totalCount} 条`,
                        hideOnSinglePage: false,
                        onChange: (page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        },
                      }}
                      scroll={{ x: 1000, y: tableScrollY }}
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到符合筛选条件的地闪分布记录。"
                          />
                        ),
                      }}
                    />
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <ImportModal
        open={importModalOpen}
        onClose={closeImportModal}
        importForm={importForm}
        initialValues={INITIAL_IMPORT_VALUES}
        selectedFile={selectedFile}
        tempFileId={tempFileId}
        uploadProgress={uploadProgress}
        uploadError={uploadError}
        onTempUpload={handleTempUpload}
        onRemoveFile={() => {
          setSelectedFile(null);
          setTempFileId(null);
          setUploadProgress(0);
          setUploadError("");
        }}
        loading={importMutation.isPending}
        onConfirm={handleImportConfirm}
      />

      {canManage && (
        <DrawLpModal
          open={!!lpDrawRow}
          data={lpDrawRow}
          onClose={() => setLpDrawRow(null)}
          fetchWithAuth={fetchWithAuth}
          onSubmitted={(taskId, fileName) => {
            if (canReadLogs && taskId) {
              setLogModalTaskId(taskId);
              setLogModalTitle(`绘图日志 - ${fileName}`);
              setLogModalOpen(true);
            }
          }}
        />
      )}

      <TaskLogViewerDrawer
        taskId={logModalTaskId}
        title={logModalTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
        variant="modal"
      />
    </div>
  );
}

function ImportModal({
  open,
  onClose,
  importForm,
  initialValues,
  selectedFile,
  tempFileId,
  uploadProgress,
  uploadError,
  onTempUpload,
  onRemoveFile,
  loading,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  importForm: ReturnType<typeof Form.useForm<ImportFormValues>>[0];
  initialValues: ImportFormValues;
  selectedFile: File | null;
  tempFileId: string | null;
  uploadProgress: number;
  uploadError: string;
  onTempUpload: (file: File) => void;
  onRemoveFile: () => void;
  loading: boolean;
  onConfirm: () => void;
}) {
  const { message: messageApi } = App.useApp();
  return (
    <Modal
      title="导入地闪密度数据"
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnHidden
    >
      <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={initialValues}>
        <div className="grid gap-3 md:grid-cols-2">
          <Form.Item name="city" label="城市">
            <Select
              showSearch
              allowClear
              placeholder="请搜索选择城市"
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
          <Form.Item name="region_id" label="地点">
            <Input placeholder="例如 XX变电站、XX区域（闪电事件发生地点）" />
          </Form.Item>
          <Form.Item name="event_year" label="数据年份">
            <InputNumber style={{ width: "100%" }} min={1900} max={2100} />
          </Form.Item>
          <Form.Item name="notes" label="数据说明">
            <Input placeholder="可填写数据来源、采集说明等" />
          </Form.Item>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Form.Item label="数据文件" required>
              <Upload.Dragger
                accept=".txt,.csv,text/plain,text/csv"
                showUploadList={false}
                beforeUpload={(file) => {
                  const maxMB = 50;
                  const allowedExts = ["csv", "txt"];
                  const ext = file.name.split(".").pop()?.toLowerCase() || "";
                  if (file.size > maxMB * 1024 * 1024) {
                    messageApi.error(`文件大小超过 ${maxMB}MB 限制，请压缩后重新上传`);
                    return Upload.LIST_IGNORE;
                  }
                  if (!allowedExts.includes(ext)) {
                    messageApi.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
                    return Upload.LIST_IGNORE;
                  }
                  return true;
                }}
                customRequest={({ file }) => onTempUpload(file as File)}
                onRemove={() => onRemoveFile()}
              >
              {selectedFile ? (
                <>
                  <p className="ant-upload-text">{selectedFile.name}</p>
                  {uploadProgress < 100 ? (
                    <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                  ) : tempFileId ? (
                    <Typography.Text type="success">
                      <CheckCircleOutlined /> 上传完成，可以确认导入
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="warning">上传中…</Typography.Text>
                  )}
                </>
              ) : (
                <>
                  <InboxOutlined style={{ fontSize: 40, color: "#999" }} />
                  <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                    点击或拖拽文件到此区域上传
                  </p>
                  <Typography.Text type="secondary">
                    支持包含经纬度和电流的 CSV 或 TXT 文件。选择文件后立即上传到临时存储。
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
        <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
          <Button
            type="primary"
            disabled={!tempFileId}
            loading={loading}
            onClick={onConfirm}
          >
            确认导入
          </Button>
        </div>
      </Form>
    </Modal>
  );
}

function DistributionDetailView({
  record,
  fetchWithAuth,
}: {
  record: LightningDistributionRecord;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
}) {
  const imageQuery = useQuery({
    queryKey: ["/api/v1/lightning-currents/distributions", record.id, "image"],
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/distributions/${record.id}/image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      if (blob.size === 0) return null;
      return URL.createObjectURL(blob);
    },
  });

  useEffect(() => {
    const objectUrl = imageQuery.data;
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [imageQuery.data]);

  return (
    <div className="admin-lightning-distribution-detail-view">
      <Space direction="vertical" size={16} className="w-full">
      <Descriptions bordered size="small" column={3}>
        <Descriptions.Item label="城市">{record.city || "-"}</Descriptions.Item>
        <Descriptions.Item label="地点标签">{record.location_tag || "-"}</Descriptions.Item>
        <Descriptions.Item label="年份">{record.event_year ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="有效点数">{record.valid_count}</Descriptions.Item>
        <Descriptions.Item label="面积(km²)">{formatNumber(record.area_km2, 3)}</Descriptions.Item>
        <Descriptions.Item label="统计年限">{formatNumber(record.data_years, 3)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            整体 Ng
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.overallNg} />
          </span>
        }>{formatNumber(record.overall_ng, 4)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            Imax(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.maxCurrent} />
          </span>
        }>{formatNumber(record.max_abs_current, 2)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            Iavg(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.avgCurrent} />
          </span>
        }>{formatNumber(record.avg_abs_current, 2)}</Descriptions.Item>
        <Descriptions.Item label="正极数量">{record.positive_count}</Descriptions.Item>
        <Descriptions.Item label="负极数量">{record.negative_count}</Descriptions.Item>
        <Descriptions.Item label="未知极性">{record.unknown_count}</Descriptions.Item>
      </Descriptions>

      <div style={{ textAlign: "center", minHeight: 200 }}>
        <DistributionImagePane
          query={imageQuery}
          alt="地闪密度图"
          emptyText="暂无密度图（导入失败或仍在处理中）"
        />
      </div>
      </Space>
    </div>
  );
}

function BackfillRecordsView({
  record,
  fetchWithAuth,
  canReadLogs,
  onOpenLog,
}: {
  record: LightningDistributionRecord;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  canReadLogs: boolean;
  onOpenLog: (taskId: string | null | undefined, label: string, fileName: string) => void;
}) {
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const { current: page, pageSize } = pagination;
  const [towerDrawer, setTowerDrawer] = useState<LightningDensityBackfillTaskSummary | null>(null);
  const [ngImageDrawer, setNgImageDrawer] = useState<LightningDensityBackfillTaskSummary | null>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState<number>(240);

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? 39;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? 64;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - 8);
    setTableScrollY((previous) => (Math.abs(previous - Math.max(160, nextHeight)) <= 1 ? previous : Math.max(160, nextHeight)));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const frameId = window.requestAnimationFrame(updateTableScrollY);
    return () => window.cancelAnimationFrame(frameId);
  }, [updateTableScrollY, searchKeyword, page, pageSize]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);
    return () => resizeObserver.disconnect();
  }, [updateTableScrollY]);

  const linkedLinesPath = useMemo(() => {
    const params = new URLSearchParams();
    const trimmed = searchKeyword.trim();
    if (trimmed) params.set("keyword", trimmed);
    params.set("limit", String(pageSize));
    params.set("offset", String((page - 1) * pageSize));
    return `/api/v1/lightning-currents/distributions/${record.id}/backfill-history?${params.toString()}`;
  }, [record.id, searchKeyword, page, pageSize]);

  const linkedLinesQuery = useQuery({
    queryKey: [linkedLinesPath],
    queryFn: async () => {
      const response = await fetchWithAuth(linkedLinesPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDensityBackfillHistoryResponse;
    },
  });

  const linkedLines = useMemo(
    () => linkedLinesQuery.data?.items ?? [],
    [linkedLinesQuery.data],
  );
  const total = linkedLinesQuery.data?.total ?? 0;

  const handleSearch = () => {
    setSearchKeyword(keywordInput.trim());
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  const linkedColumns = useMemo<ColumnsType<LightningDensityBackfillTaskSummary>>(
    () => [
      {
        title: "回填时间",
        dataIndex: "prepared_at",
        width: 160,
        render: (value: string | null) => (value ? formatDateTime(value) : "-"),
      },
      {
        title: "线路名称",
        dataIndex: "line_name",
        width: 150,
        render: (value: string | null) => value || "-",
      },
      {
        title: "线路编号",
        dataIndex: "line_code",
        width: 130,
        render: (value: string | null) => value || "-",
      },
      {
        title: "回填塔数",
        dataIndex: "updated_tower_count",
        width: 90,
        render: (value: number) => value,
      },
      {
        title: "平均 Ng",
        dataIndex: "avg_density",
        width: 100,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: "最小 Ng",
        dataIndex: "min_density",
        width: 100,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: "最大 Ng",
        dataIndex: "max_density",
        width: 100,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_: unknown, row: LightningDensityBackfillTaskSummary) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              disabled={!canReadLogs}
              onClick={() => onOpenLog(record.task_id, "回填日志", record.source_file_name)}
            >
              日志
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={() => setTowerDrawer(row)}
            >
              详情
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={() => setNgImageDrawer(row)}
            >
              Ng图
            </Button>
          </Space>
        ),
      },
    ],
    [canReadLogs, onOpenLog, record.task_id, record.source_file_name],
  );

  return (
    <div className="admin-lightning-distribution-backfill-view" style={{ padding: "0 4px" }} ref={tableScrollAnchorRef}>
      <div className="admin-filter-bar" style={{ marginBottom: 12 }}>
        <Form layout="inline">
          <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              allowClear
              placeholder="按线路编号/名称筛选"
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
              查询
            </Button>
          </Form.Item>
        </Form>
      </div>
      <Table<LightningDensityBackfillTaskSummary>
        rowKey="id"
        size="small"
        columns={linkedColumns}
        dataSource={linkedLines}
        loading={linkedLinesQuery.isFetching}
        tableLayout="fixed"
        scroll={{ x: 900, y: tableScrollY }}
        style={{ height: "100%" }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          showTotal: (totalCount) => `共 ${totalCount} 条`,
          hideOnSinglePage: false,
          onChange: (nextPage, nextPageSize) => {
            setPagination({ current: nextPage, pageSize: nextPageSize });
          },
        }}
        locale={{
          emptyText: linkedLinesQuery.isLoading ? (
            <Spin size="small" />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该分布尚未回填任何线路" />
          ),
        }}
      />

      <TowerNgDrawer
        record={record}
        line={towerDrawer}
        fetchWithAuth={fetchWithAuth}
        onClose={() => setTowerDrawer(null)}
      />
      <NgImageDrawer
        record={record}
        line={ngImageDrawer}
        fetchWithAuth={fetchWithAuth}
        onClose={() => setNgImageDrawer(null)}
      />
    </div>
  );
}

function TowerNgDrawer({
  record,
  line,
  fetchWithAuth,
  onClose,
}: {
  record: LightningDistributionRecord;
  line: LightningDensityBackfillTaskSummary | null;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onClose: () => void;
}) {
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const { current: page, pageSize } = pagination;
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState<number>(320);

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? 39;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? 64;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - 8);
    setTableScrollY((previous) => (Math.abs(previous - Math.max(160, nextHeight)) <= 1 ? previous : Math.max(160, nextHeight)));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const frameId = window.requestAnimationFrame(updateTableScrollY);
    return () => window.cancelAnimationFrame(frameId);
  }, [updateTableScrollY, line, searchKeyword, page, pageSize]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);
    return () => resizeObserver.disconnect();
  }, [updateTableScrollY, line]);

  const towersPath = useMemo(() => {
    if (!line) return null;
    const params = new URLSearchParams();
    params.set("line_id", line.line_id);
    const trimmed = searchKeyword.trim();
    if (trimmed) params.set("keyword", trimmed);
    params.set("limit", String(pageSize));
    params.set("offset", String((page - 1) * pageSize));
    return `/api/v1/lightning-currents/distributions/${record.id}/density-towers?${params.toString()}`;
  }, [record.id, line, searchKeyword, page, pageSize]);

  const towersQuery = useQuery({
    queryKey: [towersPath],
    enabled: !!towersPath,
    queryFn: async () => {
      if (!towersPath) return { items: [], total: 0 } satisfies LightningDensityBackfillTowersResponse;
      const response = await fetchWithAuth(towersPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDensityBackfillTowersResponse;
    },
  });

  const towers = useMemo(() => towersQuery.data?.items ?? [], [towersQuery.data]);
  const total = towersQuery.data?.total ?? 0;

  const handleSearch = () => {
    setSearchKeyword(keywordInput.trim());
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  const towerColumns = useMemo<ColumnsType<LightningDensityBackfillTowerDetail>>(
    () => [
      {
        title: "杆塔号",
        dataIndex: "tower_no",
        width: 110,
        render: (value: string | null) => value || "-",
      },
      {
        title: "Ng 值(次/km²·年)",
        dataIndex: "lightning_density",
        width: 140,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: "落雷数",
        dataIndex: "strike_count",
        width: 90,
        render: (value: number | null) => (value === null || value === undefined ? "-" : value),
      },
      {
        title: "经度",
        dataIndex: "longitude",
        width: 120,
        render: (value: number | null) => formatNumber(value, 6),
      },
      {
        title: "纬度",
        dataIndex: "latitude",
        width: 120,
        render: (value: number | null) => formatNumber(value, 6),
      },
      {
        title: "最近回填时间",
        dataIndex: "prepared_at",
        width: 160,
        render: (value: string | null) => (value ? formatDateTime(value) : "-"),
      },
    ],
    [],
  );

  return (
    <Drawer
      title={`回填杆塔 Ng 值 - ${line?.line_name ?? ""}`}
      open={!!line}
      onClose={onClose}
      width={720}
      destroyOnHidden
    >
      <div ref={tableScrollAnchorRef} style={{ display: "flex", flexDirection: "column", height: "100%" }}>
        <div className="admin-filter-bar" style={{ marginBottom: 12 }}>
          <Form layout="inline">
            <Form.Item label="杆塔号" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Input
                allowClear
                placeholder="按杆塔号筛选"
                value={keywordInput}
                onChange={(event) => setKeywordInput(event.target.value)}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
                查询
              </Button>
            </Form.Item>
          </Form>
        </div>
        <Table<LightningDensityBackfillTowerDetail>
          rowKey="tower_id"
          size="small"
          columns={towerColumns}
          dataSource={towers}
          loading={towersQuery.isFetching}
          tableLayout="fixed"
          scroll={{ x: 740, y: tableScrollY }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: (totalCount) => `共 ${totalCount} 条`,
            hideOnSinglePage: false,
            onChange: (nextPage, nextPageSize) => {
              setPagination({ current: nextPage, pageSize: nextPageSize });
            },
          }}
          locale={{
            emptyText: towersQuery.isLoading ? (
              <Spin size="small" />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该线路无回填杆塔数据" />
            ),
          }}
        />
      </div>
    </Drawer>
  );
}

function NgImageDrawer({
  record,
  line,
  fetchWithAuth,
  onClose,
}: {
  record: LightningDistributionRecord;
  line: LightningDensityBackfillTaskSummary | null;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onClose: () => void;
}) {
  const { message: messageApi } = App.useApp();

  const circleImagePath = line
    ? `/api/v1/lightning-currents/distributions/${record.id}/circle-image`
    : null;
  const circleImageQuery = useQuery({
    queryKey: [circleImagePath],
    enabled: !!circleImagePath,
    queryFn: async () => {
      if (!circleImagePath) return null;
      const response = await fetchWithAuth(circleImagePath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      if (blob.size === 0) return null;
      return URL.createObjectURL(blob);
    },
  });

  useEffect(() => {
    const objectUrl = circleImageQuery.data;
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [circleImageQuery.data]);

  const loading = circleImageQuery.isFetching;
  const failed = !!circleImageQuery.error;
  const errorText = circleImageQuery.error instanceof Error ? circleImageQuery.error.message : "";
  const imageUrl = circleImageQuery.data;

  const handleDownload = async () => {
    try {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/distributions/${record.id}/circle-image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${record.source_file_name || "lightning_density"}-沿线圆密度图.png`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "下载失败");
    }
  };

  return (
    <Drawer
      title={`沿线圆密度图 - ${line?.line_name ?? ""}`}
      open={!!line}
      onClose={onClose}
      width={720}
      destroyOnHidden
      extra={
        <Button icon={<DownloadOutlined />} onClick={handleDownload}>
          下载
        </Button>
      }
    >
      <div style={{ textAlign: "center", minHeight: 240 }}>
        {loading ? (
          <Spin tip="加载中…" style={{ marginTop: 80 }}>
            <div style={{ height: 160 }} />
          </Spin>
        ) : failed ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={errorText || "暂无沿线圆密度图（回填线路后生成）"}
          />
        ) : imageUrl ? (
          <Image src={imageUrl} alt="沿线圆密度图" style={{ maxWidth: "100%" }} />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无沿线圆密度图（回填线路后生成）" />
        )}
      </div>
    </Drawer>
  );
}

function DrawLpModal({
  open,
  data,
  onClose,
  fetchWithAuth,
  onSubmitted,
}: {
  open: boolean;
  data: LightningDistributionRecord | null;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onSubmitted: (taskId: string, fileName: string) => void;
}) {
  return (
    <Modal title="线路回填" open={open} onCancel={onClose} footer={null} width={560} destroyOnHidden>
      {/* key 随分布记录变化强制重挂载，避免残留上一分布选中的线路 / 提交结果 */}
      <DrawLpBody key={data?.id ?? "empty"} open={open} data={data} fetchWithAuth={fetchWithAuth} onSubmitted={onSubmitted} />
    </Modal>
  );
}

function DrawLpBody({
  open,
  data,
  fetchWithAuth,
  onSubmitted,
}: {
  open: boolean;
  data: LightningDistributionRecord | null;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onSubmitted: (taskId: string, fileName: string) => void;
}) {
  const [lineSearchText, setLineSearchText] = useState("");
  const [lineId, setLineId] = useState<string | null>(null);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  // 当前分布记录 stats_json 中的落雷经纬度范围；历史记录可能无 bbox（降级为不传 bbox 参数）。
  const bboxParam = useMemo(() => {
    const bbox = data?.stats_json?.bbox;
    if (!bbox || typeof bbox !== "object") return null;
    const { min_lat, max_lat, min_lon, max_lon } = bbox as Record<string, unknown>;
    if (
      typeof min_lat !== "number" ||
      typeof max_lat !== "number" ||
      typeof min_lon !== "number" ||
      typeof max_lon !== "number"
    ) {
      return null;
    }
    return `${min_lat},${min_lon},${max_lat},${max_lon}`;
  }, [data?.stats_json]);

  const linesQuery = useQuery({
    queryKey: ["/api/v1/lines", lineSearchText, bboxParam],
    enabled: open,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "200");
      params.set("offset", "0");
      if (lineSearchText.trim()) params.set("keyword", lineSearchText.trim());
      if (bboxParam) {
        // bbox_mode=mark：返回全部线路并标记每条是否与落雷数据区域重叠（不隐藏）
        params.set("bbox", bboxParam);
        params.set("bbox_mode", "mark");
      }
      const resp = await fetchWithAuth(`/api/v1/lines?${params.toString()}`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      return (await resp.json()) as LineListResponse;
    },
  });

  const lineOptions = useMemo(() =>
    (linesQuery.data?.items ?? []).map((l: LineSummary) => {
      const inRange = bboxParam ? (l.bbox_overlap !== false) : true;
      const label = `${l.code} - ${l.name}${l.voltage_kv ? ` (${l.voltage_kv}kV)` : ""}`;
      return {
        label: (
          <Space size={6} style={{ width: "100%", justifyContent: "space-between" }}>
            <span>{label}</span>
            {bboxParam && !inRange && (
              <Tag color="warning" style={{ marginInlineEnd: 0 }}>不在数据范围内</Tag>
            )}
          </Space>
        ),
        value: l.id,
        disabled: bboxParam ? !inRange : false,
      };
    }),
    [linesQuery.data, bboxParam],
  );

  const drawMutation = useMutation({
    mutationFn: async () => {
      if (!lineId) throw new Error("请先选择线路");
      const body = { line_id: lineId, distribution_id: data?.id };
      const results: string[] = [];

      // 1. 绘图任务
      try {
        const drawResp = await fetchWithAuth(
          `/api/v1/lightning-currents/distributions/${data?.id}/draw-lp`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
        );
        if (drawResp.ok) {
          const p = (await drawResp.json()) as LightningLpDrawResponse;
          results.push(`绘图任务已提交（ID: ${p.task_id}）`);
        }
      } catch {
        results.push("绘图任务提交失败");
      }

      // 2. 线路密度回填
      try {
        const densityResp = await fetchWithAuth(
          `/api/v1/lightning-currents/prepare-density`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
        );
        if (densityResp.ok) {
          results.push("密度回填完成");
        } else {
          results.push("密度回填失败");
        }
      } catch {
        results.push("密度回填提交失败");
      }

      return results.join("；");
    },
    onSuccess: (msg) => {
      setError("");
      setSuccess(msg);
      onSubmitted("", data?.source_file_name || "回填");
    },
    onError: (e) => {
      setSuccess("");
      setError(e instanceof Error ? e.message : "绘图任务提交失败");
    },
  });

  return (
    <>
      <Form layout="vertical">
        <Form.Item required label="选择线路">
          <Select
            showSearch
            placeholder="选择线路（按该线路杆塔分组绘图）"
            filterOption={false}
            onSearch={setLineSearchText}
            notFoundContent={
              linesQuery.isLoading
                ? <Spin size="small" />
                : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无可用线路" />
            }
            value={lineId}
            onChange={setLineId}
            options={lineOptions}
          />
        </Form.Item>
      </Form>
      <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
        <Button type="primary" loading={drawMutation.isPending} onClick={() => drawMutation.mutate()}>
          提交回填
        </Button>
      </div>
      {success && <Typography.Paragraph type="success" style={{ marginTop: 12 }}>{success}</Typography.Paragraph>}
      {error && <Typography.Paragraph type="danger" style={{ marginTop: 12 }}>{error}</Typography.Paragraph>}
    </>
  );
}
