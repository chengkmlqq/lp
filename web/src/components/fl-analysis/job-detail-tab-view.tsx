"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Drawer, message, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { TowerDetailView } from "@/components/fl-analysis/detail-modal";
import { JobDetailPanel } from "@/components/fl-analysis/job-detail-panel";
import { ResultTable } from "@/components/fl-analysis/result-table";
import { readApiError } from "@/lib/api";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultListResponse,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";
import {
  readDownloadFilename,
  waveformJobType,
} from "@/components/fl-analysis/types";

type JobDetailTabViewProps = {
  /** 打开 Tab 时的任务快照（FlAnalysisJobSummary），用于稳定标识与详情展示 */
  job: FlAnalysisJobSummary;
  /** 最新任务列表，供加装避雷器复算选择基线任务 */
  jobs: FlAnalysisJobSummary[];
  canManage: boolean;
  canReadLogs: boolean;
  onOpenMitigation: (job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]) => void;
  onOpenScenario: (
    job: FlAnalysisJobSummary,
    rows: FlAnalysisTowerResultSummary[],
    baseJobs: FlAnalysisJobSummary[],
  ) => void;
  onOpenReport: (job: FlAnalysisJobSummary, rows: FlAnalysisTowerResultSummary[]) => void;
  /** 上报提交状态：外层据此锁定/解锁该任务 Tab 的关闭 */
  onSubmittingChange: (jobId: string, submitting: boolean) => void;
  onOpenLog: (taskId: string | null | undefined, label: string, title: string) => void;
};

