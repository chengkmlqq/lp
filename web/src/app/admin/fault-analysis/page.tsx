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
import { PlusOutlined, SearchOutlined, ArrowLeftOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { AnalysisCardList } from "@/components/fault-analysis/analysis-card-list";
import { AnalysisDetailView } from "@/components/fault-analysis/analysis-detail-view";
import { CreateAnalysisFormAdvanced } from "@/components/fault-analysis/create-analysis-form-advanced";
import { readApiError } from "@/lib/api";
import type { LineListResponse } from "@/types/auth";
import type {
  FaultAnalysis,
  CreateFaultAnalysisFormValues,
} from "@/components/fault-analysis/types";

const { Title, Text } = Typography;

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
    queryKey: ["/api/v1/fault-analysis"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const mockData: FaultAnalysis[] = [
        {
          id: "1",
          title: "FA-2026-0703-001",
          description: "2024年夏季雷电多发期故障分析",
          status: "completed",
          risk_level: "high",
          tower_count: 45,
          line_name: "线路 LT-2024-001",
          fault_time: "2026-07-03 11:30",
          fault_type: "A相接地 · 绕击",
          confidence: 62.5,
          created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
          updated_at: new Date(Date.now() - 86400000).toISOString(),
          created_by: "张三",
        },
        {
          id: "2",
          title: "FA-2026-0702-002",
          description: "绝缘子污闪故障综合分析",
          status: "completed",
          risk_level: "medium",
          tower_count: 32,
          line_name: "线路 LT-2023-015",
          fault_time: "2026-07-02 14:20",
          fault_type: "B相接地 · 反击",
          confidence: 93.1,
          created_at: new Date(Date.now() - 86400000).toISOString(),
          updated_at: new Date(Date.now() - 3600000).toISOString(),
          created_by: "李四",
        },
        {
          id: "3",
          title: "FA-2026-0701-003",
          description: "年度综合评估分析报告",
          status: "processing",
          risk_level: "critical",
          tower_count: 78,
          line_name: "线路 LT-2023-008",
          fault_time: "2026-07-01 09:45",
          fault_type: "C相接地 · 绕击",
          confidence: 0,
          created_at: new Date(Date.now() - 3600000).toISOString(),
          updated_at: new Date(Date.now() - 3600000).toISOString(),
        },
      ];
      return { items: mockData, total: mockData.length };
    },
  });

  const analyses = useMemo(() => analysesQuery.data?.items ?? [], [analysesQuery.data?.items]);
  const totalCount = useMemo(() => analysesQuery.data?.total ?? 0, [analysesQuery.data?.total]);

  const filteredAnalyses = useMemo(() => {
    if (!searchKeyword.trim()) {
      return analyses;
    }
    const search = searchKeyword.toLowerCase();
    return analyses.filter(
      (analysis) =>
        analysis.title.toLowerCase().includes(search) ||
        analysis.line_name.toLowerCase().includes(search) ||
        analysis.description?.toLowerCase().includes(search),
    );
  }, [analyses, searchKeyword]);

  const paginatedAnalyses = useMemo(() => {
    const start = (pagination.current - 1) * pagination.pageSize;
    const end = start + pagination.pageSize;
    return filteredAnalyses.slice(start, end);
  }, [filteredAnalyses, pagination.current, pagination.pageSize]);

  const createMutation = useMutation({
    mutationFn: async (values: CreateFaultAnalysisFormValues) => {
      const response = await fetchWithAuth("/api/v1/fault-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { analysis: FaultAnalysis };
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
                <Form.Item style={ marginBottom: 0 }>
                  <Button
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
