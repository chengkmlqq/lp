"use client";

import type { CSSProperties, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Badge,
  Button,
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
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  FileOutlined,
  FileTextOutlined,
  HistoryOutlined,
  InboxOutlined,
  MoreOutlined,
  NumberOutlined,
  SearchOutlined,
  SendOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { ElevationBackfillHistoryTable } from "@/components/elevation-backfill-history";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { downloadFileWithAuth, getApiBaseUrl, readApiError } from "@/lib/api";
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
  // 高程文件覆盖范围（bbox），用于回填线路选择的范围标记
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
  voltage_kv: number | null;
  bbox_overlap: boolean | null;
};

type LineListResponse = {
  items?: LineSummary[];
};

// 回填覆盖预检（逐塔采样统计可回填杆塔数）
type BackfillCoverageLine = {
  line_id: string;
  line_code: string | null;
  line_name: string | null;
  voltage_kv: number | null;
  total_tower_count: number;
  matchable_tower_count: number;
};

type BackfillCoverageResponse = {
  file_record_id: string;
  items: BackfillCoverageLine[];
  total: number;
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

type EditFormValues = {
  source?: string;
  resolution_m?: number;
  notes?: string;
};

type ApplyFormValues = {
  line_ids: string[];
  file_record_id: string;
};

const ELEVATION_TABLE_MIN_SCROLL_Y = 180;
const ELEVATION_TABLE_VIEWPORT_GAP = 40;
const ELEVATION_TABLE_FALLBACK_RESERVE = 220;

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "-";
  }
  const K = 1024;
  const M = K * 1024;
  const G = M * 1024;
  const T = G * 1024;
  if (bytes >= T) return `${(bytes / T).toFixed(2)} T`;
  if (bytes >= G) return `${(bytes / G).toFixed(2)} G`;
  if (bytes >= M) return `${(bytes / M).toFixed(2)} M`;
  if (bytes >= K) return `${(bytes / K).toFixed(2)} K`;
  return `${bytes} B`;
}

type ParseStatusInfo = { label: string; color: "success" | "processing" | "error" };