export function JobDetailTabView({
  job,
  jobs,
  canManage,
  canReadLogs,
  onOpenMitigation,
  onOpenScenario,
  onOpenReport,
  onSubmittingChange,
  onOpenLog,
}: JobDetailTabViewProps) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [messageApi, contextHolder] = message.useMessage();

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  // ---- 杆塔详情：原「塔详情动态选项卡」改为抽屉展示（版式参照线路管理详情页的杆塔抽屉）----
  const [towerDetailRow, setTowerDetailRow] = useState<FlAnalysisTowerResultSummary | null>(null);

  const jobDetailQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs/detail", job.id],
    enabled: !!user && canRead && !!job.id,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${job.id}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisJobDetail;
    },
  });

  const towerResultsQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs/results", job.id],
    enabled: !!user && canRead && !!job.id,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${job.id}/results`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FlAnalysisTowerResultListResponse;
    },
  });

  const selectedJobDetail = jobDetailQuery.data ?? null;
  const selectedJobDetailWaveformType = waveformJobType(selectedJobDetail ?? job);

  // 状态跟随最新任务列表（jobs），避免快照 job 的 status 过时；job_type 等快照字段不受影响
  const liveJob = jobs.find((item) => item.id === job.id) ?? job;

  const towerRows = useMemo(() => towerResultsQuery.data?.items ?? [], [towerResultsQuery.data?.items]);
  const candidateMitigationRows = useMemo(
    () => towerRows.filter((item) => item.risk_level !== "low"),
    [towerRows],
  );
  const candidateScenarioRows = useMemo(() => {
    if (job.job_type !== "mitigation") {
      return [];
    }
    return towerRows.filter((item) => item.risk_level !== "low");
  }, [job.job_type, towerRows]);
  const candidateReportRows = useMemo(() => {
    if (job.job_type === "mitigation") {
      return towerRows;
    }
    return towerRows.filter((item) => item.risk_level !== "low");
  }, [job.job_type, towerRows]);
  const candidateScenarioBaseJobs = jobs.filter(
    (item) => item.line_id === job.line_id && item.status === "success" && ["normal", "tongtiao"].includes(item.job_type),
  );

  const canCreateMitigation = liveJob.job_type === "risk";
  const canCreateScenario = liveJob.job_type === "mitigation";
  const canCreateReport = liveJob.job_type === "risk" || liveJob.job_type === "mitigation";
  const canDownloadResults = liveJob.job_type !== "report"
    && liveJob.status === "success"
    && towerRows.length > 0;

  async function invalidateFlAnalysisQueries(): Promise<void> {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/fl-analysis"),
    });
  }

  // 任务 Tab 内自持的开始/下载操作：pending 状态按 Tab 隔离，
  // 不依赖外层 mutation（外层 detailTabs children 为打开时快照，props 不会随外层刷新）。
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
    onMutate: () => onSubmittingChange(job.id, true),
    onSettled: () => onSubmittingChange(job.id, false),
    onSuccess: async () => {
      await invalidateFlAnalysisQueries();
      messageApi.success("任务已启动");
    },
    onError: (error) => {
      messageApi.error(error instanceof Error ? error.message : "任务启动失败");
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

  // 点击分级结果中的杆塔行 → 打开抽屉查看该杆塔详情
  const openTowerDetail = useCallback((row: FlAnalysisTowerResultSummary) => {
    setTowerDetailRow(row);
  }, []);
  return (
    <>
      {contextHolder}
      <div className="admin-fl-analysis-detail-pane">
        <div>
          {/* 「任务信息」标题行：导出结果按钮右对齐放在同一行最右侧 */}
          <div className="admin-fl-analysis-title-row">
            <Typography.Title level={4} className="admin-fl-analysis-detail-title">
              计算任务-计算结果
            </Typography.Title>
            {liveJob.job_type !== "report" ? (
              <Button
                onClick={() => {
                  downloadResultsMutation.mutate({
                    jobId: job.id,
                    runId: selectedJobDetail?.latest_run_id ?? job.latest_run_id,
                    jobType: job.job_type,
                  });
                }}
                loading={downloadResultsMutation.isPending}
                disabled={!canDownloadResults}
              >
                导出结果
              </Button>
            ) : null}
          </div>
          <JobDetailPanel
            selectedJob={liveJob}
            selectedJobDetail={selectedJobDetail}
            loading={jobDetailQuery.isLoading}
            error={jobDetailQuery.error}
            canManage={canManage}
            canCreateMitigation={canCreateMitigation}
            canCreateScenario={canCreateScenario}
            canCreateReport={canCreateReport}
            selectedJobDetailWaveformType={selectedJobDetailWaveformType}
            candidateMitigationRows={candidateMitigationRows}
            candidateScenarioRows={candidateScenarioRows}
            candidateScenarioBaseJobs={candidateScenarioBaseJobs}
            candidateReportRows={candidateReportRows}
            startPending={startJobMutation.isPending}
            downloadReportPending={downloadReportMutation.isPending}
            onStart={() => {
                startJobMutation.mutate(job.id);
              }}
            onOpenMitigation={() => onOpenMitigation(liveJob, candidateMitigationRows)}
            onOpenScenario={() => onOpenScenario(liveJob, candidateScenarioRows, candidateScenarioBaseJobs)}
            onOpenReport={() => onOpenReport(liveJob, candidateReportRows)}
            onDownloadReport={() => {
              downloadReportMutation.mutate(job.id);
            }}
          />
        </div>

        {/* 分级结果：不再用选项卡，表格直接展示在下方 */}
        <section className="fl-create-form-block">
          <div className="fl-create-form-block-title">杆塔明细</div>
          <ResultTable
          selectedJob={liveJob}
          selectedWaveformJobType={selectedJobDetailWaveformType}
          rows={towerRows}
          loading={towerResultsQuery.isLoading}
          error={towerResultsQuery.error}
          onOpenDetail={openTowerDetail}
        />
        </section>
      </div>

      {/* 杆塔详情抽屉：版式参照线路管理详情页（宽 880、单一纵向滚动容器） */}
      <Drawer
        title={towerDetailRow ? `杆塔详情 - ${towerDetailRow.tower_no}` : "杆塔详情"}
        open={towerDetailRow !== null}
        width={880}
        onClose={() => setTowerDetailRow(null)}
        destroyOnHidden
      >
        {towerDetailRow ? (
          <div className="admin-tower-detail-content">
            <TowerDetailView
              detailRow={towerDetailRow}
              selectedJob={job}
              selectedJobDetail={selectedJobDetail}
              canReadLogs={canReadLogs}
              onOpenLog={onOpenLog}
            />
          </div>
        ) : null}
      </Drawer>
    </>
  );
}
