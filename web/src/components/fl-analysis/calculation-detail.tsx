"use client";

import { Alert, Descriptions, Empty, Space, Spin, Table, Tag, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatAltitudeCorrection,
  formatCurrentWaveform,
  formatExternalAdapter,
  formatFlashoverMethod,
  formatInducedVoltageFormula,
  formatRangeSummary,
  formatRiskLevel,
  readObject,
  readOptionalString,
  readScanPoints,
  readSelectedCase,
  readWorkflow,
  readPhaseResults,
  readMultiPhaseResults,
  readReasonDetails,
  readResultWarnings,
  readString,
  riskColor,
  waveformJobType,
  type PhaseResult,
  type MultiPhaseResult,
  type ScanPoint,
  type WorkflowSummary,
} from "./types";
import {
  AdvancedParamsSection,
  CalculationMethodSection,
  ComputationSteps,
  ConclusionText,
  formatAtpModel,
  formatRiskCounts,
  JobActionsBar,
  JobInfoDescriptions,
  ReasonDetailsTable,
  ResultBasicInfoShell,
  ResultWarnings,
  buildComputationSteps,
  buildScanPointColumns,
  buildPhaseResultColumns,
  buildMultiPhaseColumns,
} from "./detail-shared";

// ---- Job 级：计算任务面板（normal / tongtiao / risk / scenario 复用） ----
type CalculationJobDetailPanelProps = {
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

export function CalculationJobDetailPanel({
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
}: CalculationJobDetailPanelProps) {
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
  const selectedJobSummary = readObject(selectedJobDetail.result_summary_json);
  const selectedJobWorkflow = readObject(selectedJobDetail.result_summary_json).workflow as
    | WorkflowSummary
    | undefined;
  const selectedJobExternalModelCode = readOptionalString(selectedJobSummary, "external_model_code");
  const selectedJobExternalModelName = readOptionalString(selectedJobSummary, "external_model_name");
  const selectedJobExternalModelVersion = readOptionalString(selectedJobSummary, "external_model_version");
  const riskCounts = formatRiskCounts(selectedJobDetail.result_summary_json?.risk_counts, t);

  return (
    <Space direction="vertical" size={16} className="flex w-full">
      <JobInfoDescriptions jobDetail={selectedJobDetail} riskCountsContent={riskCounts} />
      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <CalculationMethodSection
          executionOptions={selectedJobExecutionOptions}
          externalModelName={selectedJobExternalModelName}
          externalModelCode={selectedJobExternalModelCode}
          externalModelVersion={selectedJobExternalModelVersion}
          t={t}
        />
      ) : null}
      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <AdvancedParamsSection workflow={selectedJobWorkflow} t={t} />
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

// ---- Tower 级：计算任务详情（normal / tongtiao / risk / scenario 复用） ----
export function CalculationTowerDetailView({
  detailRow,
  selectedJob,
  selectedJobDetail,
  canReadLogs,
  onOpenLog,
}: {
  detailRow: FlAnalysisTowerResultSummary;
  selectedJob: FlAnalysisJobSummary | null;
  selectedJobDetail: FlAnalysisJobDetail | null;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
}) {
  const { t, lang } = useI18n();
  const detailResultObject = readObject(detailRow.result_json);
  const reasonDetails = readReasonDetails(detailRow);
  const resultWarnings = readResultWarnings(detailRow);
  const scanPoints = readScanPoints(detailRow);
  const phaseResults = readPhaseResults(detailRow);
  const multiPhaseResults = readMultiPhaseResults(detailRow);
  const detailWorkflow = readWorkflow(detailRow);
  const detailSelectedCase = readSelectedCase(detailRow);
  const detailExternalExecution = readObject(detailResultObject.external_execution);
  const selectedJobDetailWaveformType = waveformJobType(selectedJobDetail ?? selectedJob);

  const computationSteps =
    selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao"
      ? buildComputationSteps(detailResultObject, selectedJobDetailWaveformType, t)
      : [];

  return (
    <Space direction="vertical" size={24} className="flex w-full">
      <ResultBasicInfoShell selectedJob={selectedJob} canReadLogs={canReadLogs} onOpenLog={onOpenLog} t={t} />
      <ResultWarnings warnings={resultWarnings} lang={lang} t={t} />

      <div>
        <Typography.Title level={5}>{t("基本信息")}</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label={t("当前结论")}>{detailRow.summary_text || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("风险等级")}>
            <Tag color={riskColor(detailRow.risk_level)}>{formatRiskLevel(detailRow.risk_level, t)}</Tag>
          </Descriptions.Item>
          {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
            <>
              <Descriptions.Item label={t("最不利点(μs)")}>
                {typeof detailSelectedCase.head_time_us === "number" && typeof detailSelectedCase.tail_time_us === "number"
                  ? `${detailSelectedCase.head_time_us}/${detailSelectedCase.tail_time_us}`
                  : "-"}
              </Descriptions.Item>
              <Descriptions.Item label={t("扫描点数")}>{String(detailWorkflow.scan_point_count ?? "-")}</Descriptions.Item>
              <Descriptions.Item label={t("雷电流波形")}>{formatCurrentWaveform(detailWorkflow.current_waveform, t)}</Descriptions.Item>
              <Descriptions.Item label={t("绝缘子闪络判据")}>{formatFlashoverMethod(detailWorkflow.flashover_method, t)}</Descriptions.Item>
              <Descriptions.Item label={t("是否海拔修正")}>{formatAltitudeCorrection(detailWorkflow.altitude_correction, t)}</Descriptions.Item>
              <Descriptions.Item label={t("感应电压公式")}>{formatInducedVoltageFormula(detailWorkflow.induced_voltage_formula, t)}</Descriptions.Item>
              <Descriptions.Item label={t("波头范围")}>{formatRangeSummary(detailWorkflow.head_time_range_us, t)}</Descriptions.Item>
              <Descriptions.Item label={t("波尾范围")}>{formatRangeSummary(detailWorkflow.tail_time_range_us, t)}</Descriptions.Item>
              <Descriptions.Item label={t("执行适配器")}>
                {formatExternalAdapter(readOptionalString(detailExternalExecution, "adapter"), t)}
              </Descriptions.Item>
              <Descriptions.Item label={t("ATP模型")}>
                {formatAtpModel(readOptionalString(detailExternalExecution, "model_name") || readOptionalString(detailExternalExecution, "model_code"), t)}
              </Descriptions.Item>
              {selectedJobDetailWaveformType === "tongtiao" ? (
                <>
                  <Descriptions.Item label={t("主导相组")}>{readOptionalString(detailResultObject, "dominant_phase_set") ?? "-"}</Descriptions.Item>
                  <Descriptions.Item label={t("闪络相")}>{readOptionalString(detailResultObject, "flashover_phase") ?? "-"}</Descriptions.Item>
                </>
              ) : null}
              {/* 计算参数固定 11 项（同跳另加 2 项），均为奇数，会导致其后的整行项(span=2)
                  触发 antd "Sum of column span ... not match column" 告警并将整行降宽；
                  此处补一个空项凑成偶数行。 */}
              <Descriptions.Item label="">{""}</Descriptions.Item>
            </>
          ) : null}
        </Descriptions>
      </div>

      <ReasonDetailsTable reasonDetails={reasonDetails} t={t} />

      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <div>
          <Typography.Title level={5}>{t("波形扫描")}</Typography.Title>
          {scanPoints.length === 0 ? (
            <Empty description={t("当前结果未生成扫描点")} />
          ) : (
            <Table<ScanPoint>
              rowKey={(row) => `${row.head_time_us ?? "-"}-${row.tail_time_us ?? "-"}`}
              columns={buildScanPointColumns(t)}
              dataSource={scanPoints}
              pagination={false}
              size="small"
              scroll={{ x: 1000 }}
            />
          )}
        </div>
      ) : null}

      {selectedJobDetailWaveformType === "tongtiao" ? (
        <>
          <div>
            <Typography.Title level={5}>{t("相别结果")}</Typography.Title>
            {phaseResults.length === 0 ? (
              <Empty description={t("当前结果未生成相别结果")} />
            ) : (
              <Table<PhaseResult>
                rowKey="phase"
                columns={buildPhaseResultColumns(t)}
                dataSource={phaseResults}
                pagination={false}
                size="small"
                scroll={{ x: 1200 }}
              />
            )}
          </div>

          <div>
            <Typography.Title level={5}>{t("多相结果")}</Typography.Title>
            {multiPhaseResults.length === 0 ? (
              <Empty description={t("当前结果未生成多相结果")} />
            ) : (
              <Table<MultiPhaseResult>
                rowKey="label"
                columns={buildMultiPhaseColumns(t)}
                dataSource={multiPhaseResults}
                pagination={false}
                size="small"
                scroll={{ x: 900 }}
              />
            )}
          </div>
        </>
      ) : null}

      <ComputationSteps steps={computationSteps} t={t} />

      <ConclusionText
        summaryText={readOptionalString(detailRow, "summary_text")}
        causeAnalysis={readString(detailResultObject, "cause_analysis")}
        lang={lang}
        t={t}
      />
    </Space>
  );
}
