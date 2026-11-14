"use client";

import { Alert, Button, Collapse, Descriptions, Divider, Empty, Space, Table, Tag, Typography } from "antd";
import { useI18n, type AppLang } from "@/lib/i18n";
import { translateAnalysisText } from "@/lib/analysis-text";

const ATP_TOWER_TEXT: Record<string, string> = {
  guxing: "鼓型", maotou: "猫头型", ganzi: "干字型", jiubei: "酒杯型",
  menxing: "门型", shangzi: "上字型", sihuita: "四回塔", zhiliu: "直流塔",
};
const ATP_SCENE_TEXT: Record<string, string> = {
  fanji: "反击", raoji: "绕击", raoji1: "绕击1", raoji2: "绕击2", raoji3: "绕击3",
};

/** ATP 模型编码 → 中文（如 atp500-guxing-fanji-M1 → 500kV 鼓型 反击 避雷器组合 M1） */
export function formatAtpModel(
  src: string | null | undefined,
  t: (s: string) => string,
  version?: string | null,
) {
  const text = (src || "").trim();
  if (!text) return "-";
  const parts = text.split("-").filter(Boolean);
  const kv = parts.find((part) => /kv/i.test(part));
  const label = kv ? `${kv.replace(/^atp/i, "").toUpperCase()}` : "";
  const rest = parts
    .filter((part) => part !== kv && !/^atp\d*$/i.test(part))
    .map((part) => {
      const key = part.toLowerCase();
      if (ATP_TOWER_TEXT[key]) return t(ATP_TOWER_TEXT[key]);
      if (ATP_SCENE_TEXT[key]) return t(ATP_SCENE_TEXT[key]);
      const arrester = /^M\d+/i.exec(part);
      if (arrester) return `${t("避雷器组合")} ${arrester[0].toUpperCase()}`;
      return part;
    });
  const base = [label, ...rest].filter(Boolean).join(" ") || "-";
  const ver = (version || "").trim();
  return ver ? `${base} · ${ver}` : base;
}

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
  formatFlashoverMethod,
  formatInducedVoltageFormula,
  formatJobType,
  formatRangeSummary,
  formatRiskLevel,
  mitigationMode,
  riskColor,
  statusColor,
  type ReasonDetail,
  type MitigationAction,
  type ScanPoint,
  type PhaseResult,
  type MultiPhaseResult,
} from "./types";

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
export function formatFinishedAt(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace(/\//g, "-");
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ---- 风险标签 ----
export function RiskTag({ value, t }: { value?: string | null; t: (s: string) => string }) {
  return <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>;
}

// ---- 原因细项表格 ----
export const buildReasonDetailColumns = (t: (s: string) => string): ColumnsType<ReasonDetail> => [
  {
    title: t("因子"),
    dataIndex: "label",
    width: 180,
    render: (value: string) => t(value),
  },
  {
    title: t("当前值"),
    key: "value",
    render: (_value, row) => {
      if (row.value === undefined || row.value === null) {
        return "-";
      }
      return typeof row.value === "string" ? t(row.value) : String(row.value);
    },
  },
  {
    title: t("标准值"),
    key: "standard_value",
    render: (_value, row) => {
      if (row.standard_value === undefined || row.standard_value === null) {
        return "-";
      }
      return typeof row.standard_value === "string" ? t(row.standard_value) : String(row.standard_value);
    },
  },
  {
    title: t("档次"),
    dataIndex: "grade",
    width: 90,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("是否命中"),
    dataIndex: "triggered",
    width: 100,
    render: (value: boolean | undefined) => (value ? <Tag color="red">{t("是")}</Tag> : <Tag>{t("否")}</Tag>),
  },
];

// ---- 改造动作表格 ----
export const buildMitigationActionColumns = (t: (s: string) => string): ColumnsType<MitigationAction> => [
  { title: t("动作"), dataIndex: "label", width: 160 },
  { title: t("建议"), dataIndex: "summary" },
  {
    title: t("当前值"),
    key: "current_value",
    render: (_value, row) => (row.current_value === undefined || row.current_value === null ? "-" : String(row.current_value)),
    width: 100,
  },
  {
    title: t("目标值"),
    key: "target_value",
    render: (_value, row) => (row.target_value === undefined || row.target_value === null ? "-" : String(row.target_value)),
    width: 100,
  },
];

// ---- 波形扫描表格 ----
export const buildScanPointColumns = (t: (s: string) => string): ColumnsType<ScanPoint> => [
  { title: t("波头(μs)"), dataIndex: "head_time_us", width: 100, render: (value: number | null | undefined) => value ?? "-" },
  { title: t("波尾(μs)"), dataIndex: "tail_time_us", width: 100, render: (value: number | null | undefined) => value ?? "-" },
  {
    title: t("风险"),
    dataIndex: "risk_level",
    width: 100,
    render: (value: string | null | undefined) => <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>,
  },
  { title: t("得分"), dataIndex: "score", width: 90, render: (value: number | null | undefined) => value ?? "-" },
  {
    title: t("反击跳闸率"),
    dataIndex: "counterstrike_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("绕击跳闸率"),
    dataIndex: "shielding_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("闪络相"),
    dataIndex: "flashover_phase",
    width: 160,
    render: (value: string | null | undefined) => value || "-",
  },
];

// ---- 相别结果表格 ----
export const buildPhaseResultColumns = (t: (s: string) => string): ColumnsType<PhaseResult> => [
  { title: t("相别"), dataIndex: "phase", width: 120 },
  { title: t("回路"), dataIndex: "circuit", width: 90, render: (value: string | null | undefined) => value || "-" },
  {
    title: t("A/B/C绕击耐雷水平(kA)"),
    dataIndex: "shielding_withstand_ka",
    width: 180,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("A/B/C绕击跳闸率"),
    dataIndex: "shielding_trip_rate",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("反击耐雷水平(kA)"),
    dataIndex: "counterstrike_withstand_ka",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("反击跳闸率"),
    dataIndex: "counterstrike_trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
];

// ---- 多相结果表格 ----
export const buildMultiPhaseColumns = (t: (s: string) => string): ColumnsType<MultiPhaseResult> => [
  { title: t("相数组合"), dataIndex: "label", width: 100 },
  { title: t("闪络相"), dataIndex: "flashover_phase", render: (value: string | null | undefined) => value || "-" },
  {
    title: t("反击耐雷水平(kA)"),
    dataIndex: "counterstrike_withstand_ka",
    width: 140,
    render: (value: number | null | undefined) => value ?? "-",
  },
  {
    title: t("跳闸率"),
    dataIndex: "trip_rate",
    width: 120,
    render: (value: number | null | undefined) => value ?? "-",
  },
];

/** 二分搜索的扫描历史一行（对应后端 binary_search.search_history） */
interface BinarySearchStepItem {
  iteration: number;
  current_ka: number | null;
  flashover_count: number | null;
  low: number | null;
  high: number | null;
}

/** 计算过程：可展开步骤项 */
interface ComputationStepItem {
  key: string;
  header: string;
  summaryRows: { label: string; value: string }[];
  scanItems: BinarySearchStepItem[];
}

/**
 * 从单塔 result_json 构建「计算过程」步骤（仿故障分析 · 计算过程 tab 的可展开步骤）。
 * 数据全部来自已落库结果：binary_search（反击二分）/ multi_phase_results（同跳各相）/
 * shielding_binary_search（绕击二分）。不增加后端计算负担、不改计算结果。
 */
export function buildComputationSteps(
  resultObject: Record<string, unknown> | undefined,
  waveformType: string | null,
  t: (s: string) => string,
): ComputationStepItem[] {
  const steps: ComputationStepItem[] = [];
  if (!resultObject) return steps;

  const readNum = (v: unknown): number | null => (typeof v === "number" ? v : null);
  const fmt = (v: number | null | undefined, suffix = ""): string =>
    v === null || v === undefined ? "-" : `${v.toFixed(4)}${suffix}`;

  // 通用：把一次二分搜索渲染成步骤
  const binarySearchSteps = (
    prefix: string,
    search: Record<string, unknown> | undefined,
    keyBase: string,
  ) => {
    if (!search) return;
    const history = Array.isArray(search.search_history) ? search.search_history : [];
    const scanItems: BinarySearchStepItem[] = history
      .map((row: unknown) => {
        const r = (row || {}) as Record<string, unknown>;
        return {
          iteration: readNum(r.iteration) ?? 0,
          current_ka: readNum(r.current_ka),
          flashover_count: readNum(r.flashover_count),
          low: readNum(r.low),
          high: readNum(r.high),
        };
      })
      .filter((item) => item.current_ka !== null);
    const finalWithstand = readNum(search.final_withstand_ka);
    const converged = Boolean(search.converged);
    const target = readNum(search.target_flashover_phases);
    steps.push({
      key: `${keyBase}-${target ?? "x"}`,
      header: `${prefix}（${t("目标闪络相数")} ≥ ${target ?? "?"}）`,
      summaryRows: [
        { label: t("收敛"), value: converged ? t("是") : t("否") },
        { label: t("耐雷水平(kA)"), value: fmt(finalWithstand) },
        { label: t("扫描次数"), value: String(scanItems.length) },
      ],
      scanItems,
    });
  };

  // 反击二分（normal 单相 / tongtiao 主结果）
  const binarySearch = resultObject.binary_search as Record<string, unknown> | undefined;
  if (binarySearch) {
    binarySearchSteps(t("反击二分"), binarySearch, "counterstrike");
  }

  // 同跳各相二分：完整 search_history 在 multi_phase_binary_search.phase_entries
  // （每个 entry 含 phase_count/label/counterstrike_withstand_ka/trip_rate/converged/
  //   search_history），multi_phase_results 仅有摘要、无 search_history（旧数据源，
  //   保留作 fallback 兼容历史记录）。
  const bsEntries =
    Array.isArray((resultObject.multi_phase_binary_search as Record<string, unknown> | undefined)?.phase_entries)
      ? ((resultObject.multi_phase_binary_search as Record<string, unknown>).phase_entries as Record<string, unknown>[])
      : null;
  const multiPhaseFallback = Array.isArray(resultObject.multi_phase_results)
    ? (resultObject.multi_phase_results as Record<string, unknown>[])
    : [];
  const multiPhase = bsEntries ?? multiPhaseFallback;
  if (multiPhase.length > 0 && waveformType === "tongtiao") {
    multiPhase.forEach((phase, index) => {
      const label = typeof phase.label === "string" ? phase.label : `${t("第")}${index + 1}${t("相")}`;
      const withstand = readNum(phase.counterstrike_withstand_ka);
      const tripRate = readNum(phase.trip_rate);
      const phSearch = phase.search_history as Record<string, unknown>[] | undefined;
      const scanItems: BinarySearchStepItem[] = Array.isArray(phSearch)
        ? phSearch.map((row) => ({
            iteration: readNum(row.iteration) ?? 0,
            current_ka: readNum(row.current_ka),
            flashover_count: readNum(row.flashover_count),
            low: readNum(row.low),
            high: readNum(row.high),
          }))
        : [];
      steps.push({
        key: `multi-${phase.phase_count ?? index}`,
        header: `${label}${t("反击二分")}`,
        summaryRows: [
          { label: t("耐雷水平(kA)"), value: fmt(withstand) },
          {
            label: t("跳闸率"),
            value: tripRate === null ? "-" : tripRate.toFixed(6),
          },
          { label: t("扫描次数"), value: String(scanItems.length) },
        ],
        scanItems,
      });
    });
  }

  // 绕击二分
  const shieldingSearch = resultObject.shielding_binary_search as Record<string, unknown> | undefined;
  if (shieldingSearch) {
    binarySearchSteps(t("绕击二分"), shieldingSearch, "shielding");
  }

  // 结果回填/落库
  steps.push({
    key: "finalize",
    header: t("结果回填落库"),
    summaryRows: [
      { label: t("风险等级"), value: typeof resultObject.risk_level === "string" ? resultObject.risk_level : "-" },
      { label: t("是否收敛"), value: Boolean(binarySearch?.converged) ? t("是") : "-" },
    ],
    scanItems: [],
  });
  return steps;
}

export const buildBinaryScanColumns = (t: (s: string) => string): ColumnsType<BinarySearchStepItem> => [
  { title: t("迭代"), dataIndex: "iteration", width: 60 },
  { title: t("电流(kA)"), dataIndex: "current_ka", width: 100, render: (v: number | null) => v ?? "-" },
  { title: t("闪络相数"), dataIndex: "flashover_count", width: 90, render: (v: number | null) => v ?? "-" },
  { title: t("下限"), dataIndex: "low", width: 100, render: (v: number | null) => v ?? "-" },
  { title: t("上限"), dataIndex: "high", width: 100, render: (v: number | null) => v ?? "-" },
];

/** 二分搜索扫描历史表格（计算过程可展开步骤内使用） */
export function BinaryScanTable({ items, t }: { items: BinarySearchStepItem[]; t: (s: string) => string }) {
  if (items.length === 0) return null;
  return (
    <Table<BinarySearchStepItem>
      rowKey={(row) => `${row.iteration}`}
      columns={buildBinaryScanColumns(t)}
      dataSource={items}
      pagination={false}
      size="small"
      scroll={{ x: 500 }}
    />
  );
}

/** 计算过程可展开步骤 */
export function ComputationSteps({ steps, t }: { steps: ComputationStepItem[]; t: (s: string) => string }) {
  if (steps.length === 0) return null;
  return (
    <div>
      <Typography.Title level={5}>{t("计算过程")}</Typography.Title>
      <Collapse
        size="small"
        items={steps.map((step) => ({
          key: step.key,
          label: step.header,
          children: (
            <Space direction="vertical" size={12} className="w-full">
              <Descriptions size="small" column={3}>
                {step.summaryRows.map((row) => (
                  <Descriptions.Item key={row.label} label={row.label}>
                    {row.value}
                  </Descriptions.Item>
                ))}
              </Descriptions>
              <BinaryScanTable items={step.scanItems} t={t} />
            </Space>
          ),
        }))}
      />
    </div>
  );
}

/** 原因细项表格区块（计算 / 改造共用） */
export function ReasonDetailsTable({ reasonDetails, t }: { reasonDetails: ReasonDetail[]; t: (s: string) => string }) {
  return (
    <div>
      <Typography.Title level={5}>{t("原因细项")}</Typography.Title>
      {reasonDetails.length === 0 ? (
        <Empty description={t("暂无细项分级")} />
      ) : (
        <Table<ReasonDetail>
          rowKey="code"
          columns={buildReasonDetailColumns(t)}
          dataSource={reasonDetails}
          pagination={false}
          size="small"
        />
      )}
    </div>
  );
}

/** 综合结论 / 原因分析 文本块（计算 / 改造共用） */
export function ConclusionText({
  summaryText,
  causeAnalysis,
  lang,
  t,
}: {
  summaryText?: string | null;
  causeAnalysis?: string | null;
  lang: AppLang;
  t: (s: string) => string;
}) {
  return (
    <div>
      <Typography.Title level={5}>{t("综合结论")}</Typography.Title>
      <div className="fl-detail-conclusion">{summaryText || "-"}</div>
      <Typography.Title level={5} style={{ marginTop: 16 }}>{t("原因分析")}</Typography.Title>
      <div className="fl-detail-conclusion">{translateAnalysisText(causeAnalysis ?? "-", lang)}</div>
    </div>
  );
}

/** 结果可信性提示 */
export function ResultWarnings({ warnings, lang, t }: { warnings: string[]; lang: AppLang; t: (s: string) => string }) {
  if (warnings.length === 0) return null;
  return (
    <Alert
      type="warning"
      showIcon
      message={t("结果可信性提示")}
      description={
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {warnings.map((item) => (
            <li key={item}>{translateAnalysisText(item, lang)}</li>
          ))}
        </ul>
      }
    />
  );
}

/** 任务头（任务名 / 类型 / 状态 + 查看日志按钮）—— 计算与改造塔级详情共用 */
export function ResultBasicInfoShell({
  selectedJob,
  canReadLogs,
  onOpenLog,
  t,
}: {
  selectedJob: FlAnalysisJobSummary | null;
  canReadLogs?: boolean;
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
  t: (s: string) => string;
}) {
  return (
    <Space className="flex w-full" style={{ justifyContent: "space-between" }} align="center">
      <Typography.Text type="secondary" style={{ marginBottom: 0 }}>
        {t("任务：")}{selectedJob?.job_name || selectedJob?.line_name || selectedJob?.line_code || "-"
          }（{selectedJob ? formatJobType(selectedJob.job_type, mitigationMode(selectedJob), t) : "-"}）
      </Typography.Text>
      {canReadLogs && onOpenLog ? (
        <Button
          size="small"
          disabled={!selectedJob?.task_id}
          onClick={() => onOpenLog(
            selectedJob?.task_id,
            t("任务执行日志"),
            selectedJob?.job_name || selectedJob?.line_name || selectedJob?.line_code || t("防雷任务"),
          )}
        >
          {t("查看日志")}
        </Button>
      ) : null}
    </Space>
  );
}

/** 任务信息区块：通用字段（任务名/状态/线路/类型/结果杆塔数/完成时间）+ 各类型附加字段 + 风险计数 */
export function JobInfoDescriptions({
  jobDetail,
  extraItems,
  riskCountsContent,
}: {
  jobDetail: FlAnalysisJobDetail;
  extraItems?: ReactNode;
  riskCountsContent: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <section className="fl-create-form-block">
      <div className="fl-create-form-block-title">{t("任务信息")}</div>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label={t("任务名称")}>{jobDetail.job_name || "-"}</Descriptions.Item>
        <Descriptions.Item label={t("任务状态")}>
          <Tag color={statusColor(jobDetail.status)}>{JOB_STATUS_TEXT[jobDetail.status] ? t(JOB_STATUS_TEXT[jobDetail.status]) : jobDetail.status}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={t("线路")}>{jobDetail.line_name || jobDetail.line_code || "-"}</Descriptions.Item>
        <Descriptions.Item label={t("任务类型")}>{formatJobType(jobDetail.job_type, mitigationMode(jobDetail), t)}</Descriptions.Item>
        <Descriptions.Item label={t("结果杆塔数")}>{jobDetail.result_tower_count}</Descriptions.Item>
        <Descriptions.Item label={t("完成时间")}>{formatFinishedAt(jobDetail.finished_at)}</Descriptions.Item>
        {extraItems}
        <Descriptions.Item label={t("风险计数")} span={2}>{riskCountsContent}</Descriptions.Item>
      </Descriptions>
    </section>
  );
}

/** 计算方法区块（普通 / 同跳 / 复算共用） */
export function CalculationMethodSection({
  executionOptions,
  externalModelName,
  externalModelCode,
  externalModelVersion,
  t,
}: {
  executionOptions: Record<string, unknown>;
  externalModelName?: string | null;
  externalModelCode?: string | null;
  externalModelVersion?: string | null;
  t: (s: string) => string;
}) {
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
  const showMethod = (v: unknown) => (typeof v === "string" && v ? (METHOD_TEXT[v] ? t(METHOD_TEXT[v]) : v) : "-");
  return (
    <section className="fl-create-form-block">
      <div className="fl-create-form-block-title">{t("计算方法")}</div>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label={t("反击耐雷水平计算方法")}>{showMethod(executionOptions.fanji_naleishuiping_method)}</Descriptions.Item>
        <Descriptions.Item label={t("绕击耐雷水平计算方法")}>{showMethod(executionOptions.raoji_naleishuiping_method)}</Descriptions.Item>
        <Descriptions.Item label={t("反击跳闸率计算方法")}>{showMethod(executionOptions.fanji_tzl_method)}</Descriptions.Item>
        <Descriptions.Item label={t("绕击跳闸率计算方法")}>{showMethod(executionOptions.raoji_tzl_method)}</Descriptions.Item>
        <Descriptions.Item label={t("ATP模型")}>{formatAtpModel(externalModelName || externalModelCode, t, externalModelVersion)}</Descriptions.Item>
      </Descriptions>
    </section>
  );
}

/** 高级参数区块（普通 / 同跳 / 复算共用） */
export function AdvancedParamsSection({
  workflow,
  t,
}: {
  workflow: { current_waveform?: string; flashover_method?: string; altitude_correction?: string; induced_voltage_formula?: string; head_time_range_us?: { min?: number | null; max?: number | null; step?: number | null }; tail_time_range_us?: { min?: number | null; max?: number | null; step?: number | null } } | undefined;
  t: (s: string) => string;
}) {
  return (
    <section className="fl-create-form-block">
      <div className="fl-create-form-block-title">{t("高级参数")}</div>
      <Descriptions bordered size="small" column={2}>
        <Descriptions.Item label={t("雷电流波形")}>{formatCurrentWaveform(workflow?.current_waveform, t)}</Descriptions.Item>
        <Descriptions.Item label={t("绝缘子闪络判据")}>{formatFlashoverMethod(workflow?.flashover_method, t)}</Descriptions.Item>
        <Descriptions.Item label={t("是否海拔修正")}>{formatAltitudeCorrection(workflow?.altitude_correction, t)}</Descriptions.Item>
        <Descriptions.Item label={t("感应电压公式")}>{formatInducedVoltageFormula(workflow?.induced_voltage_formula, t)}</Descriptions.Item>
        <Descriptions.Item label={t("波头范围")}>{formatRangeSummary(workflow?.head_time_range_us, t)}</Descriptions.Item>
        <Descriptions.Item label={t("波尾范围")}>{formatRangeSummary(workflow?.tail_time_range_us, t)}</Descriptions.Item>
      </Descriptions>
    </section>
  );
}

/** 任务级操作按钮栏（生成措施推荐 / 加装避雷器复算 / 生成报告 / 下载报告）—— 各 job 级面板共用 */
export function JobActionsBar({
  selectedJob,
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
}: {
  selectedJob: FlAnalysisJobSummary;
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
}) {
  const { t } = useI18n();
  if (!(canManage || selectedJob.job_type === "report")) {
    return null;
  }
  return (
    <Space size={12} wrap split={<Divider type="vertical" />}>
      {canManage && (canCreateMitigation || canCreateScenario || canCreateReport) ? (
        <Space wrap>
          {canCreateMitigation ? (
            <Button
              type="primary"
              disabled={candidateMitigationRows.length === 0}
              onClick={onOpenMitigation}
            >
              {t("生成措施推荐")}
            </Button>
          ) : null}
          {canCreateScenario ? (
            <Button
              disabled={candidateScenarioRows.length === 0}
              onClick={onOpenScenario}
            >
              {t("加装避雷器复算")}
            </Button>
          ) : null}
          {canCreateReport ? (
            <Button
              disabled={candidateReportRows.length === 0}
              onClick={onOpenReport}
            >
              {t("生成报告")}
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
            {t("下载报告")}
          </Button>
        ) : null}
      </Space>
    </Space>
  );
}

/** 风险计数：high/medium/low → 高/中/低风险 + 座数 */
export function formatRiskCounts(counts: unknown, t: (s: string) => string) {
  if (!counts || typeof counts !== "object") return "-";
  const map: Array<[string, string]> = [["high", t("高风险")], ["medium", t("中风险")], ["low", t("低风险")]];
  const record = counts as Record<string, unknown>;
  const parts = map
    .filter(([key]) => record[key] !== undefined && record[key] !== null)
    .map(([key, label]) => `${label} ${Number(record[key]) || 0} ${t("座")}`);
  const extra = Object.entries(record)
    .filter(([key]) => !map.some(([k]) => k === key))
    .map(([key, value]) => `${key} ${value}`);
  const all = [...parts, ...extra];
  return all.length ? all.join("；") : t("无");
}
