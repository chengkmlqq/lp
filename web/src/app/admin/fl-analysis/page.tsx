"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Segmented,
  Space,
  Tabs,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { TaskLogViewerDrawer } from "@/components/task-log-viewer";
import { Card } from "@/components/ui-antd";
import { CreateJobForm } from "@/components/fl-analysis/create-job-form";
import { JobCardList } from "@/components/fl-analysis/job-card-list";
import { JobDetailTabView } from "@/components/fl-analysis/job-detail-tab-view";
import { JobTable } from "@/components/fl-analysis/job-table";
import { MitigationModal } from "@/components/fl-analysis/mitigation-modal";
import { ScenarioModal } from "@/components/fl-analysis/scenario-modal";
import { ReportModal } from "@/components/fl-analysis/report-modal";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import {
  CREATE_JOB_DEFAULTS,
  formatJobType,
  mitigationMode,
  type CreateJobFormValues,
  type MitigationFormValues,
  type ReportFormValues,
  type ScenarioFormValues,
} from "@/components/fl-analysis/types";
import { readApiError } from "@/lib/api";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
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
  const { modal: modalApi, message: messageApi } = App.useApp();
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

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logModalTaskId, setLogModalTaskId] = useState<string | null>(null);
  const [logModalTitle, setLogModalTitle] = useState("任务执行日志");

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

  const jobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data?.items]);
  const total = jobsQuery.data?.total ?? 0;

  const selectedLine = useMemo(() => {
    return linesQuery.data?.items.find((item) => item.id === selectedLineId) ?? null;
  }, [linesQuery.data?.items, selectedLineId]);

  useEffect(() => {
    const firstLine = linesQuery.data?.items[0];
    if (firstLine && !createJobForm.getFieldValue("line_id")) {
      createJobForm.setFieldsValue({ line_id: firstLine.id });
    }
  }, [createJobForm, linesQuery.data?.items]);

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
      const executionOptions: Record<string, unknown> = {
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
        fanji_naleishuiping_method: values.fanji_naleishuiping_method,
        raoji_naleishuiping_method: values.raoji_naleishuiping_method,
        fanji_tzl_method: values.fanji_tzl_method,
        raoji_tzl_method: values.raoji_tzl_method,
        include_tower_ids: values.include_tower_ids,
      };
      // 普通/同跳计算：勾选的杆塔列表（空=全部杆塔）
      const selectedTowers = values.selected_tower_ids ?? [];
      if (selectedTowers.length > 0) {
        executionOptions.selected_tower_ids = selectedTowers;
      }
      payload.execution_options_json = executionOptions;
    }
    return payload;
  }

  const handleSearch = () => {
    // LP-545：关键词/分页都未变化时查询键不变，react-query 不会自动重新拉取；
    // 手动强制刷新，保证重复点击「查询」也会触发查询（如拉取新数据）。
    const keywordChanged = keywordInput.trim() !== keyword.trim();
    const pageChanged = paginationCurrent !== 1;
    setKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    if (!keywordChanged && !pageChanged) {
      void queryClient.refetchQueries({ queryKey: [jobsListPath] });
    }
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

  // 删除前二次确认（对齐雷电流幅值统计页的 modalApi.confirm 交互）
  const handleDeleteJob = (job: FlAnalysisJobSummary) => {
    modalApi.confirm({
      title: "删除防雷分析任务",
      content: `确认删除任务「${job.job_name || job.line_name || job.id}」吗？删除后不可恢复。`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: () => deleteJobMutation.mutate(job),
    });
  };

  // ---- 任务详情动态 Tab（LP-274：点击任务打开详情，可多开）----
  const [detailTabs, setDetailTabs] = useState<{ key: string; job: FlAnalysisJobSummary }[]>([]);
  const [detailActiveTabKey, setDetailActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [submittingByJob, setSubmittingByJob] = useState<Record<string, boolean>>({});

  const openJobDetail = useCallback((job: FlAnalysisJobSummary) => {
    const tabKey = job.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [...previous, { key: tabKey, job }];
    });
    setDetailActiveTabKey(tabKey);
  }, []);

  const handleDetailTabsEdit = useCallback((targetKey: string | ReactMouseEvent | ReactKeyboardEvent, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    if (submittingByJob[key]) {
      // 任务提交中（措施推荐/复算/报告）禁止关闭详情 Tab
      return;
    }
    setDetailTabs((previous) => {
      const removedIndex = previous.findIndex((tab) => tab.key === key);
      const next = previous.filter((tab) => tab.key !== key);
      if (detailActiveTabKey === key) {
        const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
        setDetailActiveTabKey(fallback);
      }
      return next;
    });
  }, [detailActiveTabKey, submittingByJob]);

  // ---- 措施推荐 / 加装避雷器复算 / 报告生成 Modal 状态 ----
  const mitigationForm = Form.useForm<MitigationFormValues>()[0];
  const scenarioForm = Form.useForm<ScenarioFormValues>()[0];
  const reportForm = Form.useForm<ReportFormValues>()[0];
  const [mitigationOpen, setMitigationOpen] = useState(false);
  const [mitigationJob, setMitigationJob] = useState<FlAnalysisJobSummary | null>(null);
  const [mitigationRows, setMitigationRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [mitigationTowerIds, setMitigationTowerIds] = useState<string[]>([]);
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [scenarioJob, setScenarioJob] = useState<FlAnalysisJobSummary | null>(null);
  const [scenarioRows, setScenarioRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [scenarioBaseJobs, setScenarioBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [scenarioTowerIds, setScenarioTowerIds] = useState<string[]>([]);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportJob, setReportJob] = useState<FlAnalysisJobSummary | null>(null);
  const [reportRows, setReportRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [reportTowerIds, setReportTowerIds] = useState<string[]>([]);

  const openMitigation = useCallback((job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]) => {
    setMitigationJob(job);
    setMitigationRows(rows);
    setMitigationTowerIds(rows.map((row) => row.tower_id));
    mitigationForm.setFieldsValue({ job_name: "", non_construction: false });
    setMitigationOpen(true);
  }, [mitigationForm]);

  const openScenario = useCallback((
    job: FlAnalysisJobSummary,
    rows: FlAnalysisTowerResultSummary[],
    baseJobs: FlAnalysisJobSummary[],
  ) => {
    setScenarioJob(job);
    setScenarioRows(rows);
    setScenarioBaseJobs(baseJobs);
    setScenarioTowerIds(rows.map((row) => row.tower_id));
    scenarioForm.setFieldsValue({ job_name: "" });
    setScenarioOpen(true);
  }, [scenarioForm]);

  const openReport = useCallback((job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]) => {
    setReportJob(job);
    setReportRows(rows);
    setReportTowerIds(rows.map((row) => row.tower_id));
    reportForm.setFieldsValue({ job_name: "" });
    setReportOpen(true);
  }, [reportForm]);

  // ---- 措施推荐任务创建 ----
  const createMitigationMutation = useMutation({
    mutationFn: async (values: MitigationFormValues) => {
      const payload: Record<string, unknown> = {
        line_id: mitigationJob?.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "mitigation",
        execution_options_json: {
          source_job_id: mitigationJob?.id,
          source_run_id: mitigationJob?.latest_run_id,
          selected_tower_ids: mitigationTowerIds,
          non_construction: values.non_construction,
        },
      };
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { job: FlAnalysisJobDetail };
    },
    onSuccess: async () => {
      await invalidateFlAnalysisQueries();
      setMitigationOpen(false);
      messageApi.success("措施推荐任务已创建");
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "措施推荐任务创建失败");
    },
  });

  // ---- 加装避雷器复算任务创建 ----
  const createScenarioMutation = useMutation({
    mutationFn: async (values: ScenarioFormValues) => {
      const payload: Record<string, unknown> = {
        line_id: scenarioJob?.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "scenario",
        execution_options_json: {
          source_job_id: scenarioJob?.id,
          source_run_id: scenarioJob?.latest_run_id,
          base_job_id: values.base_job_id,
          selected_tower_ids: scenarioTowerIds,
        },
      };
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { job: FlAnalysisJobDetail };
    },
    onSuccess: async () => {
      await invalidateFlAnalysisQueries();
      setScenarioOpen(false);
      messageApi.success("加装避雷器复算任务已创建");
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "加装避雷器复算任务创建失败");
    },
  });

  // ---- 报告生成任务创建 ----
  const createReportMutation = useMutation({
    mutationFn: async (values: ReportFormValues) => {
      const payload: Record<string, unknown> = {
        line_id: reportJob?.line_id,
        job_name: values.job_name.trim() || null,
        job_type: "report",
        execution_options_json: {
          source_job_id: reportJob?.id,
          source_run_id: reportJob?.latest_run_id,
          selected_tower_ids: reportTowerIds,
        },
      };
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as { job: FlAnalysisJobDetail };
    },
    onSuccess: async () => {
      await invalidateFlAnalysisQueries();
      setReportOpen(false);
      messageApi.success("报告生成任务已创建");
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "报告生成任务创建失败");
    },
  });


  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
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
        onEdit={handleDetailTabsEdit}
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
                      <JobCardList jobs={jobs} loading={jobsQuery.isLoading} onDeleteJob={handleDeleteJob} canReadLogs={canReadLogs} onOpenLog={openLogViewer} onOpenDetail={openJobDetail} />
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
                      onDeleteJob={handleDeleteJob}
                      canReadLogs={canReadLogs}
                      onOpenLog={openLogViewer}
                      onOpenDetail={openJobDetail}
                    />
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs.map((tab) => ({
            key: tab.key,
            label: (
              <span className="admin-fl-analysis-tab-title">
                {tab.job.job_name || tab.job.line_name || tab.job.line_code || "任务详情"}
              </span>
            ),
            closable: true,
            children: (
              <JobDetailTabView
                job={tab.job}
                jobs={jobs}
                canManage={canManage}
                canReadLogs={canReadLogs}
                onOpenMitigation={openMitigation}
                onOpenScenario={openScenario}
                onOpenReport={openReport}
                onSubmittingChange={(jobId, submitting) => {
                  setSubmittingByJob((previous) => ({ ...previous, [jobId]: submitting }));
                }}
                onOpenLog={openLogViewer}
              />
            ),
          })),
        ]}
      />

      <Modal
        title="新建防雷任务"
        open={createModalOpen}
        width={880}
        footer={null}
        onCancel={() => {
          if (createJobMutation.isPending) {
            return;
          }
          setCreateModalOpen(false);
        }}
        destroyOnHidden={false}
      >
        <CreateJobForm
          form={createJobForm}
          open={createModalOpen}
          submitting={createJobMutation.isPending}
          onCancel={() => {
            if (createJobMutation.isPending) {
              return;
            }
            setCreateModalOpen(false);
          }}
          lines={linesQuery.data?.items ?? []}
          linesLoading={linesQuery.isLoading}
          selectedLine={selectedLine}
          selectedJobType={selectedCreateJobType}
          onSubmit={(values) => {
            createJobMutation.mutate(values);
          }}
        />
      </Modal>

      <TaskLogViewerDrawer
        taskId={logModalTaskId}
        title={logModalTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
      />

      <MitigationModal
        open={mitigationOpen}
        selectedJob={mitigationJob}
        rows={mitigationRows}
        selectedTowerIds={mitigationTowerIds}
        form={mitigationForm}
        submitting={createMitigationMutation.isPending}
        onSelectedTowerIdsChange={setMitigationTowerIds}
        onSubmit={(values) => {
          createMitigationMutation.mutate(values);
        }}
        onCancel={() => setMitigationOpen(false)}
      />

      <ScenarioModal
        open={scenarioOpen}
        selectedJob={scenarioJob}
        rows={scenarioRows}
        baseJobs={scenarioBaseJobs}
        selectedTowerIds={scenarioTowerIds}
        form={scenarioForm}
        submitting={createScenarioMutation.isPending}
        onSelectedTowerIdsChange={setScenarioTowerIds}
        onSubmit={(values) => {
          createScenarioMutation.mutate(values);
        }}
        onCancel={() => setScenarioOpen(false)}
      />

      <ReportModal
        open={reportOpen}
        selectedJob={reportJob}
        rows={reportRows}
        selectedTowerIds={reportTowerIds}
        form={reportForm}
        submitting={createReportMutation.isPending}
        onSelectedTowerIdsChange={setReportTowerIds}
        onSubmit={(values) => {
          createReportMutation.mutate(values);
        }}
        onCancel={() => setReportOpen(false)}
      />
    </div>
  );
}
