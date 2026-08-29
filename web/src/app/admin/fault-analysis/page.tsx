"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
} from "@/components/fault-analysis/types";

const { Text } = Typography;

const FAULT_STATUS_META: Record<FaultAnalysis["status"], { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
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

function mapSummary(item: FaultAnalysisListResponse["items"][0]): FaultAnalysis {
  return {
    id: item.id,
    title: item.title ?? "",
    description: item.description ?? "",
    status: item.status as FaultAnalysis["status"],
    line_name: item.line_name ?? "",
    fault_time: item.fault_time ?? "",
    fault_phase: item.fault_phase ?? "",
    reclosure_status: item.reclosure_status ?? "",
    progress: item.progress ?? 0,
    created_at: item.create_date,
    updated_at: item.update_date,
    created_by: item.create_user ?? undefined,
  };
}

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
  if (values.fault_resistance_ohm != null) body.fault_resistance_ohm = values.fault_resistance;
  if (values.line_length_km != null) body.line_length_km = values.line_length;
  if (values.line_angle_deg != null) body.line_angle_deg = values.line_angle;
  if (values.line_impedance_ohm != null) body.line_impedance_ohm = values.line_impedance;
  if (values.lightning_current) body.lightning_current_ka = parseFloat(values.lightning_current) || undefined;
  if (values.lightning_longitude != null) body.lightning_longitude = values.lightning_longitude;
  if (values.lightning_latitude != null) body.lightning_latitude = values.lightning_latitude;
  if (values.wave_distance_km != null) body.wave_distance_km = values.wave_distance;
  if (values.traveling_wave_distance_km != null) body.traveling_wave_distance_km = values.traveling_wave_distance;
  if (values.optical_position) body.optical_position = values.optical_position;
  if (values.optical_device_location) body.optical_device_location = values.optical_device_location;
  return body;
}

function pickTempFileId(list: { temp_file_id?: string; status?: string }[] | undefined): string | undefined {
  const item = list?.find((it) => it.temp_file_id);
  return item?.temp_file_id;
}

function pickTempFileIds(list: { temp_file_id?: string; status?: string }[] | undefined): string[] | undefined {
  const ids = list?.filter((it) => it.temp_file_id).map((it) => it.temp_file_id as string);
  return ids?.length ? ids : undefined;
}

