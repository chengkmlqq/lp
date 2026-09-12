"use client";

import { Button, Descriptions, Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import type { ReactNode } from "react";

import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatAltitudeCorrection,
  formatCurrentWaveform,
  formatDimensionValue,
  formatExternalAdapter,
  formatFlashoverMethod,
  formatInducedVoltageFormula,
  formatJobType,
  formatRangeSummary,
  formatRiskLevel,
  mitigationMode,
  readCurrentRisk,
  readCurrentScore,
  readMitigationActions,
  readMultiPhaseResults,
  readObject,
  readOptionalNumber,
  readOptionalString,
  readPhaseResults,
  readReasonDetails,
  readScanPoints,
  readSelectedCase,
  readString,
  readWorkflow,
  riskColor,
  waveformJobType,
  type MitigationAction,
  type MultiPhaseResult,
  type PhaseResult,
  type ReasonDetail,
  type ScanPoint,
} from "./types";
import { useFlDimensionOptions } from "./use-fl-dimensions";

const reasonDetailColumns: ColumnsType<ReasonDetail> = [
  { title: "因子", dataIndex: "label", width: 180 },
  {
    title: "当前值",
    key: "value",
    render: (_value, row) => (row.value === undefined || row.value === null ? "-" : String(row.value)),
  },
  {
    title: "标准值",
    key: "standard_value",
    render: (_value, row) => (row.standard_value === undefined || row.standard_value === null ? "-" : String(row.standard_value)),
  },
  {
    title: "档次",
    dataIndex: "grade",
    width: 90,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "是否命中",
    dataIndex: "triggered",
    width: 100,
    render: (value: boolean | undefined) => (value ? <Tag color="red">是</Tag> : <Tag>否</Tag>),
  },
];

const mitigationActionColumns: ColumnsType<MitigationAction> = [
  { title: "动作", dataIndex: "label", width: 160 },
  { title: "建议", dataIndex: "summary" },
  {
    title: "当前值",
    key: "current_value",
    render: (_value, row) => (row.current_value === undefined || row.current_value === null ? "-" : String(row.current_value)),
    width: 100,
  },
  {
    title: "目标值",
    key: "target_value",
    render: (_value, row) => (row.target_value === undefined || row.target_value === null ? "-" : String(row.target_value)),
    width: 100,
  },
];

const scanPointColumns: ColumnsType<ScanPoint> = [
  { title: "波头(μs)", dataIndex: "head_time_us", width: 100, render: (value: number | null | undefined) => value ?? "-" },
  { title: "波尾(μs)", dataIndex: "tail_time_us", width: 100, render: (value: number | null | undefined) => value ?? "-" },
  {
    title: "风险",
    dataIndex: "risk_level",
    width: 100,
    render: (value: string | null | undefined) => <Tag color={riskColor(value)}>{formatRiskLevel(value)}</Tag>,
  },
  { title: "得分", dataIndex: "score", width: 90, render: (value: number | null | undefined) => value ?? "-" },
  {
    title: "反击跳闸率",
    dataIndex: "counterstrike_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "绕击跳闸率",
    dataIndex: "shielding_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "闪络相",
    dataIndex: "flashover_phase",
    width: 160,
    render: (value: string | null | undefined) => value || "-",
  },
];

