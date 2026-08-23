"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Segmented,
  Space,
  Tabs,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { CreateJobForm } from "@/components/fl-analysis/create-job-form";
import { JobCardList } from "@/components/fl-analysis/job-card-list";
import { JobTable } from "@/components/fl-analysis/job-table";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import {
  CREATE_JOB_DEFAULTS,
  formatJobType,
  mitigationMode,
  type CreateJobFormValues,
} from "@/components/fl-analysis/types";
import { readApiError } from "@/lib/api";
import type {
  AtpEngineStatusResponse,
  AtpAssetListResponse,
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  LineListResponse,
} from "@/types/auth";

const LIST_TAB_KEY = "list";
const FL_ANALYSIS_TABLE_MIN_SCROLL_Y = 180;
const FL_ANALYSIS_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const FL_ANALYSIS_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const FL_ANALYSIS_TABLE_BOTTOM_GAP = 8;

export default function AdminFlAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const { message: messageApi } = App.useApp();
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [tableScrollY, setTableScrollY] = useState(FL_ANALYSIS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [createJobForm] = Form.useForm<CreateJobFormValues>();
  const selectedLineId = Form.useWatch("line_id", createJobForm);
  const selectedCreateJobType = Form.useWatch("job_type", createJobForm) ?? CREATE_JOB_DEFAULTS.job_type;
  const selectedAtpModelId = Form.useWatch("atp_model_id", createJobForm) ?? "";

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");
  const canReadAtp = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

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

  const jobsListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    const query = params.toString();
    return `/api/v1/fl-analysis/jobs${query ? `?${query}` : ""}`;
  }, [keyword, paginationCurrent, paginationPageSize]);

  const jobsQuery = useQuery({
    queryKey: [jobsListPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(jobsListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisJobListResponse;
    },
  });

  const engineQuery = useQuery({
    queryKey: ["/api/v1/atp/engine/status"],
    enabled: !!user && canReadAtp,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/atp/engine/status");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpEngineStatusResponse;
    },
    staleTime: 30_000,
  });

  const atpModelsQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", "enabled"],
    enabled: !!user && canReadAtp,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/atp/assets?status=enabled");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetListResponse;
    },
  });

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const total = jobsQuery.data?.total ?? 0;

  const atpModels = useMemo(() => atpModelsQuery.data?.items ?? [], [atpModelsQuery.data]);
  const selectedAtpModel = useMemo(
    () => atpModels.find((item) => item.id === selectedAtpModelId) ?? null,
    [atpModels, selectedAtpModelId],
  );

  const selectedLine = useMemo(() => {
    return linesQuery.data?.items.find((item) => item.id === selectedLineId) ?? null;
  }, [linesQuery.data?.items, selectedLineId]);

  useEffect(() => {
    const firstLine = linesQuery.data?.items[0];
    if (firstLine && !createJobForm.getFieldValue("line_id")) {
      createJobForm.setFieldsValue({ line_id: firstLine.id });
    }
  }, [createJobForm, linesQuery.data?.items]);

  useEffect(() => {
    if (!["normal", "tongtiao"].includes(selectedCreateJobType)) {
      return;
    }
    if (!atpModels.length || createJobForm.getFieldValue("atp_model_id")) {
      return;
    }
    createJobForm.setFieldValue("atp_model_id", atpModels[0].id);
  }, [atpModels, createJobForm, selectedCreateJobType]);

  const invalidateFlAnalysisQueries = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/fl-analysis"),
    });
  }, [queryClient]);

  useTopicSubscription("admin.fl-analysis", useCallback(() => {
    void invalidateFlAnalysisQueries();
  }, [invalidateFlAnalysisQueries]));

  const jobListError = jobsQuery.error instanceof Error ? jobsQuery.error.message : "";
  useToastFeedback({
    errorMessage: error || jobListError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const updateTableScrollHeight = useCallback(() => {
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
    const headerHeight = header?.getBoundingClientRect().height ?? FL_ANALYSIS_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = paginationEl?.getBoundingClientRect().height ?? FL_ANALYSIS_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - FL_ANALYSIS_TABLE_BOTTOM_GAP);
    const clampedHeight = Math.max(FL_ANALYSIS_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight]);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(updateTableScrollHeight);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollHeight, viewMode, jobs.length]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
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
  }, [updateTableScrollHeight, viewMode, jobs.length]);

  async function createAndStartJob(payload: Record<string, unknown>): Promise<FlAnalysisJobDetail> {
    const createResponse = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!createResponse.ok) {
      throw new Error(await readApiError(createResponse));
    }
    const created = (await createResponse.json()) as { job: FlAnalysisJobDetail };

    const startResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${created.job.id}/start`, {
      method: "POST",
    });
    if (!startResponse.ok) {
      throw new Error(await readApiError(startResponse));
    }
    const started = (await startResponse.json()) as { job: FlAnalysisJobDetail };
    return started.job;
  }

  function buildCreateJobPayload(values: CreateJobFormValues): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      line_id: values.line_id,
      job_name: values.job_name.trim() || null,
      job_type: values.job_type,
    };
    if (values.job_type === "normal" || values.job_type === "tongtiao") {
      payload.execution_options_json = {
        current_waveform: values.current_waveform,
        flashover_method: values.flashover_method,
        altitude_correction: values.altitude_correction,
        induced_voltage_formula: values.induced_voltage_formula,
        head_time_min_us: values.head_time_min_us,
        head_time_max_us: values.head_time_max_us,
        head_time_step_us: values.head_time_step_us,
        tail_time_min_us: values.tail_time_min_us,
        tail_time_max_us: values.tail_time_max_us,
        tail_time_step_us: values.tail_time_step_us,
      };
      if (values.atp_model_id) {
        payload.external_adapter = "atp";
        payload.adapter_config_json = {
          model_id: values.atp_model_id,
        };
      }
      if (values.binary_search) {
        payload.execution_options_json.binary_search = true;
        payload.execution_options_json.binary_search_low_ka = values.binary_search_low_ka;
        payload.execution_options_json.binary_search_high_ka = values.binary_search_high_ka;
        payload.execution_options_json.binary_search_tolerance_ka = values.binary_search_tolerance_ka;
      }
    }
    return payload;
  }

  const handleSearch = () => {
    setKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  const createJobMutation = useMutation({
    mutationFn: async (values: CreateJobFormValues) => createAndStartJob(buildCreateJobPayload(values)),
    onSuccess: async (job) => {
      setError("");
      await invalidateFlAnalysisQueries();
      setCreateModalOpen(false);
      messageApi.success(`${formatJobType(job.job_type, mitigationMode(job))}任务已创建并启动`);
      createJobForm.setFieldsValue({ job_name: "" });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "分析任务创建失败");
    },
  });

  const deleteJobMutation = useMutation({
    mutationFn: async (job: FlAnalysisJobSummary) => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${job.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return job;
    },
    onSuccess: async (job) => {
      setError("");
      await invalidateFlAnalysisQueries();
      messageApi.success(`已删除防雷分析任务：${job.job_name || job.line_name || job.id}`);
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "防雷分析任务删除失败");
    },
  });


  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再查看防雷分析结果。</Typography.Text>
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
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `line.manage`）。</Typography.Text>
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
        className="admin-fl-analysis-tabs"
        tabBarExtraContent={
          <Space>
            {canManage && (
              <Button type="primary" onClick={() => setCreateModalOpen(true)}>
                新建任务
              </Button>
            )}
          </Space>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-fl-analysis-tab-title">防雷计算</span>,
            closable: false,
            children: (
              <div className="admin-fl-analysis-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label="关键字" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        value={keywordInput}
                        allowClear
                        onChange={(event) => setKeywordInput(event.target.value)}
                        placeholder="按任务名/线路名/线路编码筛选"
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={handleSearch}
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

                 {jobs.length === 0 ? (
                  <Empty description="暂无防雷分析任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : viewMode === "card" ? (
                  <>
                    <div className="admin-power-lines-card-scroll">
                      <JobCardList jobs={jobs} loading={jobsQuery.isLoading} onDeleteJob={(job) => deleteJobMutation.mutate(job)} />
                    </div>
                    <div className="admin-power-lines-pagination">
                      <Pagination
                        current={pagination.current}
                        pageSize={pagination.pageSize}
                        total={total}
                        onChange={(page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        }}
                        showSizeChanger
                        showTotal={(total) => `共 ${total} 条`}
                      />
                    </div>
                  </>
                ) : (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-fl-analysis-table-view"
                    style={{ "--admin-fl-analysis-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <JobTable
                      jobs={jobs}
                      loading={jobsQuery.isLoading}
                      total={total}
                      pagination={pagination}
                      onPaginationChange={(next) => setPagination(next)}
                      scrollY={tableScrollY}
                      onDeleteJob={(job) => deleteJobMutation.mutate(job)}
                    />
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />

      <Modal
        title="新建防雷任务"
        open={createModalOpen}
        width={800}
        onCancel={() => {
          if (createJobMutation.isPending) {
            return;
          }
          setCreateModalOpen(false);
        }}
        onOk={() => createJobForm.submit()}
        okText="创建并启动任务"
        cancelText="取消"
        confirmLoading={createJobMutation.isPending}
        destroyOnClose={false}
      >
        <CreateJobForm
          form={createJobForm}
          lines={linesQuery.data?.items ?? []}
          linesLoading={linesQuery.isLoading}
          selectedLine={selectedLine}
          selectedJobType={selectedCreateJobType}
          atpModels={atpModels}
          atpModelsLoading={atpModelsQuery.isLoading}
          atpModelsError={atpModelsQuery.error}
          selectedAtpModel={selectedAtpModel}
          engineQueryData={engineQuery.data}
          onSubmit={(values) => {
            createJobMutation.mutate(values);
          }}
        />
      </Modal>
    </div>
  );
}
