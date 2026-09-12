"use client";

import { Alert, Button, Descriptions, Divider, Empty, Space, Spin, Tag } from "antd";

import type {
  FlAnalysisJobDetail,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatAltitudeCorrection,
  formatCurrentWaveform,
  formatDateTime,
  formatDimensionValue,
  formatFlashoverMethod,
  formatInducedVoltageFormula,
  formatJobType,
  formatRangeSummary,
  mitigationMode,
  readObject,
  readOptionalNumber,
  readOptionalString,
  selectedTowerCount,
  statusColor,
  type WorkflowSummary,
} from "./types";
import { useFlDimensionOptions } from "./use-fl-dimensions";

type JobDetailPanelProps = {
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
  candidateScenarioBaseJobs: FlAnalysisJobSummary[];
  candidateReportRows: FlAnalysisTowerResultSummary[];
  startPending: boolean;
  downloadReportPending: boolean;
  onStart: () => void;
  onOpenMitigation: () => void;
  onOpenScenario: () => void;
  onOpenReport: () => void;
  onDownloadReport: () => void;
};

const JOB_STATUS_TEXT: Record<string, string> = {
  pending: "待执行",
  queued: "排队中",
  running: "执行中",
  success: "已完成",
  failed: "失败",
  cancelled: "已取消",
  canceled: "已取消",
};

