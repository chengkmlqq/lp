"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Form,
  Modal,
  Segmented,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { CreateJobForm } from "@/components/fl-analysis/create-job-form";
import { JobCardList } from "@/components/fl-analysis/job-card-list";
import { JobDetailTabView } from "@/components/fl-analysis/job-detail-tab-view";
import { JobTable } from "@/components/fl-analysis/job-table";
import { MitigationModal } from "@/components/fl-analysis/mitigation-modal";
import { ReportModal } from "@/components/fl-analysis/report-modal";
import { ScenarioModal } from "@/components/fl-analysis/scenario-modal";
import {
  CREATE_JOB_DEFAULTS,
  formatJobType,
  mitigationMode,
  statusColor,
  type CreateJobFormValues,
  type DetailTabItem,
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
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
  LineListResponse,
} from "@/types/auth";

/** 任务列表固定主 Tab（不可关闭），任务详情 Tab 依次追加在其后 */
const LIST_TAB_KEY = "list";

export default function AdminFlAnalysisPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [mitigationModalOpen, setMitigationModalOpen] = useState(false);
  const [scenarioModalOpen, setScenarioModalOpen] = useState(false);
  const [reportModalOpen, setReportModalOpen] = useState(false);
  const [detailTabs, setDetailTabs] = useState<Array<{ key: string; job: FlAnalysisJobSummary }>>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  // ---- 提交进行中的任务 Tab key 集合（LP-348：提交中禁止关闭对应任务 Tab）----
  const [submittingTabKeys, setSubmittingTabKeys] = useState<Set<string>>(() => new Set());
  // ---- 任务日志弹窗（LP-274：与详情 Tab 同位展示）----
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logModalTaskId, setLogModalTaskId] = useState<string | null>(null);
  const [logModalTitle, setLogModalTitle] = useState("任务执行日志");
  const [selectedMitigationTowerIds, setSelectedMitigationTowerIds] = useState<string[]>([]);
  const [selectedScenarioTowerIds, setSelectedScenarioTowerIds] = useState<string[]>([]);
  const [selectedReportTowerIds, setSelectedReportTowerIds] = useState<string[]>([]);
  const [mitigationModalJob, setMitigationModalJob] = useState<FlAnalysisJobSummary | null>(null);
  const [scenarioModalJob, setScenarioModalJob] = useState<FlAnalysisJobSummary | null>(null);
  const [reportModalJob, setReportModalJob] = useState<FlAnalysisJobSummary | null>(null);
  const [mitigationModalRows, setMitigationModalRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [scenarioModalRows, setScenarioModalRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [scenarioModalBaseJobs, setScenarioModalBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [reportModalRows, setReportModalRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [createJobForm] = Form.useForm<CreateJobFormValues>();
  const [mitigationForm] = Form.useForm<MitigationFormValues>();
  const [scenarioForm] = Form.useForm<ScenarioFormValues>();
  const [reportForm] = Form.useForm<ReportFormValues>();
  const [messageApi, contextHolder] = message.useMessage();
  const selectedLineId = Form.useWatch("line_id", createJobForm);
  const selectedCreateJobType = Form.useWatch("job_type", createJobForm) ?? CREATE_JOB_DEFAULTS.job_type;
  const selectedAtpModelId = Form.useWatch("atp_model_id", createJobForm) ?? "";

  // closeTab 可能被 Tab 内回调（mutation onSuccess/onMutate 上报提交状态）触发，
  // 用 ref 始终读取最新 detailTabs/activeTabKey，避免关闭/回退位置错乱（LP-348）。
  const detailTabsRef = useRef(detailTabs);
  const activeTabKeyRef = useRef(activeTabKey);
  useEffect(() => {
    detailTabsRef.current = detailTabs;
  }, [detailTabs]);
  useEffect(() => {
    activeTabKeyRef.current = activeTabKey;
  }, [activeTabKey]);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");
  const canReadAtp = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");

  const openLogViewer = useCallback((taskId: string | null | undefined, label: string, title: string) => {
    if (!taskId || !canReadLogs) {
      return;
    }
    setLogModalTaskId(taskId);
    setLogModalTitle(`${label} - ${title}`);
    setLogModalOpen(true);
  }, [canReadLogs]);

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

  // 「当前激活 Tab 的任务」：主 Tab 时为空，任务 Tab 时为其 job.id
  const selectedJobId = activeTabKey === LIST_TAB_KEY ? null : activeTabKey;

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

  // ---- 提交状态上报（LP-348）：提交中禁止关闭对应任务 Tab ----
  const setTabSubmitting = useCallback((tabKey: string, submitting: boolean) => {
    setSubmittingTabKeys((previous) => {
      const next = new Set(previous);
      if (submitting) {
        next.add(tabKey);
      } else {
        next.delete(tabKey);
      }
      return next;
    });
  }, []);

  // ---- 打开/激活任务详情 Tab（LP-374）：按 job.id 去重，可多开对比 ----
  const openJobDetailTab = useCallback((job: FlAnalysisJobSummary) => {
    const tabKey = job.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [
        ...previous,
        { key: tabKey, job },
      ];
    });
    setActiveTabKey(tabKey);
  }, []);

  // ---- 任务 Tab 项：label 用最新 jobs 重建（状态 Tag 实时），children 快照自持 ----
  const detailTabItems = detailTabs.map((tab) => {
    const liveJob = jobs.find((item) => item.id === tab.key) ?? tab.job;
    const lineName = liveJob.line_name || liveJob.line_code || "防雷任务";
    return {
      key: tab.key,
      label: (
        <Space size={6}>
          <span>{liveJob.job_name || lineName}</span>
          <Tag color={statusColor(liveJob.status)}>{liveJob.status}</Tag>
        </Space>
      ),
      closable: true,
      children: (
        <JobDetailTabView
          job={tab.job}
          jobs={jobs}
          canManage={canManage}
          canReadLogs={canReadLogs}
          onOpenMitigation={openMitigationJobModal}
          onOpenScenario={openScenarioJobModal}
          onOpenReport={openReportJobModal}
          onSubmittingChange={setTabSubmitting}
          onOpenLog={openLogViewer}
        />
      ),
    } satisfies DetailTabItem;
  });

  // ---- 关闭任务 Tab：按「左邻 → 最左 → 任务列表」回退 ----
  const handleTabsEdit = useCallback((
    targetKey: ReactMouseEvent | ReactKeyboardEvent | string,
    action: "add" | "remove",
  ) => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    // LP-348：提交进行中的任务 Tab 禁止关闭，避免丢失进行中的操作。
    if (submittingTabKeys.has(key)) {
      return;
    }
    const removedIndex = detailTabsRef.current.findIndex((tab) => tab.key === key);
    const next = detailTabsRef.current.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKeyRef.current === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [submittingTabKeys]);

  function openMitigationJobModal(job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]): void {
    const baseName = job.job_name || job.line_name || job.line_code || "防雷任务";
    setMitigationModalJob(job);
    setMitigationModalRows(rows);
    setSelectedMitigationTowerIds(rows.map((item) => item.tower_id));
    mitigationForm.setFieldsValue({
      job_name: `${baseName}-措施推荐`,
      non_construction: false,
    });
    setMitigationModalOpen(true);
  }

  function openScenarioJobModal(
    job: FlAnalysisJobSummary,
    rows: FlAnalysisTowerResultSummary[],
    baseJobs: FlAnalysisJobSummary[],
  ): void {
    const baseName = job.job_name || job.line_name || job.line_code || "防雷任务";
    setScenarioModalJob(job);
    setScenarioModalRows(rows);
    setScenarioModalBaseJobs(baseJobs);
    setSelectedScenarioTowerIds(rows.map((item) => item.tower_id));
    scenarioForm.setFieldsValue({
      job_name: `${baseName}-加装避雷器复算`,
      base_job_id: baseJobs[0]?.id ?? "",
    });
    setScenarioModalOpen(true);
  }

  function openReportJobModal(job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]): void {
    const baseName = job.job_name || job.line_name || job.line_code || "防雷任务";
    setReportModalJob(job);
    setReportModalRows(rows);
    setSelectedReportTowerIds(rows.map((item) => item.tower_id));
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
      openJobDetailTab(job);
      setCreateModalOpen(false);
      messageApi.success(`${formatJobType(job.job_type, mitigationMode(job))}任务已创建并启动`);
      createJobForm.setFieldsValue({ job_name: "" });
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "分析任务创建失败");
    },
  });

  const createMitigationMutation = useMutation({
    mutationFn: async (values: MitigationFormValues) => {
      if (!mitigationModalJob) {
        throw new Error("缺少前驱风险任务");
      }
      if (mitigationModalJob.job_type !== "risk") {
        throw new Error("仅风险评估任务可生成措施推荐");
      }
      if (selectedMitigationTowerIds.length === 0) {
        throw new Error("请至少选择一座高风险杆塔");
      }
      return createAndStartJob({
        line_id: mitigationModalJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "mitigation",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: mitigationModalJob.id,
          selected_tower_ids: selectedMitigationTowerIds,
          non_construction: values.non_construction,
        },
      });
    },
    onMutate: () => {
      if (mitigationModalJob) {
        setTabSubmitting(mitigationModalJob.id, true);
      }
    },
    onSettled: () => {
      if (mitigationModalJob) {
        setTabSubmitting(mitigationModalJob.id, false);
      }
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setMitigationModalOpen(false);
      openJobDetailTab(job);
      messageApi.success("措施推荐任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "措施推荐任务创建失败");
    },
  });

  const createScenarioMutation = useMutation({
    mutationFn: async (values: ScenarioFormValues) => {
      if (!scenarioModalJob) {
        throw new Error("缺少前驱措施任务");
      }
      if (scenarioModalJob.job_type !== "mitigation") {
        throw new Error("仅措施推荐任务可生成加装避雷器复算");
      }
      if (selectedScenarioTowerIds.length === 0) {
        throw new Error("请至少选择一座需要复算的杆塔");
      }
      if (!values.base_job_id) {
        throw new Error("请选择复用的普通计算或同跳计算任务");
      }
      return createAndStartJob({
        line_id: scenarioModalJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "scenario",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: scenarioModalJob.id,
          base_job_id: values.base_job_id,
          selected_tower_ids: selectedScenarioTowerIds,
        },
      });
    },
    onMutate: () => {
      if (scenarioModalJob) {
        setTabSubmitting(scenarioModalJob.id, true);
      }
    },
    onSettled: () => {
      if (scenarioModalJob) {
        setTabSubmitting(scenarioModalJob.id, false);
      }
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setScenarioModalOpen(false);
      openJobDetailTab(job);
      messageApi.success("加装避雷器复算任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "加装避雷器复算任务创建失败");
    },
  });

  const createReportMutation = useMutation({
    mutationFn: async (values: ReportFormValues) => {
      if (!reportModalJob) {
        throw new Error("缺少报告来源任务");
      }
      if (!["risk", "mitigation"].includes(reportModalJob.job_type)) {
        throw new Error("仅风险评估或措施推荐任务可生成报告");
      }
      if (selectedReportTowerIds.length === 0) {
        throw new Error("请至少选择一座纳入报告的杆塔");
      }
      return createAndStartJob({
        line_id: reportModalJob.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "report",
        external_adapter: "placeholder",
        execution_options_json: {
          source_job_id: reportModalJob.id,
          selected_tower_ids: selectedReportTowerIds,
        },
      });
    },
    onMutate: () => {
      if (reportModalJob) {
        setTabSubmitting(reportModalJob.id, true);
      }
    },
    onSettled: () => {
      if (reportModalJob) {
        setTabSubmitting(reportModalJob.id, false);
      }
    },
    onSuccess: async (job) => {
      await invalidateFlAnalysisQueries();
      setReportModalOpen(false);
      openJobDetailTab(job);
      messageApi.success("报告任务已创建并启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "报告任务创建失败");
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

        <Tabs
          type="editable-card"
          hideAdd
          activeKey={activeTabKey}
          onChange={setActiveTabKey}
          onEdit={handleTabsEdit}
          className="admin-fl-analysis-tabs"
          items={[
            {
              key: LIST_TAB_KEY,
              label: <span className="admin-fl-analysis-tab-title">任务列表</span>,
              closable: false,
              children: (
                <div className="admin-fl-analysis-list-pane">
                  <div className="admin-fl-analysis-list-toolbar">
                    <div>
                      <Typography.Title level={5} style={{ margin: 0 }}>
                        任务列表
                      </Typography.Title>
                      <Typography.Text type="secondary">
                        点击卡片/行打开任务详情，可多开对比。
                      </Typography.Text>
                    </div>
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
                    <JobCardList
                      jobs={jobs}
                      selectedJobId={selectedJobId}
                      loading={jobsQuery.isLoading}
                      onSelect={openJobDetailTab}
                    />
                  ) : (
                    <JobTable
                      jobs={jobs}
                      selectedJobId={selectedJobId}
                      loading={jobsQuery.isLoading}
                      onSelect={openJobDetailTab}
                    />
                  )}
                </div>
              ),
            },
            ...detailTabItems,
          ]}
        />
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

      <MitigationModal
        open={mitigationModalOpen}
        selectedJob={mitigationModalJob}
        rows={mitigationModalRows}
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
        selectedJob={scenarioModalJob}
        rows={scenarioModalRows}
        baseJobs={scenarioModalBaseJobs}
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
        selectedJob={reportModalJob}
        rows={reportModalRows}
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

      <TaskLogViewerDrawer
        taskId={logModalTaskId}
        title={logModalTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
      />
    </>
  );
}
