"use client";

import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
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
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
  type MenuProps,
} from "antd";
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  FileOutlined,
  FileTextOutlined,
  GlobalOutlined,
  HistoryOutlined,
  NumberOutlined,
  SearchOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { ElevationTowerView } from "@/components/elevation-tower-view";
import { ElevationBackfillHistoryTable } from "@/components/elevation-backfill-history";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { getApiBaseUrl, readApiError } from "@/lib/api";
import type { ElevationDatasetTerrainStatus } from "@/types/auth";

type ElevationFileRecordSummary = {
  id: string;
  file_name: string;
  file_path: string;
  file_format: string;
  file_size: number;
  source: string | null;
  mount_code: string;
  resolution_m: number | null;
  status: string;
  data_source_type: string;
  linked_line_count: number;
  bbox_min_lon: number | null;
  bbox_max_lon: number | null;
  bbox_min_lat: number | null;
  bbox_max_lat: number | null;
  sample_count: number;
  analysis_status: string;
  analysis_task_id: string | null;
  terrain_status: ElevationDatasetTerrainStatus;
  terrain_task_id: string | null;
  terrain_error_message: string | null;
  terrain_url_template: string | null;
  terrain_min_zoom: number | null;
  terrain_max_zoom: number | null;
  terrain_bounds: {
    west: number;
    south: number;
    east: number;
    north: number;
  } | null;
  terrain_metadata: Record<string, unknown> | null;
  notes: string | null;
  create_date: string;
  create_user: string | null;
  update_date: string;
  update_user: string | null;
};

type FileRecordListResponse = {
  items: ElevationFileRecordSummary[];
  total: number;
};

type LineSummary = {
  id: string;
  code: string | null;
  name: string | null;
};

type LineListResponse = {
  items?: LineSummary[];
};

