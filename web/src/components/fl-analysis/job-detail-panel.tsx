"use client";
import { useI18n } from "@/lib/i18n";

import { Alert, Descriptions, Empty, Space, Spin } from "antd";

import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatJobType,
  readObject,
  readOptionalNumber,
  readOptionalString,
  selectedTowerCount,
} from "./types";
import {
  AdvancedParamsSection,
  CalculationMethodSection,
  formatRiskCounts,
  JobActionsBar,
  JobInfoDescriptions,
} from "./detail-shared";

type ScenarioJobDetailPanelProps = {
  selectedJob: FlAnalysisJobSummary | null;
  selectedJobDetail: FlAnalysisJobDetail | null;
  loading: boolean;
  error: unknown;
  canManage: boolean;
  canCreateMitigation: boolean;
  canCreateScenario: boolean;
  canCreateReport: boolean;
  selectedJobDetailWaveformType: "normal" | "tongtiao" | null;
  candidateMitigationRows: FlAnalysisTowerResultSummary[];
  candidateScenarioRows: FlAnalysisTowerResultSummary[];
  candidateReportRows: FlAnalysisTowerResultSummary[];
  downloadReportPending: boolean;
  onOpenMitigation: () => void;
  onOpenScenario: () => void;
  onOpenReport: () => void;
  onDownloadReport: () => void;
};

// ---- Job 级：加装避雷器复算任务面板（scenario，复用计算类区块） ----
export function ScenarioJobDetailPanel({
  selectedJob,
  selectedJobDetail,
  loading,
  error,
  canManage,
  canCreateMitigation,
  canCreateScenario,
  canCreateReport,
  selectedJobDetailWaveformType,
  candidateMitigationRows,
  candidateScenarioRows,
  candidateReportRows,
  downloadReportPending,
  onOpenMitigation,
  onOpenScenario,
  onOpenReport,
  onDownloadReport,
}: ScenarioJobDetailPanelProps) {
  const { t } = useI18n();

  if (loading) {
    return (
      <div className="flex w-full items-center justify-center py-8">
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error instanceof Error ? error.message : t("任务详情加载失败")}
      />
    );
  }

  if (!selectedJobDetail || !selectedJob) {
    return <Empty description={t("暂无任务详情")} />;
  }

  const selectedJobExecutionOptions = readObject(selectedJobDetail.execution_options_json);
  const sourceJobId = readOptionalString(selectedJobExecutionOptions, "source_job_id");
  const scenarioBaseJobType = readOptionalString(selectedJobExecutionOptions, "base_job_type");
  const scenarioBaseJobName = readOptionalString(selectedJobExecutionOptions, "base_job_name");
  const riskCounts = formatRiskCounts(selectedJobDetail.result_summary_json?.risk_counts, t);

  const scenarioExtra = (
    <>
      <Descriptions.Item label={t("前驱措施任务")}>{sourceJobId || "-"}</Descriptions.Item>
      <Descriptions.Item label={t("选塔数")}>{String(selectedTowerCount(selectedJobDetail) || "-")}</Descriptions.Item>
      <Descriptions.Item label={t("复用计算口径")}>
        {scenarioBaseJobType ? formatJobType(scenarioBaseJobType, false, t) : "-"}
      </Descriptions.Item>
      <Descriptions.Item label={t("基线计算任务")}>{scenarioBaseJobName || "-"}</Descriptions.Item>
    </>
  );

  return (
    <Space direction="vertical" size={16} className="flex w-full">
      <JobInfoDescriptions jobDetail={selectedJobDetail} extraItems={scenarioExtra} riskCountsContent={riskCounts} />
      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <CalculationMethodSection executionOptions={selectedJobExecutionOptions} t={t} />
      ) : null}
      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <AdvancedParamsSection
          workflow={readObject(selectedJobDetail.result_summary_json).workflow as
            | { current_waveform?: string; flashover_method?: string; altitude_correction?: string; induced_voltage_formula?: string; head_time_range_us?: { min?: number | null; max?: number | null; step?: number | null }; tail_time_range_us?: { min?: number | null; max?: number | null; step?: number | null } }
            | undefined}
          t={t}
        />
      ) : null}
      <JobActionsBar
        selectedJob={selectedJob}
        canManage={canManage}
        canCreateMitigation={canCreateMitigation}
        canCreateScenario={canCreateScenario}
        canCreateReport={canCreateReport}
        candidateMitigationRows={candidateMitigationRows}
        candidateScenarioRows={candidateScenarioRows}
        candidateReportRows={candidateReportRows}
        downloadReportPending={downloadReportPending}
        onOpenMitigation={onOpenMitigation}
        onOpenScenario={onOpenScenario}
        onOpenReport={onOpenReport}
        onDownloadReport={onDownloadReport}
      />
    </Space>
  );
}

