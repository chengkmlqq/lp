"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Form,
  Modal,
  Space,
  Typography,
  message,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { CreateJobForm } from "@/components/fl-analysis/create-job-form";
import { DetailModal } from "@/components/fl-analysis/detail-modal";
import { JobDetailPanel } from "@/components/fl-analysis/job-detail-panel";
import { JobListCard } from "@/components/fl-analysis/job-card-list";
import { MitigationModal } from "@/components/fl-analysis/mitigation-modal";
import { ReportModal } from "@/components/fl-analysis/report-modal";
import { ResultTable } from "@/components/fl-analysis/result-table";
import { ScenarioModal } from "@/components/fl-analysis/scenario-modal";
import {
  CREATE_JOB_DEFAULTS,
  formatJobType,
  mitigationMode,
  readDownloadFilename,
  waveformJobType,
  type CreateJobFormValues,
  type MitigationFormValues,
  type ReportFormValues,
  type ScenarioFormValues,
} from "@/components/fl-analysis/types";
import { readApiError } from "@/lib/api";
import type {
  AtpEngineStatusResponse,
  AtpAssetListResponse,
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisTowerResultListResponse,
  FlAnalysisTowerResultSummary,
  LineListResponse,
} from "@/types/auth";

export default function AdminFlAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [detailRow, setDetailRow] = useState<FlAnalysisTowerResultSummary | null>(null);
  const [mitigationModalOpen, setMitigationModalOpen] = useState(false);
  const [scenarioModalOpen, setScenarioModalOpen] = useState(false);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedMitigationTowerIds, setSelectedMitigationTowerIds] = useState<string[]>([]);
  const [selectedScenarioTowerIds, setSelectedScenarioTowerIds] = useState<string[]>([]);
  const [selectedReportTowerIds, setSelectedReportTowerIds] = useState<string[]>([]);
  const [createJobForm] = Form.useForm<CreateJobFormValues>();
  const [mitigationForm] = Form.useForm<MitigationFormValues>();
  const [scenarioForm] = Form.useForm<ScenarioFormValues>();
  const [reportForm] = Form.useForm<ReportFormValues>();
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

  const jobsQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=100");
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
  const selectedJob = useMemo(() => {
    if (!selectedJobId) {
      return jobs[0] ?? null;
    }
    return jobs.find((item) => item.id === selectedJobId) ?? null;
  }, [jobs, selectedJobId]);
  const selectedJobCardId = selectedJob?.id ?? null;
  const selectedWaveformJobType = waveformJobType(selectedJob);

  const selectedJobDetailQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs/detail", selectedJob?.id ?? ""],
    enabled: !!user && canRead && !!selectedJob?.id,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${selectedJob?.id}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisJobDetail;
    },
  });

  const towerResultsQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs/results", selectedJob?.id ?? ""],
    enabled: !!user && canRead && !!selectedJob?.id,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${selectedJob?.id}/results`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisTowerResultListResponse;
    },
  });

  const towerRows = useMemo(() => towerResultsQuery.data?.items ?? [], [towerResultsQuery.data?.items]);
  const candidateMitigationRows = useMemo(
    () => towerRows.filter((item) => item.risk_level !== "low"),
    [towerRows],
  );

  const candidateScenarioRows = useMemo(() => {
    if (selectedJob?.job_type !== "mitigation") {
      return [];
    }
    return towerRows.filter((item) => item.risk_level !== "low");
  }, [selectedJob?.job_type, towerRows]);

  const candidateReportRows = useMemo(() => {
    if (selectedJob?.job_type === "mitigation") {
      return towerRows;
    }
    return towerRows.filter((item) => item.risk_level !== "low");
  }, [selectedJob?.job_type, towerRows]);

  const candidateScenarioBaseJobs = useMemo(() => {
    if (!selectedJob) {
      return [];
    }
    return jobs.filter(
      (item) => item.line_id === selectedJob.line_id && item.status === "success" && ["normal", "tongtiao"].includes(item.job_type),
    );
  }, [jobs, selectedJob]);

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

  function openMitigationJobModal(): void {
    if (!selectedJob) {
      return;
    }
    const baseName = selectedJob.job_name || selectedJob.line_name || selectedJob.line_code || "防雷任务";
    setSelectedMitigationTowerIds(candidateMitigationRows.map((item) => item.tower_id));
    mitigationForm.setFieldsValue({
      job_name: `${baseName}-措施推荐`,
      non_construction: false,
    });
    setMitigationModalOpen(true);
  }

  function openScenarioJobModal(): void {
    if (!selectedJob) {
      return;
    }
    const baseName = selectedJob.job_name || selectedJob.line_name || selectedJob.line_code || "防雷任务";
    setSelectedScenarioTowerIds(candidateScenarioRows.map((item) => item.tower_id));
    scenarioForm.setFieldsValue({
      job_name: `${baseName}-加装避雷器复算`,
      base_job_id: candidateScenarioBaseJobs[0]?.id ?? "",
    });
    setScenarioModalOpen(true);
  }

  function openReportJobModal(): void {
    if (!selectedJob) {
      return;
    }
    const baseName = selectedJob.job_name || selectedJob.line_name || selectedJob.line_code || "防雷任务";
    setSelectedReportTowerIds(candidateReportRows.map((item) => item.tower_id));
    reportForm.setFieldsValue({
      job_name: `${baseName}-报告`,
    });
    setReportModalOpen(true);
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

  const createJobMutation = useMutation({
    mutationFn: async (values: CreateJobFormValues) => createAndStartJob(buildCreateJobPayload(values)),
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setSelectedJobId(job.id);
      setCreateModalOpen(false);
      messageApi.success(`${formatJobType(job.job_type, mitigationMode(job))}任务已创建并启动`);
      createJobForm.setFieldsValue({ job_name: "" });
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "分析任务创建失败");
    },
  });

  const startJobMutation = useMutation({
    mutationFn: async (jobId: string) => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/start`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { job: FlAnalysisJobDetail };
    },
    onSuccess: async () => {
      await invalidateFlAnalysisQueries();
      messageApi.success("任务已启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "任务启动失败");
    },
  });

  const createMitigationMutation = useMutation({
    mutationFn: async (values: MitigationFormValues) => {
      if (!selectedJob) {
        throw new Error("缺少前驱风险任务");
      }
      if (selectedJob.job_type !== "risk") {
        throw new Error("仅风险评估任务可生成措施推荐");
      }
      if (selectedMitigationTowerIds.length === 0) {
        throw new Error("请至少选择一座高风险杆塔");
      }
      return createAndStartJob({
        line_id: selectedJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "mitigation",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: selectedJob.id,
          selected_tower_ids: selectedMitigationTowerIds,
          non_construction: values.non_construction,
        },
      });
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setMitigationModalOpen(false);
      setSelectedJobId(job.id);
      messageApi.success("措施推荐任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "措施推荐任务创建失败");
    },
  });

  const createScenarioMutation = useMutation({
    mutationFn: async (values: ScenarioFormValues) => {
      if (!selectedJob) {
        throw new Error("缺少前驱措施任务");
      }
      if (selectedJob.job_type !== "mitigation") {
        throw new Error("仅措施推荐任务可生成加装避雷器复算");
      }
      if (selectedScenarioTowerIds.length === 0) {
        throw new Error("请至少选择一座需要复算的杆塔");
      }
      if (!values.base_job_id) {
        throw new Error("请选择复用的普通计算或同跳计算任务");
      }
      return createAndStartJob({
        line_id: selectedJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "scenario",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: selectedJob.id,
          base_job_id: values.base_job_id,
          selected_tower_ids: selectedScenarioTowerIds,
        },
      });
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setScenarioModalOpen(false);
      setSelectedJobId(job.id);
      messageApi.success("加装避雷器复算任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "加装避雷器复算任务创建失败");
    },
  });

  const createReportMutation = useMutation({
    mutationFn: async (values: ReportFormValues) => {
      if (!selectedJob) {
        throw new Error("缺少报告来源任务");
      }
      if (!["risk", "mitigation"].includes(selectedJob.job_type)) {
        throw new Error("仅风险评估或措施推荐任务可生成报告");
      }
      if (selectedReportTowerIds.length === 0) {
        throw new Error("请至少选择一座纳入报告的杆塔");
      }
      return createAndStartJob({
        line_id: selectedJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "report",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: selectedJob.id,
          selected_tower_ids: selectedReportTowerIds,
        },
      });
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setReportModalOpen(false);
      setSelectedJobId(job.id);
      messageApi.success("报告任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "报告任务创建失败");
    },
  });

  const downloadReportMutation = useMutation({
    mutationFn: async (jobId: string) => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/report/download`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const filename = readDownloadFilename(
        response.headers.get("content-disposition"),
        "防雷报告.doc",
      );
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    },
    onSuccess: () => {
      messageApi.success("报告下载成功");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "报告下载失败");
    },
  });

  const downloadResultsMutation = useMutation({
    mutationFn: async ({ jobId, runId, jobType }: { jobId: string; runId?: string | null; jobType: string }) => {
      const params = new URLSearchParams();
      if (runId) {
        params.set("run_id", runId);
      }
      const suffix = params.size > 0 ? `?${params.toString()}` : "";
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/results/download${suffix}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const filename = readDownloadFilename(
        response.headers.get("content-disposition"),
        `防雷分析-${jobType}-结果.csv`,
      );
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    },
    onSuccess: () => {
      messageApi.success("结果导出成功");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "结果导出失败");
    },
  });

  const selectedJobDetail = selectedJobDetailQuery.data ?? null;
  const selectedJobDetailWaveformType = waveformJobType(selectedJobDetail ?? selectedJob);
  const canCreateMitigation = selectedJob?.job_type === "risk";
  const canCreateScenario = selectedJob?.job_type === "mitigation";
  const canCreateReport = selectedJob?.job_type === "risk" || selectedJob?.job_type === "mitigation";
  const canDownloadResults = selectedJob?.job_type !== "report"
    && selectedJob?.status === "success"
    && towerRows.length > 0;

  if (!initializing && !user) {
    return <Alert type="warning" showIcon message="请先登录后查看防雷分析结果。" />;
  }

  if (!initializing && !canRead) {
    return <Alert type="error" showIcon message="当前账号缺少线路读取权限，无法查看防雷分析与改造任务。" />;
  }

  return (
    <>
      {contextHolder}
      <Space direction="vertical" size={16} className="flex w-full">
        <Card>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                防雷分析与改造
              </Typography.Title>
              <Typography.Text type="secondary">
                支持普通计算、同跳计算、风险评估、措施推荐、加装避雷器复算与报告生成工作流。
              </Typography.Text>
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

        {jobsQuery.error ? (
          <Alert type="error" showIcon message={jobsQuery.error instanceof Error ? jobsQuery.error.message : "任务列表加载失败"} />
        ) : null}

        <JobListCard
          jobs={jobs}
          selectedJobId={selectedJobCardId}
          loading={jobsQuery.isLoading}
          onSelect={setSelectedJobId}
        />

        {selectedJob ? (
          <>
            <Card>
              <JobDetailPanel
                selectedJob={selectedJob}
                selectedJobDetail={selectedJobDetail}
                loading={selectedJobDetailQuery.isLoading}
                error={selectedJobDetailQuery.error}
                canManage={canManage}
                canCreateMitigation={canCreateMitigation}
                canCreateScenario={canCreateScenario}
                canCreateReport={canCreateReport}
                canDownloadResults={canDownloadResults}
                selectedJobDetailWaveformType={selectedJobDetailWaveformType}
                candidateMitigationRows={candidateMitigationRows}
                candidateScenarioRows={candidateScenarioRows}
                candidateScenarioBaseJobs={candidateScenarioBaseJobs}
                candidateReportRows={candidateReportRows}
                startPending={startJobMutation.isPending}
                downloadResultsPending={downloadResultsMutation.isPending}
                downloadReportPending={downloadReportMutation.isPending}
                onStart={() => {
                  if (selectedJob) {
                    startJobMutation.mutate(selectedJob.id);
                  }
                }}
                onOpenMitigation={openMitigationJobModal}
                onOpenScenario={openScenarioJobModal}
                onOpenReport={openReportJobModal}
                onDownloadResults={() => {
                  downloadResultsMutation.mutate({
                    jobId: selectedJob.id,
                    runId: selectedJobDetail?.latest_run_id ?? selectedJob.latest_run_id,
                    jobType: selectedJob.job_type,
                  });
                }}
                onDownloadReport={() => {
                  downloadReportMutation.mutate(selectedJob.id);
                }}
              />
            </Card>

            <Card>
              <ResultTable
                selectedJob={selectedJob}
                selectedWaveformJobType={selectedWaveformJobType}
                rows={towerRows}
                loading={towerResultsQuery.isLoading}
                error={towerResultsQuery.error}
                onOpenDetail={(row) => {
                  setDetailRow(row);
                  setDetailModalOpen(true);
                }}
              />
            </Card>
          </>
        ) : null}
      </Space>

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

      <DetailModal
        open={detailModalOpen}
        detailRow={detailRow}
        selectedJob={selectedJob}
        selectedJobDetail={selectedJobDetail}
        onClose={() => {
          setDetailModalOpen(false);
          setDetailRow(null);
        }}
      />

      <MitigationModal
        open={mitigationModalOpen}
        selectedJob={selectedJob}
        rows={candidateMitigationRows}
        selectedTowerIds={selectedMitigationTowerIds}
        form={mitigationForm}
        submitting={createMitigationMutation.isPending}
        onSelectedTowerIdsChange={setSelectedMitigationTowerIds}
        onSubmit={(values) => {
          createMitigationMutation.mutate(values);
        }}
        onCancel={() => {
          setMitigationModalOpen(false);
        }}
      />

      <ScenarioModal
        open={scenarioModalOpen}
        selectedJob={selectedJob}
        rows={candidateScenarioRows}
        baseJobs={candidateScenarioBaseJobs}
        selectedTowerIds={selectedScenarioTowerIds}
        form={scenarioForm}
        submitting={createScenarioMutation.isPending}
        onSelectedTowerIdsChange={setSelectedScenarioTowerIds}
        onSubmit={(values) => {
          createScenarioMutation.mutate(values);
        }}
        onCancel={() => {
          setScenarioModalOpen(false);
        }}
      />

      <ReportModal
        open={reportModalOpen}
        selectedJob={selectedJob}
        rows={candidateReportRows}
        selectedTowerIds={selectedReportTowerIds}
        form={reportForm}
        submitting={createReportMutation.isPending}
        onSelectedTowerIdsChange={setSelectedReportTowerIds}
        onSubmit={(values) => {
          createReportMutation.mutate(values);
        }}
        onCancel={() => {
          setReportModalOpen(false);
        }}
      />
    </>
  );
}