// 完成时间：年月日之间用横杠（YYYY-MM-DD HH:mm）
function formatFinishedAt(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace(/\//g, "-");
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function JobDetailPanel({
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
  candidateScenarioBaseJobs,
  candidateReportRows,
  startPending,
  downloadReportPending,
  onStart,
  onOpenMitigation,
  onOpenScenario,
  onOpenReport,
  onDownloadReport,
}: JobDetailPanelProps) {
  const { labelMap } = useFlDimensionOptions();

  if (loading) {
    return <Spin />;
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error instanceof Error ? error.message : "任务详情加载失败"}
      />
    );
  }

  if (!selectedJobDetail || !selectedJob) {
    return <Empty description="暂无任务详情" />;
  }

  const selectedJobExecutionOptions = readObject(selectedJobDetail.execution_options_json);
  const selectedJobSummary = readObject(selectedJobDetail.result_summary_json);
  const selectedJobWorkflow = readObject(selectedJobDetail.result_summary_json).workflow as WorkflowSummary | undefined;
  const selectedJobExternalModelCode = readOptionalString(selectedJobSummary, "external_model_code");
  const selectedJobExternalModelName = readOptionalString(selectedJobSummary, "external_model_name");
  const selectedJobExternalVersionNo = readOptionalNumber(selectedJobSummary, "external_version_no");
  const sourceJobId = readOptionalString(selectedJobExecutionOptions, "source_job_id");
  const scenarioBaseJobName = readOptionalString(selectedJobExecutionOptions, "base_job_name");
  const scenarioBaseJobType = readOptionalString(selectedJobExecutionOptions, "base_job_type");
  const reportSourceJobType = readOptionalString(selectedJobSummary, "source_job_type");
  const reportSourceJobName = readOptionalString(selectedJobSummary, "source_job_name");
  const reportMitigationJobName = readOptionalString(selectedJobSummary, "mitigation_job_name");
  const reportScenarioJobName = readOptionalString(selectedJobSummary, "scenario_job_name");
  const reportDocumentName = readOptionalString(selectedJobSummary, "document_filename");


  const METHOD_TEXT: Record<string, string> = {
    egm: "EGM",
    guicheng: "规程",
    guideline: "规程法",
    intersection: "相交法",
    leader_development: "先导发展法",
    xiangjiao: "相交法",
    xiandao: "先导发展法",
    none: "无",
  };
  const showMethod = (v: unknown) => (typeof v === "string" && v ? (METHOD_TEXT[v] ?? v) : "-");
  // ATP 模型：把 "atp500-guxing-fanji-M1" 这类编码翻译成中文，不展示编码
  const ATP_TOWER_TEXT: Record<string, string> = {
    guxing: "鼓型", maotou: "猫头型", ganzi: "干字型", jiubei: "酒杯型",
    menxing: "门型", shangzi: "上字型", sihuita: "四回塔", zhiliu: "直流塔",
  };
  const ATP_SCENE_TEXT: Record<string, string> = {
    fanji: "反击", raoji: "绕击", raoji1: "绕击1", raoji2: "绕击2", raoji3: "绕击3",
  };
  const formatAtpModel = (src?: string | null) => {
    const text = (src || "").trim();
    if (!text) return "-";
    const parts = text.split("-").filter(Boolean);
    const kv = parts.find((part) => /kv/i.test(part));
    const label = kv ? `${kv.replace(/^atp/i, "").toUpperCase()}` : "";
    const rest = parts
      .filter((part) => part !== kv && !/^atp\d*$/i.test(part))
      .map((part) => {
        const key = part.toLowerCase();
        if (ATP_TOWER_TEXT[key]) return ATP_TOWER_TEXT[key];
        if (ATP_SCENE_TEXT[key]) return ATP_SCENE_TEXT[key];
        const arrester = /^M\d+/i.exec(part);
        if (arrester) return `避雷器组合 ${arrester[0].toUpperCase()}`;
        return part;
      });
    return [label, ...rest].filter(Boolean).join(" ") || "-";
  };
  // 风险计数：high/medium/low → 高/中/低风险 + 座数
  const formatRiskCounts = (counts?: unknown) => {
    if (!counts || typeof counts !== "object") return "-";
    const map: Array<[string, string]> = [["high", "高风险"], ["medium", "中风险"], ["low", "低风险"]];
    const record = counts as Record<string, unknown>;
    const parts = map
      .filter(([key]) => record[key] !== undefined && record[key] !== null)
      .map(([key, label]) => `${label} ${Number(record[key]) || 0} 座`);
    const extra = Object.entries(record)
      .filter(([key]) => !map.some(([k]) => k === key))
      .map(([key, value]) => `${key} ${value}`);
    const all = [...parts, ...extra];
    return all.length ? all.join("；") : "无";
  };
  return (
    <Space direction="vertical" size={16} className="flex w-full">
      <section className="fl-create-form-block">
        <div className="fl-create-form-block-title">任务信息</div>
        <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label="任务名称">{selectedJobDetail.job_name || "-"}</Descriptions.Item>
        <Descriptions.Item label="任务状态">
          <Tag color={statusColor(selectedJobDetail.status)}>{JOB_STATUS_TEXT[selectedJobDetail.status] ?? selectedJobDetail.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="线路">{selectedJobDetail.line_name || selectedJobDetail.line_code || "-"}</Descriptions.Item>
        <Descriptions.Item label="任务类型">{formatJobType(selectedJobDetail.job_type, mitigationMode(selectedJobDetail))}</Descriptions.Item>
        <Descriptions.Item label="结果杆塔数">{selectedJobDetail.result_tower_count}</Descriptions.Item>
        <Descriptions.Item label="完成时间">{formatFinishedAt(selectedJobDetail.finished_at)}</Descriptions.Item>
        {selectedJobDetail.job_type === "mitigation" ? (
          <>
            <Descriptions.Item label="前驱风险任务">{sourceJobId || "-"}</Descriptions.Item>
            <Descriptions.Item label="选塔数">{String(selectedTowerCount(selectedJobDetail) || "-")}</Descriptions.Item>
            <Descriptions.Item label="模式">{mitigationMode(selectedJobDetail) ? "非建线" : "常规建线"}</Descriptions.Item>
            <Descriptions.Item label="需装避雷器数">
              {String(readObject(selectedJobDetail.result_summary_json).arrester_required_count ?? "-")}
            </Descriptions.Item>
          </>
        ) : selectedJobDetail.job_type === "scenario" ? (
          <>
            <Descriptions.Item label="前驱措施任务">{sourceJobId || "-"}</Descriptions.Item>
            <Descriptions.Item label="选塔数">{String(selectedTowerCount(selectedJobDetail) || "-")}</Descriptions.Item>
            <Descriptions.Item label="复用计算口径">
              {scenarioBaseJobType ? formatJobType(scenarioBaseJobType) : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="基线计算任务">{scenarioBaseJobName || "-"}</Descriptions.Item>
          </>
        ) : selectedJobDetail.job_type === "report" ? (
          <>
            <Descriptions.Item label="报告来源">
              {reportSourceJobType ? formatJobType(reportSourceJobType) : "-"}
              {reportSourceJobName ? ` / ${reportSourceJobName}` : ""}
            </Descriptions.Item>
            <Descriptions.Item label="选塔数">
              {String(readObject(selectedJobDetail.result_summary_json).selected_tower_count ?? "-")}
            </Descriptions.Item>
            <Descriptions.Item label="关联措施任务">{reportMitigationJobName || "未关联"}</Descriptions.Item>
            <Descriptions.Item label="关联复算任务">{reportScenarioJobName || "未关联"}</Descriptions.Item>
            <Descriptions.Item label="文档名" span={2}>{reportDocumentName || "-"}</Descriptions.Item>
          </>
        ) : null}
                <Descriptions.Item label="风险计数" span={2}>{formatRiskCounts(selectedJobDetail.result_summary_json?.risk_counts)}</Descriptions.Item>
</Descriptions>
      </section>

      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <section className="fl-create-form-block">
          <div className="fl-create-form-block-title">计算方法</div>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="反击耐雷水平计算方法">{showMethod(readObject(selectedJobExecutionOptions).fanji_naleishuiping_method)}</Descriptions.Item>
            <Descriptions.Item label="绕击耐雷水平计算方法">{showMethod(readObject(selectedJobExecutionOptions).raoji_naleishuiping_method)}</Descriptions.Item>
            <Descriptions.Item label="反击跳闸率计算方法">{showMethod(readObject(selectedJobExecutionOptions).fanji_tzl_method)}</Descriptions.Item>
            <Descriptions.Item label="绕击跳闸率计算方法">{showMethod(readObject(selectedJobExecutionOptions).raoji_tzl_method)}</Descriptions.Item>
            <Descriptions.Item label="ATP模型">{formatAtpModel(selectedJobExternalModelName || selectedJobExternalModelCode)}</Descriptions.Item>
          </Descriptions>
        </section>
      ) : null}

      {selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao" ? (
        <section className="fl-create-form-block">
          <div className="fl-create-form-block-title">高级参数</div>
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="雷电流波形">{formatDimensionValue(selectedJobWorkflow?.current_waveform, labelMap.current_waveform, formatCurrentWaveform)}</Descriptions.Item>
            <Descriptions.Item label="绝缘子闪络判据">{formatDimensionValue(selectedJobWorkflow?.flashover_method, labelMap.flashover_method, formatFlashoverMethod)}</Descriptions.Item>
            <Descriptions.Item label="是否海拔修正">{formatDimensionValue(selectedJobWorkflow?.altitude_correction, labelMap.altitude_correction, formatAltitudeCorrection)}</Descriptions.Item>
            <Descriptions.Item label="感应电压公式">{formatInducedVoltageFormula(selectedJobWorkflow?.induced_voltage_formula)}</Descriptions.Item>
            <Descriptions.Item label="波头范围">{formatRangeSummary(selectedJobWorkflow?.head_time_range_us)}</Descriptions.Item>
            <Descriptions.Item label="波尾范围">{formatRangeSummary(selectedJobWorkflow?.tail_time_range_us)}</Descriptions.Item>
          </Descriptions>
        </section>
      ) : null}


      {canManage || selectedJob.job_type === "report" ? (
        <Space size={12} wrap split={<Divider type="vertical" />}>
          {canManage ? (
            <Space wrap>
              {/* 已完成的成功任务不再提供「重新执行任务」入口（结果详情页要求） */}
              {selectedJob.status === "success" ? null : (
                <Button onClick={onStart} loading={startPending}>
                  启动任务
                </Button>
              )}
            </Space>
          ) : null}
          {canManage && (canCreateMitigation || canCreateScenario || canCreateReport) ? (
            <Space wrap>
              {canCreateMitigation ? (
                <Button
                  type="primary"
                  disabled={candidateMitigationRows.length === 0}
                  onClick={onOpenMitigation}
                >
                  生成措施推荐
                </Button>
              ) : null}
              {canCreateScenario ? (
                <Button
                  disabled={candidateScenarioRows.length === 0 || candidateScenarioBaseJobs.length === 0}
                  onClick={onOpenScenario}
                >
                  加装避雷器复算
                </Button>
              ) : null}
              {canCreateReport ? (
                <Button
                  disabled={candidateReportRows.length === 0}
                  onClick={onOpenReport}
                >
                  生成报告
                </Button>
              ) : null}
            </Space>
          ) : null}
          <Space wrap>
            {selectedJob.job_type === "report" ? (
              <Button
                type="primary"
                onClick={onDownloadReport}
                loading={downloadReportPending}
                disabled={selectedJob.status !== "success"}
              >
                下载报告
              </Button>
            ) : null}
          </Space>
        </Space>
      ) : null}
    </Space>
  );
}
