"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  DatePicker,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip as AntTooltip,
  Typography,
  Upload,
  message,
  type MenuProps,
} from "antd";
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EnvironmentOutlined,
  EyeOutlined,
  HomeOutlined,
  InboxOutlined,
  MoreOutlined,
  NumberOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, type TooltipValueType } from "recharts";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { ApiError, getApiBaseUrl, readApiError } from "@/lib/api";
import type {
  LightningAmplitudeRecord,
  LightningAmplitudeListResponse,
  LightningAmplitudeImportResponse,
  LightningAmplitudeBackfillLine,
  LightningAmplitudeBackfillLineListResponse,
  LightningTempUploadResponse,
  LineListResponse,
  LineSummary,
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
  sample_interval_us: number;
  city: string;
  sensor_model: string;
  install_position: string;
  notes: string;
  location_tag: string;
  event_time: dayjs.Dayjs | null;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  sample_interval_us: 1,
  city: "",
  sensor_model: "",
  install_position: "",
  notes: "",
  location_tag: "",
  event_time: null,
};

const STATUS_META: Record<string, { color: string; label: string }> = {
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

function formatPolarity(polarity: LightningPolarity): string {
  if (polarity === "positive") return "正极性";
  if (polarity === "negative") return "负极性";
  if (polarity === "mixed") return "混合";
  return "未知";
}

function truncateFileName(name: string, maxLength = 20): string {
  if (!name) {
    return "未命名";
  }
  return name.length > maxLength ? `${name.slice(0, maxLength)}…` : name;
}

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const LIGHTNING_TABLE_BOTTOM_GAP = 8;

export default function AdminLightningCurrentsPage() {
  const { user, initializing, hasPermission, fetchWithAuth, getAccessToken } = useAuth();
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
  const [backfillOpen, setBackfillOpen] = useState(false);
  const [backfillRecord, setBackfillRecord] = useState<LightningAmplitudeRecord | null>(null);
  const [backfillLineIds, setBackfillLineIds] = useState<string[]>([]);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

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
            ? `导入完成：采样点 ${payload.sample_count} 个，峰值 ${formatNumber(payload.peak_abs_current_ka, 2)}kA`
            : "导入完成",
        );
        void refreshAll();
      } else if (name === "amplitude.import_failed") {
        setError(new ApiError(payload?.error || "导入失败，请在列表中对失败记录执行重试"));
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

    const anchorHeight = anchor.getBoundingClientRect().height;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - LIGHTNING_TABLE_BOTTOM_GAP);

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
  }, [error, listError, records.length, recordsQuery.isFetching, updateTableScrollY, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY, viewMode]);

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
  }, [updateTableScrollY, viewMode]);

  // 导入中进度直接通过订阅消息 + 表格“状态”列展示，不弹进度条轮询弹窗

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
      if (values.sample_interval_us !== null && values.sample_interval_us !== undefined) {
        formData.append("sample_interval_us", String(values.sample_interval_us));
      }
      if (values.city?.trim()) formData.append("city", values.city.trim());
      if (values.sensor_model?.trim()) formData.append("sensor_model", values.sensor_model.trim());
      if (values.install_position?.trim()) formData.append("install_position", values.install_position.trim());
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());
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
      setSuccess(`导入任务已提交（任务ID: ${payload.task_id}），正在后台处理`);
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
      setError(new ApiError(candidate instanceof Error ? candidate.message : "导入失败"));
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
      setSuccess("雷电流幅值记录已删除");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "删除失败"));
    },
  });

  const retryMutation = useMutation({
    mutationFn: async (record: LightningAmplitudeRecord) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
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
      setSuccess(`重试任务已提交（任务ID: ${payload.task_id}）`);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "重试失败"));
    },
  });

  const backfillMutation = useMutation({
    mutationFn: async (lineIds: string[]) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const failures: string[] = [];
      let successCount = 0;
      for (const lineId of lineIds) {
        try {
          const response = await fetchWithAuth("/api/v1/lightning-currents/prepare-current", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ line_id: lineId }),
          });
          if (!response.ok) {
            failures.push(`线路 ${lineId}: ${await readApiError(response)}`);
          } else {
            successCount += 1;
          }
        } catch (candidate) {
          failures.push(`线路 ${lineId}: ${candidate instanceof Error ? candidate.message : "回填失败"}`);
        }
      }
      return { successCount, failures };
    },
    onSuccess: async ({ successCount, failures }) => {
      setBackfillOpen(false);
      setBackfillRecord(null);
      setBackfillLineIds([]);
      if (failures.length > 0) {
        setSuccess("");
        setError(new ApiError(`回填完成：成功 ${successCount} 条，失败 ${failures.length} 条（${failures.join("；")}）`));
      } else {
        setError(null);
        setSuccess(`回填完成：成功 ${successCount} 条线路`);
      }
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "回填失败"));
    },
  });

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
          label: <span>{truncateFileName(record.source_file_name)}</span>,
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

  const openBackfillLines = (record: LightningAmplitudeRecord) => {
    setBackfillLinesRecord(record);
    setBackfillLinesOpen(true);
  };

  // 回填线路选择：复用现有线路列表接口
  const linesQuery = useQuery<LineListResponse>({
    queryKey: ["lines"],
    enabled: backfillOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

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
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 pb-2 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <Typography.Text strong className="truncate">{record.source_file_name || "-"}</Typography.Text>
            <Tag color={meta.color}>{meta.label}</Tag>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <EnvironmentOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">城市：{record.city || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <HomeOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">安装位置：{record.install_position || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <AppstoreOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">传感器型号：{record.sensor_model || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <NumberOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">采样点数：{record.sample_count}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <ClockCircleOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">采样时间：{formatDateTime(record.event_time) || "-"}</Typography.Text>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 pt-2 border-t border-gray-200">
            {record.status === "processing" ? (
              <Progress percent={record.progress} size="small" className="flex-1 max-w-40" />
            ) : (
              <div />
            )}
            <Space size="small" className="shrink-0">
              <Button
                type="text"
                size="small"
                icon={<EyeOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  openDetail(record);
                }}
              />
              {record.status === "failed" && canManage && (
                <Button
                  type="text"
                  size="small"
                  icon={<RedoOutlined />}
                  loading={retryMutation.isPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    retryMutation.mutate(record);
                  }}
                />
              )}
              {canManage && (
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  loading={deleteMutation.isPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    Modal.confirm({
                      title: "删除记录",
                      content: `确认删除记录 ${record.source_file_name} 吗？将同时删除 MinIO 上的源文件。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: async () => {
                        await deleteMutation.mutateAsync(record);
                      },
                    });
                  }}
                />
              )}
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  const columns = useMemo<ColumnsType<LightningAmplitudeRecord>>(
    () => [
      {
        title: "文件名称",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string) => value || "-",
      },
      {
        title: "城市",
        dataIndex: "city",
        width: 110,
        ellipsis: { showTitle: true },
        render: (value: string | null) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "采样点数",
        dataIndex: "sample_count",
        width: 100,
        render: (value: number) => value ?? 0,
      },
      {
        title: "峰值(kA)",
        dataIndex: "peak_abs_current_ka",
        width: 100,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "极性",
        dataIndex: "polarity",
        width: 90,
        render: (value: LightningPolarity) => formatPolarity(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 160,
        render: (_: unknown, row) => {
          const meta = STATUS_META[row.status] ?? { color: "default", label: row.status };
          const failed = row.status === "failed";
          const statusTag = (
            <Tag color={meta.color}>{meta.label}</Tag>
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
        title: "回填线路数",
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
              {count} 条
            </Button>
          );
        },
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_: unknown, row) => {
          // 统一 UI 规范：默认仅展示 2 个直接按钮（详情/删除），其余条件操作收进 ⋯ 三点下拉
          const moreMenuItems: MenuProps["items"] = [
            ...(canManage
              ? [
                  {
                    key: "backfill",
                    label: "回填",
                    disabled: backfillMutation.isPending,
                    onClick: () => {
                      setBackfillRecord(row);
                      setBackfillLineIds([]);
                      setBackfillOpen(true);
                    },
                  },
                ]
              : []),
            ...(row.status === "failed" && canManage
              ? [
                  {
                    key: "retry",
                    label: "重试",
                    disabled: retryMutation.isPending,
                    onClick: () => retryMutation.mutate(row),
                  },
                ]
              : []),
          ];
          return (
            <Space wrap>
              <Button
                size="small"
                onClick={() => openDetail(row)}
              >
                详情
              </Button>
              {canManage && (
                <Button
                  size="small"
                  danger
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    Modal.confirm({
                      title: "删除记录",
                      content: `确认删除记录 ${row.source_file_name} 吗？将同时删除 MinIO 上的源文件。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: async () => {
                        await deleteMutation.mutateAsync(row);
                      },
                    });
                  }}
                >
                  删除
                </Button>
              )}
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, deleteMutation, retryMutation, backfillMutation, openDetail, openBackfillLines],
  );

  if (initializing) {
    return (
      <AdminPageLoading
        tip="初始化中..."
        minHeightClassName="min-h-[280px]"
      />
    );
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            请先登录后再访问雷电流幅值统计页面。
          </Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `lightning.read`）。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
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
        className="admin-lightning-currents-tabs"
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
            label: <span className="admin-lightning-currents-tab-title">雷电流幅值统计</span>,
            closable: false,
            children: (
              <div className="admin-lightning-currents-list-pane">
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="关键词" className="admin-filter-keyword-item">
              <Input
                allowClear
                placeholder="按文件名/事件编号搜索"
                value={keywordInput}
                onChange={(event) => handleKeywordChange(event.target.value)}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item>
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
                total: Math.max(recordsQuery.data?.total ?? 0, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${recordsQuery.data?.total ?? 0} 条`,
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
                    description="未找到符合筛选条件的记录。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-lightning-events-card-view">
            {recordsQuery.isLoading && records.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[180px]" />
              </div>
            ) : records.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的记录。"
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
                  <Pagination
                    current={pagination.current}
                    pageSize={pagination.pageSize}
                    total={recordsQuery.data?.total ?? 0}
                    onChange={(page, pageSize) => {
                      setPagination({ current: page, pageSize });
                    }}
                    showSizeChanger
                    showTotal={(total) => `共 ${total} 条`}
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
        title="导入雷电流幅值数据"
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
        width={800}
        destroyOnClose
      >
        <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={INITIAL_IMPORT_VALUES}>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="city" label="城市">
              <Select
                showSearch
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
            <Form.Item name="location_tag" label="采样地点">
              <Input placeholder="例如 XX变电站、XX区域" />
            </Form.Item>
            <Form.Item name="install_position" label="安装位置">
              <Input placeholder="例如 楼顶避雷针" />
            </Form.Item>
            <Form.Item name="sensor_model" label="传感器型号">
              <Input placeholder="例如 LCS-1000" />
            </Form.Item>
            <Form.Item name="sample_interval_us" label="采样间隔(us)">
              <InputNumber style={{ width: "100%" }} min={0.000001} precision={6} />
            </Form.Item>
            <Form.Item name="event_time" label="采样时间">
              <DatePicker className="w-full" showTime placeholder="选择日期时间" />
            </Form.Item>
          </div>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="可填写天气背景、场景备注等" />
          </Form.Item>
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
                    message.error(`文件大小超过 ${maxMB}MB 限制，请压缩后重新上传`);
                    return Upload.LIST_IGNORE;
                  }
                  if (!allowedExts.includes(ext)) {
                    message.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
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
                      支持单列电流序列（每行一个值）或双列 time,current 格式。选择文件后立即上传到临时存储。
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
              确认导入
            </Button>
          </div>
        </Form>
      </Modal>

      {/* 回填线路小窗 */}
      <Modal
        title={backfillLinesRecord ? `回填线路 - ${backfillLinesRecord.source_file_name}` : "回填线路"}
        open={backfillLinesOpen}
        onCancel={() => {
          setBackfillLinesOpen(false);
          setBackfillLinesRecord(null);
        }}
        footer={null}
        width={640}
      >
        <Table<LightningAmplitudeBackfillLine>
          rowKey="line_id"
          size="small"
          loading={backfillLinesQuery.isFetching}
          dataSource={backfillLinesQuery.data?.items ?? []}
          tableLayout="fixed"
          pagination={false}
          scroll={{ y: 320 }}
          columns={[
            {
              title: "线路编号",
              dataIndex: "line_code",
              key: "line_code",
              width: 120,
              render: (value: string | null) => value || "-",
            },
            {
              title: "线路名称",
              dataIndex: "line_name",
              key: "line_name",
              width: 150,
              ellipsis: true,
              render: (value: string | null) => value || "-",
            },
            {
              title: "电压(kV)",
              dataIndex: "voltage_kv",
              key: "voltage_kv",
              width: 90,
              render: (value: number | null) => (value == null ? "-" : value),
            },
            {
              title: "current_a",
              dataIndex: "current_a",
              key: "current_a",
              width: 90,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "current_b",
              dataIndex: "current_b",
              key: "current_b",
              width: 90,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "峰值max(kA)",
              dataIndex: "peak_max",
              key: "peak_max",
              width: 100,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "峰值min(kA)",
              dataIndex: "peak_min",
              key: "peak_min",
              width: 100,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "采样数",
              dataIndex: "sampled_event_count",
              key: "sampled_event_count",
              width: 70,
              render: (value: number) => value ?? 0,
            },
            {
              title: "回填时间",
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
                description="该幅值尚未被任何线路回填使用"
              />
            ),
          }}
        />
      </Modal>

      {/* 回填：选择线路列表后执行回填 */}
      <Modal
        title={backfillRecord ? `回填线路 - ${backfillRecord.source_file_name}` : "回填线路"}
        open={backfillOpen}
        onCancel={() => {
          setBackfillOpen(false);
          setBackfillRecord(null);
          setBackfillLineIds([]);
        }}
        onOk={() => {
          if (backfillLineIds.length > 0) {
            backfillMutation.mutate(backfillLineIds);
          }
        }}
        okText="确认回填"
        okButtonProps={{ disabled: backfillLineIds.length === 0, loading: backfillMutation.isPending }}
        width={480}
      >
        <Select
          mode="multiple"
          style={{ width: "100%" }}
          showSearch
          optionFilterProp="label"
          placeholder="搜索并选择线路（可多选）"
          value={backfillLineIds}
          onChange={(value) => setBackfillLineIds(value)}
          loading={linesQuery.isFetching}
          options={(linesQuery.data?.items ?? []).map((line: LineSummary) => ({
            label: `${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`,
            value: line.id,
          }))}
        />
      </Modal>

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
  return (
    <Space direction="vertical" size={12} className="w-full admin-lightning-currents-detail-pane">
      <div>
        <Typography.Title level={5}>基本信息</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="城市">{formatNullable(record.city)}</Descriptions.Item>
          <Descriptions.Item label="采样地点">{formatNullable(record.location_tag)}</Descriptions.Item>
          <Descriptions.Item label="传感器">{formatNullable(record.sensor_model)}</Descriptions.Item>
          <Descriptions.Item label="安装位置">{formatNullable(record.install_position)}</Descriptions.Item>
          <Descriptions.Item label="采样时间">{formatNullable(record.event_time)}</Descriptions.Item>
          <Descriptions.Item label="采样点数">{record.sample_count}</Descriptions.Item>
          <Descriptions.Item label="采样间隔(us)">{formatNumber(record.sample_interval_us, 6)}</Descriptions.Item>
          <Descriptions.Item label="备注">{formatNullable(record.notes)}</Descriptions.Item>
        </Descriptions>
      </div>

      <div>
        <Typography.Title level={5}>波形特征参数</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label={
            <span>
              峰值电流(kA){" "}
              <AntTooltip title="波形序列中绝对值最大的电流值（kA），代表该次雷击的最强瞬间。是衡量雷击强度的核心指标。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.peak_current_ka, 3)}
          </Descriptions.Item>
          <Descriptions.Item label="绝对峰值(kA)">{formatNumber(record.peak_abs_current_ka, 3)}</Descriptions.Item>
          <Descriptions.Item label={
            <span>
              波形分类{" "}
              <AntTooltip title="将实际波形的波前时间（T1）和半峰值时间（T2）与 IEC 标准波形模板匹配，归入最接近的分类：10/350（T1=10μs, T2=350μs，典型直击雷波形）、8/20（T1=8μs, T2=20μs，典型感应雷/测试波形）、1.2/50（T1=1.2μs, T2=50μs，典型操作冲击波形）。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNullable(record.wave_shape)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              极性{" "}
              <AntTooltip title="雷电流的主导方向。自然界约 90% 为负极性雷击，正极性雷击虽少但峰值更大、危害更强。正极性：正峰值大于负峰值；负极性：负峰值大于正峰值；混合：正负峰值相近。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatPolarity(record.polarity)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              波前时间 T1(us){" "}
              <AntTooltip title="电流从峰值的 10% 上升到 90% 所需时间的 1.25 倍（μs），反映雷电流上升的陡度。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.wavefront_time_t1_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              半峰值时间 T2(us){" "}
              <AntTooltip title="从虚拟零点到电流下降到峰值 50% 的时间（μs），反映脉冲宽度。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.half_value_time_t2_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              陡度(kA/us){" "}
              <AntTooltip title="波形中电流变化率的最大值（kA/μs），影响感应过电压的大小。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.steepness_ka_per_us, 6)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              I²t 作用积分(J/Ω){" "}
              <AntTooltip title="电流平方对时间的积分（J/Ω），衡量雷电流的热效应能量。">
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
          <Typography.Title level={5}>多回击峰值分布</Typography.Title>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={record.stroke_peaks_json.map((peak: Record<string, unknown>, idx: number) => ({
              index: idx + 1,
              time_us: Number(peak.time_us) || 0,
              current_ka: Number(peak.current_ka) || 0,
            }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="index" label={{ value: "回击序号", position: "insideBottomRight", offset: -5 }} />
              <YAxis label={{ value: "峰值电流 (kA)", angle: -90, position: "insideLeft", offset: 10 }} />
              <Tooltip
                formatter={(value: TooltipValueType | undefined, name?: string | number) => {
                  if (name === "current_ka") return [formatNumber(Number(value), 3), "峰值电流 (kA)"] as [ReactNode, string | number];
                  if (name === "time_us") return [formatNumber(Number(value), 2), "时间 (μs)"] as [ReactNode, string | number];
                  return [value, name ?? ""] as [ReactNode, string | number];
                }}
                labelFormatter={(label) => `回击 ${label}`}
              />
              <Legend />
              <Line type="monotone" dataKey="current_ka" stroke="#1890ff" name="峰值电流 (kA)" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {record.status === "failed" && (
        <div>
          <Typography.Title level={5}>失败原因</Typography.Title>
          <Typography.Paragraph type="danger">
            {record.error_message || "未知错误"}
          </Typography.Paragraph>
          {canManage && (
            <Button danger loading={retryLoading} onClick={() => onRetry(record)}>
              重试
            </Button>
          )}
        </div>
      )}
    </Space>
  );
}
