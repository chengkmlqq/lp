"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Form,
  Modal,
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
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { AnalysisCardList } from "@/components/fault-analysis/analysis-card-list";
import { AnalysisDetailView } from "@/components/fault-analysis/analysis-detail-view";
import { CreateAnalysisFormAdvanced } from "@/components/fault-analysis/create-analysis-form-advanced";
import { readApiError } from "@/lib/api";
import type { LineListResponse } from "@/types/auth";
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

/** 从 antd Upload fileList 取值中提取首个原始 File。 */
function pickUploadFile(value: { originFileObj: File }[] | undefined): File | undefined {
  return value?.[0]?.originFileObj;
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
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [tableScrollY, setTableScrollY] = useState(FAULT_TABLE_MIN_SCROLL_Y);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [createForm] = Form.useForm<CreateFaultAnalysisFormValues>();
  const [messageApi, contextHolder] = message.useMessage();

  // Edit / delete state
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm] = Form.useForm<CreateFaultAnalysisFormValues>();
  const [editLoading, setEditLoading] = useState(false);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage");

  const linesQuery = useQuery({
    queryKey: ["/api/v1/lines"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/lines");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

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

  const analyses = useMemo(
    () => (analysesQuery.data?.items ?? []).map(mapSummary),
    [analysesQuery.data?.items],
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

  const createMutation = useMutation({
    mutationFn: async (values: CreateFaultAnalysisFormValues) => {
      const body = buildFaultAnalysisBody(values);
      const fileFields: Array<[string, File | undefined]> = [
        ["wave_data_file", pickUploadFile(values.wave_data_file)],
        ["lightning_data_file", pickUploadFile(values.lightning_data_file)],
        ["ledger_data_file", pickUploadFile(values.ledger_data_file)],
        ["traveling_wave_file", pickUploadFile(values.traveling_wave_file)],
        ["optical_data_file", pickUploadFile(values.optical_data_file)],
      ];

      if (hasUploadFiles(values)) {
        // 携带判别输入文件时使用 multipart 上传接口（LP-316）。
        const formData = new FormData();
        for (const [key, value] of Object.entries(body)) {
          if (value !== undefined) {
            formData.set(key, String(value));
          }
        }
        for (const [field, file] of fileFields) {
          if (file) {
            formData.set(field, file, file.name);
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
    },
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({
        queryKey: ["/api/v1/fault-analysis"],
      });
      setCreateModalOpen(false);
      messageApi.success("故障分析创建成功");
      createForm.resetFields();
      openDetail({ id: data.analysis.id });
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "创建失败");
    },
  });

  // --- Edit handlers ---

  const handleEdit = useCallback(async (id: string) => {
    setEditingId(id);
    setEditModalOpen(true);
    setEditLoading(true);
    editForm.resetFields();

    try {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${id}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const detail: FaultAnalysisDetail = await response.json();

      editForm.setFieldsValue({
        line_id: detail.line_id ?? "",
        station_name: detail.station ?? undefined,
        fault_time: detail.fault_time ?? undefined,
        fault_line_name: detail.line_name ?? undefined,
        fault_phase: detail.fault_phase ?? undefined,
        fault_duration: detail.fault_duration_ms ?? undefined,
        reclosure_status: detail.reclosure_status ?? undefined,
        fault_voltage: detail.fault_voltage_v ?? undefined,
        fault_current: detail.fault_current_a ?? undefined,
        max_zero_current: detail.max_zero_current_a ?? undefined,
        zero_compensation: detail.zero_compensation ?? undefined,
        fault_resistance: detail.fault_resistance_ohm ?? undefined,
        line_length: detail.line_length_km ?? undefined,
        line_angle: detail.line_angle_deg ?? undefined,
        line_impedance: detail.line_impedance_ohm ?? undefined,
        lightning_current: detail.lightning_current_ka?.toString() ?? undefined,
        lightning_longitude: detail.lightning_longitude ?? undefined,
        lightning_latitude: detail.lightning_latitude ?? undefined,
        wave_distance: detail.wave_distance_km ?? undefined,
        traveling_wave_distance: detail.traveling_wave_distance_km ?? undefined,
        optical_position: detail.optical_position ?? undefined,
        optical_device_location: detail.optical_device_location ?? undefined,
      });
    } catch (error) {
      messageApi.error(error instanceof Error ? error.message : "加载故障分析详情失败");
      setEditModalOpen(false);
      setEditingId(null);
    } finally {
      setEditLoading(false);
    }
  }, [editForm, fetchWithAuth, messageApi]);

  const updateMutation = useMutation({
    mutationFn: async (values: CreateFaultAnalysisFormValues) => {
      if (!editingId) throw new Error("未指定编辑记录");

      const body = buildFaultAnalysisBody(values);

      const response = await fetchWithAuth(`/api/v1/fault-analysis/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisDetail;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/fault-analysis"] });
      setEditModalOpen(false);
      setEditingId(null);
      messageApi.success("故障分析更新成功");
      editForm.resetFields();
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "更新失败");
    },
  });

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
  const openDetail = useCallback((record: { id: string; title?: string; fault_type?: string }) => {
    const tabKey = record.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: tabKey,
          label: (
            <Space size={6}>
              <span>{record.title || `故障分析 ${record.id.slice(0, 8)}`}</span>
              {record.fault_type ? <Tag color="blue">{record.fault_type}</Tag> : null}
            </Space>
          ),
          closable: true,
          children: (
            <AnalysisDetailView
              analysisId={tabKey}
              tabKey={tabKey}
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
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey]);

  const columns = useMemo<ColumnsType<FaultAnalysis>>(
    () => [
      {
        title: "标题",
        dataIndex: "title",
        ellipsis: true,
        render: (value: string) => formatNullable(value),
      },
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
        width: 100,
        render: (value: FaultAnalysis["status"]) => {
          const meta = FAULT_STATUS_META[value] ?? { color: "default", label: value };
          return <Tag color={meta.color}>{meta.label}</Tag>;
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
        render: (value: string) => formatNullable(value),
      },
      {
        title: "操作",
        key: "actions",
        width: 180,
        fixed: "right",
        render: (_: unknown, row) => {
          const moreMenuItems: MenuProps["items"] = canManage
            ? [
                {
                  key: "delete",
                  label: "删除",
                  danger: true,
                  onClick: () => handleDelete(row.id),
                },
              ]
            : [];

          return (
            <Space wrap>
              <Button size="small" onClick={() => openDetail(row)}>
                详情
              </Button>
              {canManage && (
                <Button size="small" onClick={() => handleEdit(row.id)}>
                  编辑
                </Button>
              )}
              {canManage && (
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Button size="small" icon={<MoreOutlined />} />
                </Dropdown>
              )}
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
                onClick={() => setCreateModalOpen(true)}
              >
                新建分析
              </Button>
            ) : null
          }
          items={[
            {
              key: LIST_TAB_KEY,
              label: <span className="admin-fault-analysis-tab-title">故障分析列表</span>,
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

      <Modal
        title="新建故障分析"
        open={createModalOpen}
        width={760}
        onCancel={() => {
          if (createMutation.isPending) {
            return;
          }
          setCreateModalOpen(false);
        }}
        onOk={() => createForm.submit()}
        okText="提交分析"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        destroyOnClose
      >
        <CreateAnalysisFormAdvanced
          form={createForm}
          lines={linesQuery.data?.items ?? []}
          linesLoading={linesQuery.isLoading}
          onSubmit={(values) => createMutation.mutate(values)}
        />
      </Modal>

      <Modal
        title="编辑故障分析"
        open={editModalOpen}
        width={760}
        onCancel={() => {
          if (updateMutation.isPending) {
            return;
          }
          setEditModalOpen(false);
          setEditingId(null);
        }}
        onOk={() => editForm.submit()}
        okText="保存修改"
        cancelText="取消"
        confirmLoading={updateMutation.isPending || editLoading}
        destroyOnClose
        afterClose={() => {
          editForm.resetFields();
          setEditingId(null);
        }}
      >
        <CreateAnalysisFormAdvanced
          form={editForm}
          lines={linesQuery.data?.items ?? []}
          linesLoading={linesQuery.isLoading}
          onSubmit={(values) => updateMutation.mutate(values)}
        />
      </Modal>
    </>
  );
}