const phaseResultColumns: ColumnsType<PhaseResult> = [
  { title: "相别", dataIndex: "phase", width: 120 },
  { title: "回路", dataIndex: "circuit", width: 90, render: (value: string | null | undefined) => value || "-" },
  {
    title: "A/B/C绕击耐雷水平(kA)",
    dataIndex: "shielding_withstand_ka",
    width: 180,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "A/B/C绕击跳闸率",
    dataIndex: "shielding_trip_rate",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "反击耐雷水平(kA)",
    dataIndex: "counterstrike_withstand_ka",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "反击跳闸率",
    dataIndex: "counterstrike_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
];

const multiPhaseColumns: ColumnsType<MultiPhaseResult> = [
  { title: "相数组合", dataIndex: "label", width: 100 },
  { title: "闪络相", dataIndex: "flashover_phase", render: (value: string | null | undefined) => value || "-" },
  {
    title: "反击耐雷水平(kA)",
    dataIndex: "counterstrike_withstand_ka",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: "跳闸率",
    dataIndex: "trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
];

/**
 * 杆塔详情内容组件（LP-274）。
 * 由原 DetailModal 的展示主体抽出，作为动态选项卡（Tabs editable-card）各 Tab 的 children
 * 直接渲染，不再依赖 Modal 承载。Job 维度信息（任务名、任务类型）随 detailRow 一并展示，
 * 便于多任务对比时区分来源。
 */
export function TowerDetailView({
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
}): ReactNode {
  const { labelMap } = useFlDimensionOptions();
  const detailResultObject = readObject(detailRow.result_json);
  const reasonDetails = readReasonDetails(detailRow);
  const mitigationActions = readMitigationActions(detailRow);
  const scanPoints = readScanPoints(detailRow);
  const phaseResults = readPhaseResults(detailRow);
  const multiPhaseResults = readMultiPhaseResults(detailRow);
  const detailWorkflow = readWorkflow(detailRow);
  const detailSelectedCase = readSelectedCase(detailRow);
  const selectedJobDetailWaveformType = waveformJobType(selectedJobDetail ?? selectedJob);
  const detailExternalExecution = readObject(detailResultObject.external_execution);

  return (
    <Space direction="vertical" size={24} className="flex w-full">
      <Space className="flex w-full" style={{ justifyContent: "space-between" }} align="center">
        <Typography.Text type="secondary" style={{ marginBottom: 0 }}>
          任务：{selectedJob?.job_name || selectedJob?.line_name || selectedJob?.line_code || "-"
            }（{selectedJob ? formatJobType(selectedJob.job_type, mitigationMode(selectedJob)) : "-"}）
        </Typography.Text>
        {canReadLogs && onOpenLog ? (
          <Button
            size="small"
            disabled={!selectedJob?.task_id}
            onClick={() => onOpenLog(
              selectedJob?.task_id,
              "任务执行日志",
              selectedJob?.job_name || selectedJob?.line_name || selectedJob?.line_code || "防雷任务",
            )}
          >
            查看日志
          </Button>
        ) : null}
      </Space>
      <div>
      <Typography.Title level={5}>
        基本信息
      </Typography.Title>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="当前结论">{detailRow.summary_text || "-"}</Descriptions.Item>
        <Descriptions.Item label={selectedJob?.job_type === "mitigation" ? "预期风险/风险等级" : "风险等级"}>
          <Tag color={riskColor(detailRow.risk_level)}>{formatRiskLevel(detailRow.risk_level)}</Tag>
        </Descriptions.Item>
        {selectedJob?.job_type === "mitigation" ? (
          <>
            <Descriptions.Item label="当前风险">
              <Tag color={riskColor(readCurrentRisk(detailRow))}>{formatRiskLevel(readCurrentRisk(detailRow))}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="改造结论">{readString(detailResultObject, "recommendation_result")}</Descriptions.Item>
          </>
        ) : selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
          <>
            <Descriptions.Item label="最不利点(μs)">
              {typeof detailSelectedCase.head_time_us === "number" && typeof detailSelectedCase.tail_time_us === "number"
                ? `${detailSelectedCase.head_time_us}/${detailSelectedCase.tail_time_us}`
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="扫描点数">{String(detailWorkflow.scan_point_count ?? "-")}</Descriptions.Item>
            <Descriptions.Item label="雷电流波形">{formatDimensionValue(detailWorkflow.current_waveform, labelMap.current_waveform, formatCurrentWaveform)}</Descriptions.Item>
            <Descriptions.Item label="绝缘子闪络判据">{formatDimensionValue(detailWorkflow.flashover_method, labelMap.flashover_method, formatFlashoverMethod)}</Descriptions.Item>
            <Descriptions.Item label="是否海拔修正">{formatDimensionValue(detailWorkflow.altitude_correction, labelMap.altitude_correction, formatAltitudeCorrection)}</Descriptions.Item>
            <Descriptions.Item label="感应电压公式">{formatInducedVoltageFormula(detailWorkflow.induced_voltage_formula)}</Descriptions.Item>
            <Descriptions.Item label="波头范围">{formatRangeSummary(detailWorkflow.head_time_range_us)}</Descriptions.Item>
            <Descriptions.Item label="波尾范围">{formatRangeSummary(detailWorkflow.tail_time_range_us)}</Descriptions.Item>
            <Descriptions.Item label="执行适配器">
              {formatExternalAdapter(readOptionalString(detailExternalExecution, "adapter"))}
            </Descriptions.Item>
            <Descriptions.Item label="ATP模型">
              {readOptionalString(detailExternalExecution, "model_name") || readOptionalString(detailExternalExecution, "model_code") || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="模型版本">
              {typeof readOptionalNumber(detailExternalExecution, "version_no") === "number"
                ? `v${readOptionalNumber(detailExternalExecution, "version_no")}`
                : "-"}
            </Descriptions.Item>
            {selectedJobDetailWaveformType === "tongtiao" ? (
              <>
                <Descriptions.Item label="主导相组">{readOptionalString(detailResultObject, "dominant_phase_set") ?? "-"}</Descriptions.Item>
                <Descriptions.Item label="闪络相">{readOptionalString(detailResultObject, "flashover_phase") ?? "-"}</Descriptions.Item>
              </>
            ) : null}
            {/* 计算参数固定 11 项（同跳另加 2 项），均为奇数，会导致其后的整行项(span=2)
                触发 antd "Sum of column span ... not match column" 告警并将整行降宽；
                此处补一个空项凑成偶数行。 */}
            <Descriptions.Item label="">{""}</Descriptions.Item>
          </>
        ) : null}
        <Descriptions.Item label="原因分析" span={2}>
          {readString(detailResultObject, "cause_analysis")}
        </Descriptions.Item>
        <Descriptions.Item label="措施建议" span={2}>
          {readString(detailResultObject, "mitigation_recommendation")}
        </Descriptions.Item>
        <Descriptions.Item label="当前得分">
          {selectedJob?.job_type === "mitigation"
            ? String(readCurrentScore(detailRow) ?? "-")
            : String(readOptionalNumber(detailResultObject, "score") ?? "-")}
        </Descriptions.Item>
        <Descriptions.Item label="预期得分/得分">
          {selectedJob?.job_type === "mitigation"
            ? String(readOptionalNumber(detailResultObject, "expected_score") ?? "-")
            : String(readOptionalNumber(detailResultObject, "score") ?? "-")}
        </Descriptions.Item>
      </Descriptions>
      </div>

      <div>
      <Typography.Title level={5}>
        原因细项
      </Typography.Title>
      {reasonDetails.length === 0 ? (
        <Empty description="暂无细项分级" />
      ) : (
        <Table<ReasonDetail>
          rowKey="code"
          columns={reasonDetailColumns}
          dataSource={reasonDetails}
          pagination={false}
          size="small"
        />
      )}
      </div>

      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <>
          <div>
          <Typography.Title level={5}>
            波形扫描
          </Typography.Title>
          {scanPoints.length === 0 ? (
            <Empty description="当前结果未生成扫描点" />
          ) : (
            <Table<ScanPoint>
              rowKey={(row) => `${row.head_time_us ?? "-"}-${row.tail_time_us ?? "-"}`}
              columns={scanPointColumns}
              dataSource={scanPoints}
              pagination={false}
              size="small"
              scroll={{ x: 1000 }}
            />
          )}
          </div>
        </>
      ) : null}

      {selectedJobDetailWaveformType === "tongtiao" ? (
        <>
          <div>
          <Typography.Title level={5}>
            相别结果
          </Typography.Title>
          {phaseResults.length === 0 ? (
            <Empty description="当前结果未生成相别结果" />
          ) : (
            <Table<PhaseResult>
              rowKey="phase"
              columns={phaseResultColumns}
              dataSource={phaseResults}
              pagination={false}
              size="small"
              scroll={{ x: 1200 }}
            />
          )}
          </div>

          <div>
          <Typography.Title level={5}>
            多相结果
          </Typography.Title>
          {multiPhaseResults.length === 0 ? (
            <Empty description="当前结果未生成多相结果" />
          ) : (
            <Table<MultiPhaseResult>
              rowKey="label"
              columns={multiPhaseColumns}
              dataSource={multiPhaseResults}
              pagination={false}
              size="small"
              scroll={{ x: 900 }}
            />
          )}
          </div>
        </>
      ) : null}

      <div>
      <Typography.Title level={5}>
        改造动作
      </Typography.Title>
      {mitigationActions.length === 0 ? (
        <Empty description="当前结果未生成改造动作" />
      ) : (
        <Table<MitigationAction>
          rowKey="code"
          columns={mitigationActionColumns}
          dataSource={mitigationActions}
          pagination={false}
          size="small"
        />
      )}
      </div>
    </Space>
  );
}
