"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Pagination,
  Segmented,
  Typography,
  message,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { CreateJobForm } from "@/components/fl-analysis/create-job-form";
import { JobCardList } from "@/components/fl-analysis/job-card-list";
import { JobTable } from "@/components/fl-analysis/job-table";
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
  LineListResponse,
} from "@/types/auth";

export default function AdminFlAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [createJobForm] = Form.useForm<CreateJobFormValues>();
  const [messageApi, contextHolder] = message.useMessage();
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

  async function invalidateFlAnalysisQueries(): Promise<void> {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/fl-analysis"),
    });
  }

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
        payload.adapter_config_json = {
          model_id: values.atp_model_id,
        };
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
      await invalidateFlAnalysisQueries();
      setCreateModalOpen(false);
      messageApi.success(`${formatJobType(job.job_type, mitigationMode(job))}任务已创建并启动`);
      createJobForm.setFieldsValue({ job_name: "" });
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "分析任务创建失败");
    },
  });

  if (!initializing && !user) {
    return <Alert type="warning" showIcon message="请先登录后查看防雷分析结果。" />;
  }

  if (!initializing && !canRead) {
    return <Alert type="error" showIcon message="当前账号缺少线路读取权限，无法查看防雷分析与改造任务。" />;
  }

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col">
        <Card>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                防雷计算
              </Typography.Title>
            </div>
            {canManage ? (
              <Button
                type="primary"
                onClick={() => {
                  setCreateModalOpen(true);
                }}
              >
                新建任务
              </Button>
            ) : null}
          </div>
        </Card>

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

          {jobsQuery.error ? (
            <Alert type="error" showIcon message={jobsQuery.error instanceof Error ? jobsQuery.error.message : "任务列表加载失败"} />
          ) : null}

          {viewMode === "card" ? (
            <>
              <div className="admin-power-lines-card-scroll">
                <JobCardList jobs={jobs} loading={jobsQuery.isLoading} />
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
            <JobTable
              jobs={jobs}
              loading={jobsQuery.isLoading}
              total={total}
              pagination={pagination}
              onPaginationChange={(next) => setPagination(next)}
            />
          )}
        </div>
      </div>

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
    </>
  );
}
