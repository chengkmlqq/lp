"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Form,
  Modal,
  Space,
  Typography,
  message,
  Input,
  Pagination,
} from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { AnalysisCardList } from "@/components/fault-analysis/analysis-card-list";
import { AnalysisDetailView } from "@/components/fault-analysis/analysis-detail-view";
import { CreateAnalysisFormAdvanced } from "@/components/fault-analysis/create-analysis-form-advanced";
import { readApiError } from "@/lib/api";
import type { LineListResponse } from "@/types/auth";
import type {
  FaultAnalysisListResponse,
  FaultAnalysisCreateResponse,
} from "@/types/auth";
import type {
  FaultAnalysis,
  CreateFaultAnalysisFormValues,
} from "@/components/fault-analysis/types";

const { Text } = Typography;

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

export default function AdminFaultAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [createForm] = Form.useForm<CreateFaultAnalysisFormValues>();
  const [messageApi, contextHolder] = message.useMessage();

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
  const totalCount = useMemo(() => analysesQuery.data?.total ?? 0, [analysesQuery.data?.total]);

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
  }, [filteredAnalyses, pagination.current, pagination.pageSize]);

  const createMutation = useMutation({
    mutationFn: async (values: CreateFaultAnalysisFormValues) => {
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
      setViewingId(data.analysis.id);
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "创建失败");
    },
  });

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

  if (viewingId) {
    return (
      <>
        {contextHolder}
        <AnalysisDetailView
          analysisId={viewingId}
          onBack={() => setViewingId(null)}
        />
      </>
    );
  }

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col">
        <Card
          className="admin-fault-analysis-page-card"
          title="故障分析"
          extra={
            canManage && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setCreateModalOpen(true)}
              >
                新建分析
              </Button>
            )
          }
        >
          <div className="flex flex-col gap-4" style={{ height: '100%' }}>
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
                    }}
                    className="admin-search-btn"
                  >
                    查询
                  </Button>
                </Form.Item>
              </Form>
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

            <div className="flex flex-col" style={{ flex: 1, minHeight: 0 }}>
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
                <AnalysisCardList
                  analyses={paginatedAnalyses}
                  selectedId={null}
                  loading={analysesQuery.isLoading}
                  onView={(id) => setViewingId(id)}
                  onEdit={(id) => messageApi.info("编辑功能开发中")}
                  onDelete={(id) => messageApi.info("删除功能开发中")}
                />
              </div>

              <div className="mt-4 flex justify-end">
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
          </div>
        </Card>
      </div>

      <Modal
        title="新建故障分析"
        open={createModalOpen}
        width={950}
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
    </>
  );
}