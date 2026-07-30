"use client";

import type { ComponentType, CSSProperties, RefAttributes } from "react";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  message,
  type CardProps,
  type MenuProps,
  type UploadFile,
} from "antd";
import { MoreOutlined, UploadOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { ElevationPreviewCesiumMap } from "@/components/elevation-preview-cesium-map";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { ElevationDatasetTerrainStatus } from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

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

type ElevationPreviewPoint = {
  longitude: number;
  latitude: number;
  altitude_m: number;
};

type ElevationPreviewHeightGrid = {
  rows: number;
  cols: number;
  west: number;
  south: number;
  east: number;
  north: number;
  heights: (number | null)[];
};

type ElevationPreviewDiagnostics = {
  source_crs: string | null;
  source_bounds_min_x: number | null;
  source_bounds_max_x: number | null;
  source_bounds_min_y: number | null;
  source_bounds_max_y: number | null;
  wgs84_bounds_min_lon: number | null;
  wgs84_bounds_max_lon: number | null;
  wgs84_bounds_min_lat: number | null;
  wgs84_bounds_max_lat: number | null;
  raster_width: number | null;
  raster_height: number | null;
  target_samples: number | null;
  sampling_step: number | null;
  scanned_candidates: number | null;
  valid_preview_count: number | null;
  skip_read_error: number;
  skip_masked: number;
  skip_nodata: number;
  skip_nonfinite: number;
  skip_sample_transform_error: number;
  sample_tx_first_error: string | null;
  skip_sample_out_of_range: number;
};

type ElevationFileRecordPreviewResponse = {
  record: ElevationFileRecordSummary;
  preview_mode: "point_cloud" | "height_grid";
  total_points: number;
  sampled_points: number;
  points: ElevationPreviewPoint[];
  height_grid?: ElevationPreviewHeightGrid | null;
  diagnostics: ElevationPreviewDiagnostics | null;
  warnings: string[];
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
  const isMobile = useMobileDetection();

  const [uploadForm] = Form.useForm();
  const [applyForm] = Form.useForm<ApplyFormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(ELEVATION_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedRecords, setAllLoadedRecords] = useState<ElevationFileRecordSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [applyModalOpen, setApplyModalOpen] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<ElevationFileRecordSummary | null>(null);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewData, setPreviewData] = useState<ElevationFileRecordPreviewResponse | null>(null);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
      const formData = new FormData();
      if (fileList.length === 0) {
        throw new Error("请选择文件");
      }
      const file = fileList[0].originFileObj || fileList[0];
      if (!file || !(file instanceof File || file instanceof Blob)) {
        throw new Error("无效的文件对象");
      }
      formData.append("file", file);
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
      setFileList([]);
      queryClient.invalidateQueries({ queryKey: ["elevation-records"] });
    },
    onError: (error) => {
      message.error(readMutationError(error, "上传失败"));
    },
  });

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

  // Preview mutation
  const previewMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetchWithAuth(`/api/v1/elevation/records/${id}/preview?max_points=1500`);
      return readJsonResponse<ElevationFileRecordPreviewResponse>(response);
    },
    onSuccess: (data) => {
      setPreviewData(data);
      setPreviewModalOpen(true);
    },
    onError: (error) => {
      message.error(readMutationError(error, "预览失败"));
    },
  });

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

  // Update allLoadedRecords when records data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedRecords(() => records);
      } else {
        setAllLoadedRecords((prev) => {
          if (records.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(r => r.id));
          const newRecords = records.filter(r => !existingIds.has(r.id));
          return [...prev, ...newRecords];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [records, isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = recordsData?.total ?? 0;
        const loadedCount = allLoadedRecords.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, isLoading, recordsData?.total, allLoadedRecords.length]);

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
      title: "操作",
      key: "actions",
      width: 180,
      render: (_value, row) => {
        const analyzing = analyzeMutation.isPending && analyzingId === row.id;
        const deleting = deleteMutation.isPending && deletingId === row.id;
        const rowBusy = analyzing || deleting;

        return (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy}
              onClick={() => previewMutation.mutate(row.id)}
            >
              预览
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

    const moreMenuItems: MenuProps["items"] = [
      { type: "divider" },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: rowBusy,
        onClick: () => {
          Modal.confirm({
            title: "确认删除",
            content: `确定要删除文件 "${record.file_name}" 吗？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: () => deleteMutation.mutate(record.id),
          });
        },
      },
    ];

    return (
      <AntCard
        key={record.id}
        className="admin-elevation-record-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis>{record.file_name}</Typography.Text>
            <Tag color={statusTagColor(record.status)}>{record.status}</Tag>
          </Space>
        }
        extra={
          <Space size={4}>
            <Button
              type="text"
              size="small"
              disabled={rowBusy}
              onClick={() => previewMutation.mutate(record.id)}
            >
              预览
            </Button>
            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button type="text" size="small" disabled={rowBusy} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">格式</Typography.Text>
            <Tag>{record.file_format.toUpperCase()}</Tag>
          </div>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">大小</Typography.Text>
            <Typography.Text>{formatFileSize(record.file_size)}</Typography.Text>
          </div>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">来源</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: record.source || "-" }}>
              {record.source || "-"}
            </Typography.Text>
          </div>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">分辨率</Typography.Text>
            <Typography.Text>{record.resolution_m ? `${record.resolution_m.toFixed(1)} m` : "-"}</Typography.Text>
          </div>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">样本数</Typography.Text>
            <Typography.Text>{record.sample_count.toLocaleString()}</Typography.Text>
          </div>
          <div className="admin-elevation-record-card-field">
            <Typography.Text type="secondary">解析状态</Typography.Text>
            <Tag color={computedParseStatus(record).color}>{computedParseStatus(record).label}</Tag>
          </div>
        </Space>
      </AntCard>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-elevation-page-card"
        title="高程数据管理"
        extra={
          <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
            上传文件
          </Button>
        }
      >
        {viewMode === "card" ? (
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
                    setCardViewPage(1);
                    setAllLoadedRecords([]);
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
                    setCardViewPage(1);
                    setAllLoadedRecords([]);
                  }}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        ) : (
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
                    setCardViewPage(1);
                    setAllLoadedRecords([]);
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
                    setCardViewPage(1);
                    setAllLoadedRecords([]);
                  }}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}

        {viewMode === "table" ? (
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
                pageSizeOptions: [10, 20, 50, 100],
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
            {isLoading && allLoadedRecords.length === 0 ? (
              <div className="admin-elevation-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedRecords.length === 0 ? (
              <div className="admin-elevation-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的高程数据。"
                />
              </div>
            ) : (
              <div className="admin-elevation-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedRecords.map((recordItem) => (
                    <Col key={recordItem.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderRecordCard(recordItem)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedRecords.length >= (recordsData?.total ?? 0) && allLoadedRecords.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedRecords.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      {/* Upload Modal */}
      <Modal
        title="上传高程文件"
        open={uploadModalOpen}
        onCancel={() => {
          setUploadModalOpen(false);
          uploadForm.resetFields();
          setFileList([]);
        }}
        onOk={() => uploadForm.submit()}
        confirmLoading={uploadMutation.isPending}
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
            help="支持 .tif/.tiff 和 .zip 格式"
          >
            <Upload
              fileList={fileList}
              beforeUpload={(file) => {
                setFileList([file]);
                return false;
              }}
              onRemove={() => setFileList([])}
              maxCount={1}
              accept=".tif,.tiff,.zip"
            >
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
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

      {/* Preview Modal */}
      <Modal
        title="高程数据预览"
        open={previewModalOpen}
        onCancel={() => {
          setPreviewModalOpen(false);
          setPreviewData(null);
        }}
        footer={null}
        width="80%"
        style={{ top: 20 }}
      >
        {previewData && (
          <div>
            <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="文件名">{previewData.record?.file_name}</Descriptions.Item>
              <Descriptions.Item label="格式">{previewData.record?.file_format}</Descriptions.Item>
              <Descriptions.Item label="总点数">{previewData.total_points?.toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="采样点数">{previewData.sampled_points?.toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="地形状态">{previewData.record?.terrain_status}</Descriptions.Item>
            </Descriptions>
            <div className="min-w-0 rounded-md border border-slate-200 p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <Typography.Text strong>地形预览</Typography.Text>
                <Tag color={statusTagColor(previewData.record.terrain_status)}>{previewData.record.terrain_status}</Tag>
              </div>
              <ElevationPreviewCesiumMap
                dataset={{
                  id: previewData.record.id,
                  name: previewData.record.file_name,
                  terrain_status: previewData.record.terrain_status,
                  terrain_url_template: previewData.record.terrain_url_template,
                  terrain_bounds: previewData.record.terrain_bounds,
                  terrain_metadata: previewData.record.terrain_metadata,
                }}
                accessToken={getAccessToken()}
                points={previewData.points}
                heightGrid={previewData.height_grid ?? null}
                height={430}
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