type ElevationFileRecordTaskResponse = {
  record: ElevationFileRecordSummary;
  task_id: string | null;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

type ElevationFileRecordUploadResponse = {
  record: ElevationFileRecordSummary;
  queued: boolean;
  detail: string | null;
  warnings: string[];
};

type ElevationTempUploadResponse = {
  temp_file_id: string;
  file_name: string;
};

type ElevationLinkedLineSummary = {
  line_id: string;
  line_code: string | null;
  line_name: string | null;
  voltage_kv: number | null;
  apply_status: string;
  tower_count: number;
  updated_tower_count: number;
  applied_at: string | null;
};

type ElevationLinkedLineListResponse = {
  items: ElevationLinkedLineSummary[];
  total: number;
};

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

type UploadFormValues = {
  source?: string;
  resolution_m?: number;
  notes?: string;
};

type ApplyFormValues = {
  line_id: string;
  file_record_id: string;
  mode: "fill_null_only" | "overwrite_all";
};

const DEFAULT_APPLY_FORM: ApplyFormValues = {
  line_id: "",
  file_record_id: "",
  mode: "fill_null_only",
};

const ELEVATION_TABLE_MIN_SCROLL_Y = 180;
const ELEVATION_TABLE_VIEWPORT_GAP = 40;
const ELEVATION_TABLE_FALLBACK_RESERVE = 220;

function statusTagColor(status: string): string {
  if (status === "success" || status === "active" || status === "ready") return "green";
  if (status === "running" || status === "processing") return "blue";
  if (status === "pending" || status === "queued") return "orange";
  if (status === "failed" || status === "disabled") return "red";
  return "default";
}

function applyStatusLabel(status: string): string {
  if (status === "success") return "成功";
  if (status === "running") return "处理中";
  if (status === "pending") return "待处理";
  if (status === "failed") return "失败";
  return status;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

type ParseStatusInfo = { label: string; color: string };

function computedParseStatus(record: ElevationFileRecordSummary): ParseStatusInfo {
  const { analysis_status, terrain_status, status } = record;

  // Any failed/disabled → 失败
  if (
    analysis_status === "failed" ||
    terrain_status === "failed" ||
    status === "disabled"
  ) {
    return { label: "失败", color: "red" };
  }

  // Any running/processing/queued/pending → 处理中
  const processingStates = ["running", "queued", "pending", "processing"];
  if (
    processingStates.includes(analysis_status) ||
    processingStates.includes(terrain_status)
  ) {
    return { label: "处理中", color: "blue" };
  }

  // Otherwise → 成功（含分析完成且地形就绪或格式不支持等正常状态）
  return { label: "成功", color: "green" };
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return (await response.json()) as T;
}

async function ensureOkResponse(response: Response): Promise<void> {
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
}

function readMutationError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function ElevationRecordsPage() {
  const { fetchWithAuth, getAccessToken } = useAuth();
  const queryClient = useQueryClient();

  const [uploadForm] = Form.useForm();
  const [applyForm] = Form.useForm<ApplyFormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(ELEVATION_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<ElevationFileRecordSummary | null>(null);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 动态详情 Tab（参照 lightning-distribution LP-264 的 detailTabs 机制）
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  // 关联线路小窗
  const [linkedLinesModalOpen, setLinkedLinesModalOpen] = useState(false);
  const [linkedLinesRecord, setLinkedLinesRecord] = useState<ElevationFileRecordSummary | null>(null);

  // Fetch file records
  const { data: recordsData, isLoading } = useQuery<FileRecordListResponse>({
    queryKey: ["elevation-records", searchKeyword, pagination.current, pagination.pageSize],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pagination.pageSize));
      params.set("offset", String((pagination.current - 1) * pagination.pageSize));
      if (searchKeyword) params.append("keyword", searchKeyword);
      const query = params.toString();
      const response = await fetchWithAuth(`/api/v1/elevation/records?${query}`);
      return readJsonResponse<FileRecordListResponse>(response);
    },
  });

  // Fetch lines for apply dialog
  const { data: linesData } = useQuery({
    queryKey: ["lines"],
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/lines?limit=1000");
      return readJsonResponse<LineListResponse>(response);
    },
  });

  const records = useMemo(() => recordsData?.items ?? [], [recordsData?.items]);

  // Subscribe to real-time updates
  useTopicSubscription("admin.elevation", () => {
    queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
  });

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: async (values: UploadFormValues) => {
      if (!tempFileId) {
        throw new Error("文件尚未上传完成，请等待上传后再确认");
      }
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      if (values.source?.trim()) formData.append("source", values.source.trim());
      if (values.resolution_m) formData.append("resolution_m", values.resolution_m.toString());
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());
      formData.append("trigger_analysis", "true");

      const response = await fetchWithAuth("/api/v1/elevation/records", {
        method: "POST",
        body: formData,
      });
      return readJsonResponse<ElevationFileRecordUploadResponse>(response);
    },
    onSuccess: () => {
      message.success("文件上传成功");
      setUploadModalOpen(false);
      uploadForm.resetFields();
      resetTempUploadState();
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      message.error(readMutationError(error, "上传失败"));
    },
  });

  // 选择文件后立即上传到临时目录（与地闪密度导入统一的两段式交互）
  const handleTempUpload = useCallback(
    (file: File) => {
      setSelectedFile(file);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getApiBaseUrl()}/api/v1/elevation/upload-temp`);
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
            const payload = JSON.parse(xhr.responseText) as ElevationTempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError("上传成功但响应解析失败，请重新选择文件");
          }
          return;
        }
        let messageText = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) messageText = parsed.detail;
        } catch {
          // 忽略非 JSON 响应
        }
        setUploadError(messageText);
      };
      xhr.onerror = () => setUploadError("网络异常，上传失败");
      xhr.onabort = () => setUploadError("上传已取消");

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [getAccessToken],
  );

  const resetTempUploadState = useCallback(() => {
    setSelectedFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
  }, []);

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${id}`, {
        method: "DELETE",
      });
      await ensureOkResponse(response);
    },
    onMutate: (id) => {
      setDeletingId(id);
    },
    onSuccess: () => {
      message.success("删除成功");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      message.error(readMutationError(error, "删除失败"));
    },
    onSettled: () => setDeletingId(null),
  });

  // Analyze mutation
  const analyzeMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${id}/analyze`, {
        method: "POST",
      });
      return readJsonResponse<ElevationFileRecordTaskResponse>(response);
    },
    onMutate: (id) => {
      setAnalyzingId(id);
    },
    onSuccess: () => {
      message.success("分析任务已提交");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      message.error(readMutationError(error, "分析失败"));
    },
    onSettled: () => setAnalyzingId(null),
  });

  // Terrain build mutation
  const terrainMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${id}/terrain/build`, {
        method: "POST",
      });
      return readJsonResponse<ElevationFileRecordTaskResponse>(response);
    },
    onSuccess: () => {
      message.success("地形瓦片任务已提交");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      message.error(readMutationError(error, "地形生成失败"));
    },
  });

  // Apply mutation
  const applyMutation = useMutation({
    mutationFn: async (values: ApplyFormValues) => {
      const response = await fetchWithAuth("/api/v1/elevation/jobs/apply-line", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      return readJsonResponse(response);
    },
    onSuccess: () => {
      message.success("回填任务已创建");
      setApplyModalOpen(false);
      applyForm.resetFields();
    },
    onError: (error) => {
      message.error(readMutationError(error, "创建任务失败"));
    },
  });

  // 关联线路明细（小窗）
  const linkedLinesQuery = useQuery<ElevationLinkedLineListResponse>({
    queryKey: ["elevation-records", linkedLinesRecord?.id, "linked-lines"],
    enabled: !!linkedLinesRecord,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${linkedLinesRecord?.id}/linked-lines`);
      return readJsonResponse<ElevationLinkedLineListResponse>(response);
    },
  });

  const openLinkedLinesModal = (record: ElevationFileRecordSummary) => {
    setLinkedLinesRecord(record);
    setLinkedLinesModalOpen(true);
  };

  // 打开回填弹窗
  const openApplyModal = useCallback((record: ElevationFileRecordSummary) => {
    setSelectedRecord(record);
    applyForm.setFieldsValue({
      file_record_id: record.id,
      line_id: "",
      mode: "fill_null_only",
    });
    setApplyModalOpen(true);
  }, [applyForm]);

  // 打开回填记录 Tab
  const openBackfillHistoryTab = useCallback((record: ElevationFileRecordSummary) => {
    const key = `backfill-history-${record.id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: (
            <Space size={6}>
              <span>{record.file_name}</span>
              <Tag color="geekblue">回填记录</Tag>
            </Space>
          ),
          closable: true,
          children: (
            <ElevationBackfillHistoryTable recordId={record.id} />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, []);

  // 打开回填数据 Tab（key 用 towers-{record.id} 去重，已存在只切换）
  const openTowerTab = useCallback((record: ElevationFileRecordSummary) => {
    const key = `towers-${record.id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: (
            <Space size={6}>
              <span>{record.file_name}</span>
              <Tag color="blue">回填数据</Tag>
            </Space>
          ),
          closable: true,
          children: (
            <ElevationTowerView
              record={record}
              fetchWithAuth={fetchWithAuth}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth]);

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

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorTop = anchor.getBoundingClientRect().top;
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - ELEVATION_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? ELEVATION_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - ELEVATION_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(ELEVATION_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [pagination.current, pagination.pageSize, records.length, isLoading, updateTableScrollY]);

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
  }, [updateTableScrollY]);

  const columns: ColumnsType<ElevationFileRecordSummary> = [
    {
      title: "文件名",
      dataIndex: "file_name",
      key: "file_name",
      width: 250,
      ellipsis: true,
    },
    {
      title: "格式",
      dataIndex: "file_format",
      key: "file_format",
      width: 80,
      render: (text) => <Tag>{text.toUpperCase()}</Tag>,
    },
    {
      title: "大小",
      dataIndex: "file_size",
      key: "file_size",
      width: 100,
      render: (size) => formatFileSize(size),
    },
    {
      title: "来源",
      dataIndex: "source",
      key: "source",
      width: 150,
      ellipsis: true,
    },
    {
      title: "分辨率(m)",
      dataIndex: "resolution_m",
      key: "resolution_m",
      width: 100,
      render: (val) => (val ? val.toFixed(1) : "-"),
    },
    {
      title: "样本数",
      dataIndex: "sample_count",
      key: "sample_count",
      width: 100,
      render: (val) => val.toLocaleString(),
    },
    {
      title: "解析状态",
      key: "parse_status",
      width: 120,
      render: (_value, record) => {
        const { label, color } = computedParseStatus(record);
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: "关联线路",
      key: "linked_lines",
      width: 100,
      render: (_value, record) => (
        <Button
          type="link"
          size="small"
          style={{ padding: 0 }}
          onClick={() => openLinkedLinesModal(record)}
        >
          {record.linked_line_count ?? 0} 条
        </Button>
      ),
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 140,
      render: (_value, row) => {
        const analyzing = analyzeMutation.isPending && analyzingId === row.id;
        const deleting = deleteMutation.isPending && deletingId === row.id;
        const rowBusy = analyzing || deleting;

        const moreMenuItems: MenuProps["items"] = [];

        return (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy}
              onClick={() => openApplyModal(row)}
            >
              回填
            </Button>

            <Button
              size="small"
              disabled={rowBusy}
              onClick={() => openBackfillHistoryTab(row)}
            >
              回填记录
            </Button>

            <Button danger size="small" loading={deleting} disabled={rowBusy}
              onClick={() => {
                Modal.confirm({
                  title: `确认删除文件 "${row.file_name}"？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true, loading: deleting },
                  onOk: () => deleteMutation.mutate(row.id),
                });
              }}
            >
              删除
            </Button>
          </Space>
        );
      },
    },
  ];

  const renderRecordCard = (record: ElevationFileRecordSummary) => {
    const analyzing = analyzeMutation.isPending && analyzingId === record.id;
    const deleting = deleteMutation.isPending && deletingId === record.id;
    const rowBusy = analyzing || deleting;

    return (
      <Card
        key={record.id}
        className="admin-elevation-record-card"
        size="small"
        hoverable
        onClick={() => openTowerTab(record)}
      >
        <div className="flex flex-col">
          <div className="admin-elevation-record-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <FileOutlined className="text-base text-gray-500" />
            <Typography.Text strong className="truncate min-w-0 flex-1">{record.file_name}</Typography.Text>
            <Tag color={statusTagColor(record.status)}>{record.status}</Tag>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <FileTextOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs">格式：</Typography.Text>
              <Tag className="text-xs">{record.file_format.toUpperCase()}</Tag>
            </div>
            <div className="flex items-center gap-2">
              <GlobalOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">来源：{record.source ?? "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <AppstoreOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">分辨率：{record.resolution_m ? `${record.resolution_m.toFixed(1)} m` : "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <NumberOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">样本数：{record.sample_count.toLocaleString()}</Typography.Text>
            </div>
          </div>

          <div className="admin-elevation-record-card-actions flex justify-end px-4 py-2 border-t border-gray-200">
            <Space size="small">
                          <Tooltip title="应用">
                            <Button
                              type="text"
                              size="small"
                              icon={<CloudUploadOutlined />}
                              disabled={rowBusy}
                              onClick={(event) => {
                                event.stopPropagation();
                                openTowerTab(record);
                              }}
                            />
                          </Tooltip>
                        </Space>
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="admin_elevation_tabs"
        tabBarExtraContent={
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
            导入
          </Button>
        }
        items={[
          {
            key: "list",
            label: <span className="admin_elevation_tab_title">高程数据管理</span>,
            closable: false,
            children: (
              <div className="admin_elevation_list_pane">
                <div className="admin-filter-bar">
                  <Form layout="inline" style={{ flexWrap: "nowrap" }}>
                    <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder="搜索文件名或来源"
                        value={keywordInput}
                        onChange={(event) => handleKeywordChange(event.target.value)}
                        onPressEnter={(e) => {
                          const value = (e.target as HTMLInputElement).value;
                          setSearchKeyword(value);
                          setPagination((prev) => ({ ...prev, current: 1 }));
                        }}
                        style={{ textOverflow: "ellipsis", overflow: "hidden" }}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={() => {
                          setSearchKeyword(keywordInput);
                          setPagination((prev) => ({ ...prev, current: 1 }));
                          void queryClient.refetchQueries({ queryKey: ["elevation-records"] });
                        }}
                        className="admin-search-btn"
                      >
                        查询
                      </Button>
                    </Form.Item>
                  </Form>
                  <Segmented
                    value={viewMode}
                    onChange={(value) => {
                      setViewMode(value as "card" | "list");
                      setPagination((prev) => ({ ...prev, current: 1 }));
                    }}
                    options={[
                      { label: "卡片视图", value: "card" },
                      { label: "列表视图", value: "list" },
                    ]}
                  />
                </div>

                {viewMode === "list" ? (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-elevation-table-anchor"
                    style={{ "--admin-elevation-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<ElevationFileRecordSummary>
                      rowKey="id"
                      dataSource={records}
                      columns={columns}
                      loading={isLoading}
                      tableLayout="fixed"
                      pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total: Math.max(recordsData?.total ?? 0, 1),
                        showSizeChanger: true,
                        pageSizeOptions: [10, 20, 50],
                        showTotal: () => `共 ${recordsData?.total ?? 0} 条`,
                        hideOnSinglePage: false,
                        style: { marginBottom: 0 },
                        onChange: (page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        },
                      }}
                      scroll={{ y: tableScrollY }}
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到符合筛选条件的高程数据。"
                          />
                        ),
                      }}
                    />
                  </div>
                ) : (
                  <div className="admin-elevation-card-view">
                    {isLoading ? (
                      <div className="admin-elevation-card-view-state">
                        <Spin tip="加载中..." />
                      </div>
                    ) : records.length === 0 ? (
                      <div className="admin-elevation-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="未找到符合筛选条件的高程数据。"
                        />
                      </div>
                    ) : (
                      <>
                        <div className="admin-elevation-card-view-content">
                          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                            {records.map((recordItem) => (
                              renderRecordCard(recordItem)
                            ))}
                          </div>
                        </div>
                        <div className="admin-power-lines-pagination">
                          <Pagination
                            current={pagination.current}
                            pageSize={pagination.pageSize}
                            total={Math.max(recordsData?.total ?? 0, 1)}
                            showSizeChanger
                            showTotal={(total) => `共 ${total} 条`}
                            onChange={(page, pageSize) => {
                              setPagination({ current: page, pageSize });
                            }}
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

      {/* Upload Modal */}
      <Modal
        title="上传高程文件"
        open={uploadModalOpen}
        onCancel={() => {
          setUploadModalOpen(false);
          uploadForm.resetFields();
          resetTempUploadState();
        }}
        onOk={() => uploadForm.submit()}
        confirmLoading={uploadMutation.isPending}
        okButtonProps={{ disabled: !tempFileId }}
        width={600}
      >
        <Form
          form={uploadForm}
          layout="vertical"
          onFinish={(values) => uploadMutation.mutate(values)}
        >
          <Form.Item
            label="文件"
            required
            help="选择文件后立即上传到临时存储，支持 .tif/.tiff 和 .zip 格式"
          >
            <Upload.Dragger
              accept=".tif,.tiff,.zip"
              showUploadList={false}
              beforeUpload={(file) => {
                const allowedExts = ["tif", "tiff", "zip"];
                const ext = file.name.split(".").pop()?.toLowerCase() || "";
                if (!allowedExts.includes(ext)) {
                  message.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
                  return Upload.LIST_IGNORE;
                }
                handleTempUpload(file as File);
                return Upload.LIST_IGNORE;
              }}
              onRemove={() => resetTempUploadState()}
            >
              {selectedFile ? (
                <>
                  <p className="ant-upload-text">{selectedFile.name}</p>
                  {uploadProgress < 100 ? (
                    <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                  ) : tempFileId ? (
                    <Typography.Text type="success">
                      <CheckCircleOutlined /> 上传完成，可以确认提交
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="warning">上传中…</Typography.Text>
                  )}
                </>
              ) : (
                <>
                  <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                    点击或拖拽文件到此区域上传
                  </p>
                  <Typography.Text type="secondary">
                    支持 .tif/.tiff 和 .zip 格式（DEM 可达几十 MB），选择文件后立即上传到临时存储。
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

          <Form.Item label="来源" name="source">
            <Input placeholder="例如：SRTM、DEM 数据" />
          </Form.Item>

          <Form.Item label="分辨率(米)" name="resolution_m">
            <InputNumber min={0.1} step={0.1} style={{ width: "100%" }} placeholder="例如：30" />
          </Form.Item>

          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={3} placeholder="文件说明..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* Apply Modal */}
      <Modal
        title="回填线路高程"
        open={applyModalOpen}
        onCancel={() => {
          setApplyModalOpen(false);
          applyForm.resetFields();
        }}
        onOk={() => applyForm.submit()}
        confirmLoading={applyMutation.isPending}
        width={600}
      >
        {selectedRecord && (
          <Alert
            message={`将使用文件: ${selectedRecord.file_name}`}
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}
        <Form form={applyForm} layout="vertical" onFinish={(values) => applyMutation.mutate(values)}>
          <Form.Item name="file_record_id" hidden>
            <Input />
          </Form.Item>

          <Form.Item label="选择线路" name="line_id" rules={[{ required: true, message: "请选择线路" }]}>
            <Select
              placeholder="选择线路"
              showSearch
              optionFilterProp="label"
              options={linesData?.items?.map((line) => ({
                label: `${line.code ?? "-"} - ${line.name ?? "-"}`,
                value: line.id,
              }))}
            />
          </Form.Item>

          <Form.Item
            label="回填模式"
            name="mode"
            rules={[{ required: true }]}
            initialValue="fill_null_only"
          >
            <Select
              options={[
                { label: "仅填空（只更新空值）", value: "fill_null_only" },
                { label: "全部覆盖（覆盖所有数据）", value: "overwrite_all" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 关联线路小窗 */}
      <Modal
        title={linkedLinesRecord ? `关联线路 - ${linkedLinesRecord.file_name}` : "关联线路"}
        open={linkedLinesModalOpen}
        onCancel={() => {
          setLinkedLinesModalOpen(false);
          setLinkedLinesRecord(null);
        }}
        footer={null}
        width={560}
      >
        <Table<ElevationLinkedLineSummary>
          rowKey="line_id"
          size="small"
          loading={linkedLinesQuery.isFetching}
          dataSource={linkedLinesQuery.data?.items ?? []}
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
              width: 140,
              ellipsis: true,
              render: (value: string | null) => value || "-",
            },
            {
              title: "电压(kV)",
              dataIndex: "voltage_kv",
              key: "voltage_kv",
              width: 80,
              render: (value: number | null) => (value == null ? "-" : value),
            },
            {
              title: "回填状态",
              dataIndex: "apply_status",
              key: "apply_status",
              width: 90,
              render: (value: string) => (
                <Tag color={statusTagColor(value)}>{applyStatusLabel(value)}</Tag>
              ),
            },
            {
              title: "杆塔数",
              dataIndex: "tower_count",
              key: "tower_count",
              width: 70,
              render: (value: number) => value ?? 0,
            },
            {
              title: "更新数",
              dataIndex: "updated_tower_count",
              key: "updated_tower_count",
              width: 70,
              render: (value: number) => value ?? 0,
            },
            {
              title: "回填时间",
              dataIndex: "applied_at",
              key: "applied_at",
              width: 150,
              render: (value: string | null) => (value ? formatDateTime(value) : "-"),
            },
          ]}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无回填线路"
              />
            ),
          }}
        />
      </Modal>
    </div>
  );
}
