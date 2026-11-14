"use client";

import { Alert, Descriptions, Empty, Space, Spin, Table, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { translateAnalysisText } from "@/lib/analysis-text";

import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  mitigationMode,
  readCurrentRisk,
  readCurrentScore,
  readMitigationActions,
  readObject,
  readOptionalNumber,
  readOptionalString,
  readReasonDetails,
  readResultWarnings,
  readString,
  selectedTowerCount,
  type MitigationAction,
} from "./types";
import {
  buildMitigationActionColumns,
  ConclusionText,
  formatRiskCounts,
  JobActionsBar,
  JobInfoDescriptions,
  ReasonDetailsTable,
  ResultBasicInfoShell,
  ResultWarnings,
  RiskTag,
} from "./detail-shared";

// ---- Job 级：改造任务面板（mitigation） ----
type MitigationJobDetailPanelProps = {
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

export function MitigationJobDetailPanel({
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
}: MitigationJobDetailPanelProps) {
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

  const executionOptions = readObject(selectedJobDetail.execution_options_json);
  const sourceJobId = readOptionalString(executionOptions, "source_job_id");
  const arresterRequiredCount = readOptionalNumber(
    readObject(selectedJobDetail.result_summary_json),
    "arrester_required_count",
  );
  const riskCounts = formatRiskCounts(selectedJobDetail.result_summary_json?.risk_counts, t);

  const mitigationExtra = (
    <>
      <Descriptions.Item label={t("前驱风险任务")}>{sourceJobId || "-"}</Descriptions.Item>
      <Descriptions.Item label={t("选塔数")}>{String(selectedTowerCount(selectedJobDetail) || "-")}</Descriptions.Item>
      <Descriptions.Item label={t("模式")}>{mitigationMode(selectedJobDetail) ? t("非建线") : t("常规建线")}</Descriptions.Item>
      <Descriptions.Item label={t("需装避雷器数")}>{String(arresterRequiredCount ?? "-")}</Descriptions.Item>
    </>
  );

  return (
    <Space direction="vertical" size={16} className="flex w-full">
      <JobInfoDescriptions jobDetail={selectedJobDetail} extraItems={mitigationExtra} riskCountsContent={riskCounts} />
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

// ---- Tower 级：改造任务详情（mitigation） ----
export function MitigationTowerDetailView({
  detailRow,
  selectedJob,
  canReadLogs,
  onOpenLog,
}: {
  detailRow: FlAnalysisTowerResultSummary;
  selectedJob: FlAnalysisJobSummary | null;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
}) {
  const { t, lang } = useI18n();
  const detailResultObject = readObject(detailRow.result_json);
  const reasonDetails = readReasonDetails(detailRow);
  const resultWarnings = readResultWarnings(detailRow);
  const mitigationActions = readMitigationActions(detailRow);
  const mitigationRecommendation = readString(detailResultObject, "mitigation_recommendation");

  return (
    <Space direction="vertical" size={24} className="flex w-full">
      <ResultBasicInfoShell selectedJob={selectedJob} canReadLogs={canReadLogs} onOpenLog={onOpenLog} t={t} />
      <ResultWarnings warnings={resultWarnings} lang={lang} t={t} />

      <div>
        <Typography.Title level={5}>{t("基本信息")}</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label={t("当前结论")}>{detailRow.summary_text || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("预期风险/风险等级")}>
            <RiskTag value={detailRow.risk_level} t={t} />
          </Descriptions.Item>
          <Descriptions.Item label={t("当前风险")}>
            <RiskTag value={readCurrentRisk(detailRow)} t={t} />
          </Descriptions.Item>
          <Descriptions.Item label={t("改造结论")}>{readString(detailResultObject, "recommendation_result")}</Descriptions.Item>
          <Descriptions.Item label={t("当前得分")}>{String(readCurrentScore(detailRow) ?? "-")}</Descriptions.Item>
          <Descriptions.Item label={t("预期得分/得分")}>
            {String(readOptionalNumber(detailResultObject, "expected_score") ?? "-")}
          </Descriptions.Item>
        </Descriptions>
      </div>

      <ReasonDetailsTable reasonDetails={reasonDetails} t={t} />

      <div>
        <Typography.Title level={5}>{t("改造动作")}</Typography.Title>
        {mitigationActions.length === 0 ? (
          <Empty description={t("当前结果未生成改造动作")} />
        ) : (
          <Table<MitigationAction>
            rowKey="code"
            columns={buildMitigationActionColumns(t)}
            dataSource={mitigationActions}
            pagination={false}
            size="small"
          />
        )}
      </div>

      <div>
        <Typography.Title level={5}>{t("措施建议")}</Typography.Title>
        <div className="fl-detail-conclusion">{translateAnalysisText(mitigationRecommendation, lang)}</div>
      </div>

      <ConclusionText
        summaryText={readOptionalString(detailRow, "summary_text")}
        causeAnalysis={readString(detailResultObject, "cause_analysis")}
        lang={lang}
        t={t}
      />
    </Space>
  );
}