function hasPendingUploads(files: { status?: string; temp_file_id?: string }[] | undefined): boolean {
  return (files ?? []).some((it) => it.status === "uploading" || (!it.temp_file_id && it.status !== "done"));
}

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
  const [tableScrollY, setTableScrollY] = useState(FAULT_TABLE_MIN_SCROLL_Y);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [messageApi, contextHolder] = message.useMessage();
  const [wsProgressMap, setWsProgressMap] = useState<Record<string, { progress: number; status: string; error?: string; step?: string }>>({});

  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [detailAnalysisId, setDetailAnalysisId] = useState<string | null>(null);
  const [detailDefaultView, setDetailDefaultView] = useState<"report" | "process" | "artifacts">("report");

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editAnalysisId, setEditAnalysisId] = useState<string | null>(null);

  const [submittingCreate, setSubmittingCreate] = useState(false);
  const [submittingEdit, setSubmittingEdit] = useState(false);

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

  // ---- 弹窗：详情/新建/编辑 ----

  const openDetailModal = useCallback((record: { id: string; title?: string; fault_type?: string }, defaultView?: "report" | "process" | "artifacts") => {
    setDetailAnalysisId(record.id);
    setDetailDefaultView(defaultView ?? "report");
    setDetailModalOpen(true);
  }, []);

  const handleDetailClose = useCallback(() => {
    setDetailModalOpen(false);
    setDetailAnalysisId(null);
    setDetailDefaultView("report");
  }, []);

  const openCreateModal = useCallback(() => {
    setCreateModalOpen(true);
  }, []);

  const handleCreateClose = useCallback(() => {
    setCreateModalOpen(false);
    setSubmittingCreate(false);
  }, []);

  const openEditModal = useCallback((id: string) => {
    setEditAnalysisId(id);
    setEditModalOpen(true);
  }, []);

  const handleEditClose = useCallback(() => {
    setEditModalOpen(false);
    setEditAnalysisId(null);
    setSubmittingEdit(false);
  }, []);

  const handleCreateSubmit = useCallback(async (values: CreateFaultAnalysisFormValues) => {
    setSubmittingCreate(true);
    try {
      await submitCreate(values);
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
      messageApi.success("故障分析创建成功");
      handleCreateClose();
    } catch (error) {
      setSubmittingCreate(false);
      messageApi.error(error instanceof Error ? error.message : "创建失败");
    }
  }, [submitCreate, queryClient, messageApi, handleCreateClose]);

  const handleEditSubmit = useCallback(async (values: CreateFaultAnalysisFormValues) => {
    if (!editAnalysisId) return;
    setSubmittingEdit(true);
    try {
      await submitUpdate(editAnalysisId, values);
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
      messageApi.success("故障分析更新成功");
      handleEditClose();
    } catch (error) {
      setSubmittingEdit(false);
      messageApi.error(error instanceof Error ? error.message : "更新失败");
    }
  }, [editAnalysisId, submitUpdate, queryClient, messageApi, handleEditClose]);

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

  const openDetail = useCallback((record: { id: string; title?: string; fault_type?: string }, defaultView?: "report" | "process" | "artifacts") => {
    openDetailModal(record, defaultView);
  }, [openDetailModal]);

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
        title: "故障时刻",
        dataIndex: "fault_time",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "故障项",
        dataIndex: "fault_phase",
        width: 120,
        render: (value: string) => formatNullable(value),
      },
      {
        title: "重合闸情况",
        dataIndex: "reclosure_status",
        width: 120,
        render: (value: string) => formatNullable(value),
      },
      {
        title: "操作",
        key: "actions",
        width: 180,
        fixed: "right",
        render: (_: unknown, row) => {
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
                    onClick: () => openEditModal(row.id),
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
    [canManage, handleDelete, handleEditSubmit, openDetail, openEditModal],
  );

  if (!initializing && !user) {
    return (
      <>
        {contextHolder}
        <Alert
          type="warning"
          showIcon
          message="请先登录后查看故障分析。"
        />
      </>
    );
  }

  if (!initializing && !canRead) {
    return (
      <>
        {contextHolder}
        <Alert
          type="error"
          showIcon
          message="当前账号缺少线路读取权限，无法查看故障分析。"
        />
      </>
    );
  }

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col">
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
                  onEdit={canManage ? openEditModal : undefined}
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
      </div>

      <Modal
        title="故障分析详情"
        open={detailModalOpen}
        onCancel={handleDetailClose}
        width={1024}
        footer={null}
        destroyOnClose
        styles={{ body: { maxHeight: "calc(100vh - 180px)", overflowY: "auto" } }}
      >
        {detailAnalysisId ? (
          <AnalysisDetailView
            analysisId={detailAnalysisId}
            tabKey={`detail-${detailAnalysisId}-${detailDefaultView}`}
            defaultView={detailDefaultView}
          />
        ) : (
          <Alert type="info" showIcon message="未选择故障分析记录" />
        )}
      </Modal>

      <Modal
        title="新建故障分析"
        open={createModalOpen}
        onCancel={handleCreateClose}
        confirmLoading={submittingCreate}
        width={1024}
        footer={null}
        destroyOnClose
        styles={{ body: { maxHeight: "calc(100vh - 180px)", overflowY: "auto" } }}
      >
        <CreateAnalysisFormTab
          mode="create"
          submitRequest={handleCreateSubmit}
          onSuccess={handleCreateClose}
          onError={(error) => messageApi.error(error instanceof Error ? error.message : "创建失败")}
          onSubmittingChange={setSubmittingCreate}
        />
      </Modal>

      <Modal
        title={editAnalysisId ? "编辑故障分析" : "编辑故障分析"}
        open={editModalOpen}
        onCancel={handleEditClose}
        confirmLoading={submittingEdit}
        width={1024}
        footer={null}
        destroyOnClose
        styles={{ body: { maxHeight: "calc(100vh - 180px)", overflowY: "auto" } }}
      >
        {editAnalysisId ? (
          <CreateAnalysisFormTab
            mode="edit"
            editId={editAnalysisId}
            submitRequest={handleEditSubmit}
            onSuccess={handleEditClose}
            onError={(error) => messageApi.error(error instanceof Error ? error.message : "更新失败")}
            onSubmittingChange={setSubmittingEdit}
            onLoadError={handleEditClose}
          />
        ) : null}
      </Modal>
    </>
  );
}