type ReportJobDetailPanelProps = {
  selectedJob: FlAnalysisJobSummary | null;
  selectedJobDetail: FlAnalysisJobDetail | null;
  loading: boolean;
  error: unknown;
  canManage: boolean;
  canCreateMitigation: boolean;
  canCreateScenario: boolean;
  canCreateReport: boolean;
  candidateMitigationRows: FlAnalysisTowerResultSummary[];
  candidateScenarioRows: FlAnalysisTowerResultSummary[];
  candidateReportRows: FlAnalysisTowerResultSummary[];
  downloadReportPending: boolean;
  onOpenMitigation: () => void;
  onOpenScenario: () => void;
  onOpenReport: () => void;
  onDownloadReport: () => void;
};

// ---- Job 级：报告任务面板（report，保留报告专属字段块） ----
export function ReportJobDetailPanel({
  selectedJob,
  selectedJobDetail,
  loading,
  error,
  canManage,
  canCreateMitigation,
  canCreateScenario,
  canCreateReport,
  candidateMitigationRows,
  candidateScenarioRows,
  candidateReportRows,
  downloadReportPending,
  onOpenMitigation,
  onOpenScenario,
  onOpenReport,
  onDownloadReport,
}: ReportJobDetailPanelProps) {
  const { t } = useI18n();

  if (loading) {
    return (
      <div className="flex w-full items-center justify-center py-8">
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error instanceof Error ? error.message : t("任务详情加载失败")}
      />
    );
  }

  if (!selectedJobDetail || !selectedJob) {
    return <Empty description={t("暂无任务详情")} />;
  }

  const selectedJobSummary = readObject(selectedJobDetail.result_summary_json);
  const reportSourceJobType = readOptionalString(selectedJobSummary, "source_job_type");
  const reportSourceJobName = readOptionalString(selectedJobSummary, "source_job_name");
  const reportMitigationJobName = readOptionalString(selectedJobSummary, "mitigation_job_name");
  const reportScenarioJobName = readOptionalString(selectedJobSummary, "scenario_job_name");
  const reportDocumentName = readOptionalString(selectedJobSummary, "document_filename");
  const selectedTowerCountValue = readOptionalNumber(selectedJobSummary, "selected_tower_count");
  const riskCounts = formatRiskCounts(selectedJobDetail.result_summary_json?.risk_counts, t);

  const reportExtra = (
    <>
      <Descriptions.Item label={t("报告来源")}>
        {reportSourceJobType ? formatJobType(reportSourceJobType, false, t) : "-"}
        {reportSourceJobName ? ` / ${reportSourceJobName}` : ""}
      </Descriptions.Item>
      <Descriptions.Item label={t("选塔数")}>{String(selectedTowerCountValue ?? "-")}</Descriptions.Item>
      <Descriptions.Item label={t("关联措施任务")}>{reportMitigationJobName || t("未关联")}</Descriptions.Item>
      <Descriptions.Item label={t("关联复算任务")}>{reportScenarioJobName || t("未关联")}</Descriptions.Item>
      <Descriptions.Item label={t("文档名")} span={2}>{reportDocumentName || "-"}</Descriptions.Item>
    </>
  );

  return (
    <Space direction="vertical" size={16} className="flex w-full">
      <JobInfoDescriptions jobDetail={selectedJobDetail} extraItems={reportExtra} riskCountsContent={riskCounts} />
      <JobActionsBar
        selectedJob={selectedJob}
        canManage={canManage}
        canCreateMitigation={canCreateMitigation}
        canCreateScenario={canCreateScenario}
        canCreateReport={canCreateReport}
        candidateMitigationRows={candidateMitigationRows}
        candidateScenarioRows={candidateScenarioRows}
        candidateReportRows={candidateReportRows}
        downloadReportPending={downloadReportPending}
        onOpenMitigation={onOpenMitigation}
        onOpenScenario={onOpenScenario}
        onOpenReport={onOpenReport}
        onDownloadReport={onDownloadReport}
      />
    </Space>
  );
}