function computedParseStatus(record: ElevationFileRecordSummary): ParseStatusInfo {
  const { analysis_status, terrain_status, status } = record;

  // Any failed/disabled → 失败
  if (
    analysis_status === "failed" ||
    terrain_status === "failed" ||
    status === "disabled"
  ) {
    return { label: "失败", color: "error" };
  }

  // 分析任务进行中（含排队未开始）→ 处理中
  const activeAnalysisStates = ["running", "queued", "pending", "processing"];
  if (activeAnalysisStates.includes(analysis_status)) {
    return { label: "处理中", color: "processing" };
  }

  // 地形瓦片构建链已下线（LP-457）：新建记录 terrain_status 默认 "pending" 且永不推进，
  // 不再视为处理中；仅历史遗留的真实进行中构建（processing/running）保持处理中
  const activeTerrainStates = ["processing", "running"];
  if (activeTerrainStates.includes(terrain_status)) {
    return { label: "处理中", color: "processing" };
  }

  // Otherwise → 成功（含分析完成且地形就绪/不支持等正常状态）
  return { label: "成功", color: "success" };
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
  const { t } = useI18n();
  const { message: messageApi } = App.useApp();
  const { fetchWithAuth, getAccessToken, hasPermission } = useAuth();
  const queryClient = useQueryClient();

  const canRead = hasPermission("elevation.read") || hasPermission("elevation.manage");
  const canManage = hasPermission("elevation.manage");

  const [uploadForm] = Form.useForm();
  const [applyForm] = Form.useForm<ApplyFormValues>();
  const [editForm] = Form.useForm<EditFormValues>();

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
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingRecord, setEditingRecord] = useState<ElevationFileRecordSummary | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // 动态详情 Tab（参照 lightning-distribution LP-264 的 detailTabs 机制）
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);

  // Fetch file records
  const { data: recordsData, isLoading, isFetching: recordsFetching } = useQuery<FileRecordListResponse>({
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

  // 回填覆盖预检：选中高程文件+打开回填弹窗时，逐塔采样统计每条候选线路的可回填杆塔数。
  // DEM 可能在局部区域无数据（NoData），单看外包矩形/有效范围会漏判（线路能选到但回填全未命中）。
  // 这里直接对每条线路的每座塔真实采样，matchable_tower_count=0 的线路不可回填（禁用并标注）。
  const { data: coverageData, isLoading: coverageLoading } = useQuery<BackfillCoverageResponse>({
    queryKey: ["elevation-backfill-coverage", selectedRecord?.id],
    enabled: !!selectedRecord?.id && applyModalOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/elevation/records/${selectedRecord!.id}/lines-preview`,
      );
      return readJsonResponse<BackfillCoverageResponse>(response);
    },
  });

  // coverage 结果按 line_id 映射，供弹窗 Select 判断可用性
  const coverageMap = useMemo(() => {
    const map = new Map<string, BackfillCoverageLine>();
    for (const item of coverageData?.items ?? []) {
      map.set(item.line_id, item);
    }
    return map;
  }, [coverageData]);

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
      messageApi.success("文件上传成功");
      setUploadModalOpen(false);
      uploadForm.resetFields();
      resetTempUploadState();
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "上传失败"));
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
      messageApi.success("删除成功");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "删除失败"));
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
      messageApi.success("分析任务已提交");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "分析失败"));
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
      messageApi.success("地形瓦片任务已提交");
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "地形生成失败"));
    },
  });

  // 下载原始高程文件（保持上传时的原始格式，单文件逐个下载）
  const handleDownloadSource = useCallback(async (record: ElevationFileRecordSummary) => {
    try {
      await downloadFileWithAuth(
        `/api/v1/elevation/records/${record.id}/download`,
        record.file_name || "elevation.tif",
      );
    } catch (error) {
      messageApi.error(readMutationError(error, "下载失败"));
    }
  }, [messageApi]);

  // 编辑文件记录（来源/分辨率/备注）mutation
  const editMutation = useMutation({
    mutationFn: async (args: { id: string; values: EditFormValues }) => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${args.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: args.values.source?.trim() || null,
          resolution_m: args.values.resolution_m ?? null,
          notes: args.values.notes?.trim() || null,
        }),
      });
      return readJsonResponse<ElevationFileRecordSummary>(response);
    },
    onMutate: (args) => {
      setEditingId(args.id);
    },
    onSuccess: () => {
      messageApi.success("保存成功");
      setEditModalOpen(false);
      setEditingRecord(null);
      editForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "保存失败"));
    },
    onSettled: () => setEditingId(null),
  });

  // Apply mutation（支持一次勾选多条线路，逐条创建回填任务）
  const applyMutation = useMutation({
    mutationFn: async (values: ApplyFormValues) => {
      const lineIds = Array.from(new Set(values.line_ids ?? []));
      if (lineIds.length === 0) {
        throw new Error("请选择至少一条线路");
      }
      const failed: Array<{ line_id: string; detail: string }> = [];
      for (const lineId of lineIds) {
        try {
          const response = await fetchWithAuth("/api/v1/elevation/jobs/apply-line", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              line_id: lineId,
              file_record_id: values.file_record_id,
              mode: "overwrite_all",
            }),
          });
          if (!response.ok) {
            failed.push({ line_id: lineId, detail: await readApiError(response) });
          }
        } catch (error) {
          failed.push({
            line_id: lineId,
            detail: error instanceof Error && error.message ? error.message : "请求失败",
          });
        }
      }
      const createdCount = lineIds.length - failed.length;
      if (failed.length > 0) {
        throw new Error(
          `成功创建 ${createdCount} 个，失败 ${failed.length} 个（${failed.map((item) => item.detail).join("；")}）`,
        );
      }
      return { createdCount };
    },
    onSuccess: (data) => {
      messageApi.success(`已创建 ${data.createdCount} 个回填任务`);
      setApplyModalOpen(false);
      applyForm.resetFields();
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      messageApi.error(readMutationError(error, "创建任务失败"));
    },
  });

  // 打开回填弹窗
  const openApplyModal = useCallback((record: ElevationFileRecordSummary) => {
    setSelectedRecord(record);
    applyForm.setFieldsValue({
      file_record_id: record.id,
      line_ids: [],
    });
    setApplyModalOpen(true);
  }, [applyForm]);

  // 打开编辑弹窗（来源/分辨率/备注）
  const openEditModal = useCallback((record: ElevationFileRecordSummary) => {
    setEditingRecord(record);
    editForm.setFieldsValue({
      source: record.source ?? "",
      resolution_m: record.resolution_m ?? undefined,
      notes: record.notes ?? "",
    });
    setEditModalOpen(true);
  }, [editForm]);

  const closeEditModal = useCallback(() => {
    setEditModalOpen(false);
    setEditingRecord(null);
    editForm.resetFields();
  }, [editForm]);

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
            <span>{record.file_name}</span>
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
      title: t("文件名"),
      dataIndex: "file_name",
      key: "file_name",
      width: 250,
      ellipsis: true,
    },
    {
      title: t("格式"),
      dataIndex: "file_format",
      key: "file_format",
      width: 80,
      render: (text) => <Tag>{text.toUpperCase()}</Tag>,
    },
    {
      title: t("大小"),
      dataIndex: "file_size",
      key: "file_size",
      width: 100,
      render: (size) => formatFileSize(size),
    },
    {
      title: t("来源"),
      dataIndex: "source",
      key: "source",
      width: 150,
      ellipsis: true,
    },
    {
      title: t("分辨率(m)"),
      dataIndex: "resolution_m",
      key: "resolution_m",
      width: 100,
      render: (val) => (val ? val.toFixed(1) : "-"),
    },
    {
      title: t("样本数"),
      dataIndex: "sample_count",
      key: "sample_count",
      width: 100,
      render: (val) => val.toLocaleString(),
    },
    {
      title: t("解析状态"),
      key: "parse_status",
      width: 120,
      render: (_value, record) => {
        const { label, color } = computedParseStatus(record);
        return <Tag color={color}>{label}</Tag>;
      },
    },
    {
      title: t("操作"),
      key: "actions",
      fixed: "right",
      width: 180,
      render: (_value, row) => {
        const analyzing = analyzeMutation.isPending && analyzingId === row.id;
        const deleting = deleteMutation.isPending && deletingId === row.id;
        const editing = editMutation.isPending && editingId === row.id;
        const rowBusy = analyzing || deleting || editing;

        return canManage ? (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy}
              onClick={() => {
                void handleDownloadSource(row);
              }}
            >
              下载
            </Button>

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
              onClick={() => openEditModal(row)}
            >
              编辑
            </Button>

            <Dropdown
              menu={{
                items: [
                  {
                    key: "backfill-history",
                    label: t("回填记录"),
                    icon: <HistoryOutlined />,
                    disabled: rowBusy,
                    onClick: () => openBackfillHistoryTab(row),
                  },
                  {
                    key: "delete",
                    label: t("删除"),
                    icon: <DeleteOutlined />,
                    danger: true,
                    disabled: rowBusy,
                    onClick: () => {
                      Modal.confirm({
                        title: `确认删除文件 "${row.file_name}"？`,
                        okText: t("删除"),
                        cancelText: t("取消"),
                        okButtonProps: { danger: true, loading: deleting },
                        onOk: () => deleteMutation.mutate(row.id),
                      });
                    },
                  },
                ],
              }}
              trigger={["click"]}
            >
              <Tooltip title={t("更多")}>
                <Button
                  type="text"
                  size="small"
                  disabled={rowBusy}
                  icon={<MoreOutlined />}
                />
              </Tooltip>
            </Dropdown>
          </Space>
        ) : (
          <span style={{ color: "rgba(0,0,0,0.25)" }}>—</span>
        );
      },
    },
  ];

  const renderRecordCard = (record: ElevationFileRecordSummary) => {
    const analyzing = analyzeMutation.isPending && analyzingId === record.id;
    const deleting = deleteMutation.isPending && deletingId === record.id;
    const editing = editMutation.isPending && editingId === record.id;
    const rowBusy = analyzing || deleting || editing;
    const recordStatus = computedParseStatus(record);
    // 分析生命周期：queued（已提交）→ running（执行中）→ success/failed；
    // 进行中即展示底部进度条（分析无增量进度数据，用全宽动画条表示处理中）
    const showProgress = ["queued", "running", "processing"].includes(record.analysis_status) ||
      ["processing", "running"].includes(record.terrain_status);

    return (
      <Card
        key={record.id}
        className="admin-elevation-record-card"
        size="small"
        hoverable
        onClick={() => openBackfillHistoryTab(record)}
      >
        <div className="flex flex-col">
          <div className="admin-elevation-record-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <FileOutlined className="text-base text-gray-500" />
            <Typography.Text strong className="truncate min-w-0 flex-1">{record.file_name}</Typography.Text>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Badge status={recordStatus.color as Parameters<typeof Badge>[0]["status"]} />
              <Typography.Text type="secondary" className="text-xs">{recordStatus.label}</Typography.Text>
            </div>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <FileTextOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs">{t("格式：")}</Typography.Text>
              <Tag color="blue" className="text-xs">{record.file_format.toUpperCase()}</Tag>
            </div>
            <div className="flex items-center gap-2">
              <DatabaseOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs min-w-0 truncate">大小：{formatFileSize(record.file_size)}</Typography.Text>
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

          <div className="admin-elevation-record-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {showProgress ? (
              <Progress percent={100} size="small" className="flex-1 max-w-40" showInfo={false} status="active" />
            ) : (
              <div />
            )}
            <Space size={4} className="shrink-0">
              <Tooltip title={t("编辑")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  disabled={rowBusy}
                  onClick={(event) => {
                    event.stopPropagation();
                    openEditModal(record);
                  }}
                />
              </Tooltip>
              <Tooltip title={t("回填")}>
                <Button
                  type="text"
                  size="small"
                  icon={<SendOutlined />}
                  disabled={rowBusy}
                  onClick={(event) => {
                    event.stopPropagation();
                    openApplyModal(record);
                  }}
                />
              </Tooltip>
              <Dropdown
                menu={{
                  items: [
                    {
                      key: "backfill-history",
                      label: t("回填记录"),
                      icon: <HistoryOutlined />,
                      disabled: rowBusy,
                      onClick: (info) => {
                        info.domEvent?.stopPropagation();
                        openBackfillHistoryTab(record);
                      },
                    },
                    {
                      key: "delete",
                      label: t("删除"),
                      icon: <DeleteOutlined />,
                      danger: true,
                      disabled: rowBusy,
                      onClick: (info) => {
                        info.domEvent?.stopPropagation();
                        Modal.confirm({
                          title: `确认删除文件 "${record.file_name}"？`,
                          okText: t("删除"),
                          cancelText: t("取消"),
                          okButtonProps: { danger: true, loading: deleting },
                          onOk: () => deleteMutation.mutate(record.id),
                        });
                      },
                    },
                  ],
                }}
                trigger={["click"]}
              >
                <Tooltip title={t("更多")}>
                  <Button
                    type="text"
                    size="small"
                    disabled={rowBusy}
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
          canManage ? (
            <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
              导入
            </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: <span className="admin_elevation_tab_title">{t("高程数据管理")}</span>,
            closable: false,
            children: (
              <div className="admin_elevation_list_pane">
                <div className="admin-filter-bar">
                  <Form layout="inline" style={{ flexWrap: "nowrap" }}>
                    <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("搜索文件名或来源")}
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
                    <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={() => {
                          setSearchKeyword(keywordInput);
                          setPagination((prev) => ({ ...prev, current: 1 }));
                          void queryClient.refetchQueries({ queryKey: ["elevation-records"] });
                        }}
                         loading={recordsFetching}className="admin-search-btn"
                      >
                        {t("查询")}
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
                      { label: t("卡片视图"), value: "card" },
                      { label: t("列表视图"), value: "list" },
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
                            description={t("未找到符合筛选条件的高程数据。")}
                          />
                        ),
                      }}
                    />
                  </div>
                ) : (
                  <div className="admin-elevation-card-view">
                    {isLoading ? (
                      <div className="admin-elevation-card-view-state">
                        <Spin />
                      </div>
                    ) : records.length === 0 ? (
                      <div className="admin-elevation-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("未找到符合筛选条件的高程数据。")}
                        />
                      </div>
                    ) : (
                      <>
                        <div className="admin-elevation-card-view-content">
                          <div className="grid min-h-0 flex-1 content-start gap-3 md:grid-cols-2 xl:grid-cols-4">
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
        title={t("上传高程文件")}
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
          <Form.Item label={t("来源")} name="source">
            <Input placeholder={t("例如：SRTM、DEM 数据")} />
          </Form.Item>

          <Form.Item label={t("分辨率(米)")} name="resolution_m">
            <InputNumber min={0.1} step={0.1} style={{ width: "100%" }} placeholder={t("例如：30")} />
          </Form.Item>

          <Form.Item label={t("备注")} name="notes">
            <Input.TextArea rows={3} placeholder={t("文件说明...")} />
          </Form.Item>

          <Form.Item
            label={t("文件")}
            required
          >
            <Upload.Dragger
              accept=".tif,.tiff,.zip"
              showUploadList={false}
              beforeUpload={(file) => {
                const allowedExts = ["tif", "tiff", "zip"];
                const ext = file.name.split(".").pop()?.toLowerCase() || "";
                if (!allowedExts.includes(ext)) {
                  messageApi.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
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
                    <Typography.Text type="warning">{t("上传中…")}</Typography.Text>
                  )}
                </>
              ) : (
                <>
                  <InboxOutlined style={{ fontSize: 40, color: "#999" }} />
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
        </Form>
      </Modal>

      {/* 编辑文件记录 Modal（来源/分辨率/备注） */}
      <Modal
        title={editingRecord ? `编辑文件 - ${editingRecord.file_name}` : "编辑文件"}
        open={editModalOpen}
        onCancel={closeEditModal}
        onOk={() => editForm.submit()}
        confirmLoading={editMutation.isPending}
        okText={t("保存")}
        width={600}
      >
        <Form form={editForm} layout="vertical" onFinish={(values) => {
          if (editingRecord) {
            editMutation.mutate({ id: editingRecord.id, values });
          }
        }}>
          <Form.Item label={t("来源")} name="source">
            <Input placeholder={t("例如：SRTM、DEM 数据")} allowClear />
          </Form.Item>

          <Form.Item label={t("分辨率(米)")} name="resolution_m">
            <InputNumber min={0.1} step={0.1} style={{ width: "100%" }} placeholder={t("例如：30")} />
          </Form.Item>

          <Form.Item label={t("备注")} name="notes">
            <Input.TextArea rows={3} placeholder={t("文件说明...")} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Apply Modal */}
      <Modal
        title={t("回填线路高程")}
        open={applyModalOpen}
        forceRender
        onCancel={() => {
          setApplyModalOpen(false);
          applyForm.resetFields();
        }}
        onOk={() => applyForm.submit()}
        confirmLoading={applyMutation.isPending}
        width={600}
      >
        <Form form={applyForm} layout="vertical" onFinish={(values) => applyMutation.mutate(values)}>
          <Form.Item name="file_record_id" hidden>
            <Input />
          </Form.Item>

          <Form.Item label={t("选择线路")} name="line_ids" rules={[{ required: true, message: t("请至少选择一条线路") }]}>
            <Select
              mode="multiple"
              placeholder={coverageLoading ? "正在预检线路可回填杆塔…" : "请选择线路（无可回填杆塔的线路已置灰）"}
              showSearch
              optionFilterProp="label"
              loading={coverageLoading}
              disabled={coverageLoading}
              maxTagCount="responsive"
              options={(coverageData?.items ?? []).map((cov) => {
                const matchable = cov.matchable_tower_count ?? 0;
                const noMatch = cov.total_tower_count > 0 && matchable === 0;
                const label = `${cov.line_code ?? "-"} - ${cov.line_name ?? "-"}${cov.voltage_kv ? ` (${cov.voltage_kv}kV)` : ""}`;
                return {
                  label: (
                    <Space size={6} style={{ width: "100%", justifyContent: "space-between" }}>
                      <span>{label}</span>
                      {noMatch ? (
                        <Tag color="warning" style={{ marginInlineEnd: 0 }}>{t("无可回填杆塔")}</Tag>
                      ) : (
                        <span style={{ color: "#8c8c8c", fontSize: 12, whiteSpace: "nowrap" }}>
                          {matchable}/{cov.total_tower_count} 座可回填
                        </span>
                      )}
                    </Space>
                  ),
                  value: cov.line_id,
                  disabled: noMatch,
                };
              })}
            />
          </Form.Item>
        </Form>
      </Modal>

    </div>
  );
}
