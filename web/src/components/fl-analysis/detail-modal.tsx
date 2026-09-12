"use client";

import { Button, Collapse, Descriptions, Empty, Space, Table, Tag, Typography } from "antd";

const ATP_TOWER_TEXT: Record<string, string> = {
  guxing: "鼓型", maotou: "猫头型", ganzi: "干字型", jiubei: "酒杯型",
  menxing: "门型", shangzi: "上字型", sihuita: "四回塔", zhiliu: "直流塔",
};
const ATP_SCENE_TEXT: Record<string, string> = {
  fanji: "反击", raoji: "绕击", raoji1: "绕击1", raoji2: "绕击2", raoji3: "绕击3",
};

/** ATP 模型编码 → 中文（如 atp500-guxing-fanji-M1 → 500kV 鼓型 反击 避雷器组合 M1） */
function formatAtpModel(src?: string | null) {
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
function buildComputationSteps(
  resultObject: Record<string, unknown> | undefined,
  waveformType: string | null,
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
      header: `${prefix}（目标闪络相数 ≥ ${target ?? "?"}）`,
      summaryRows: [
        { label: "收敛", value: converged ? "是" : "否" },
        { label: "耐雷水平(kA)", value: fmt(finalWithstand) },
        { label: "扫描次数", value: String(scanItems.length) },
      ],
      scanItems,
    });
  };

  // 反击二分（normal 单相 / tongtiao 主结果）
  const binarySearch = resultObject.binary_search as Record<string, unknown> | undefined;
  if (binarySearch) {
    binarySearchSteps("反击二分", binarySearch, "counterstrike");
  }

  // 同跳各相（multi_phase_results）
  const multiPhase = Array.isArray(resultObject.multi_phase_results)
    ? (resultObject.multi_phase_results as Record<string, unknown>[])
    : [];
  if (multiPhase.length > 0 && waveformType === "tongtiao") {
    multiPhase.forEach((phase, index) => {
      const label = typeof phase.label === "string" ? phase.label : `第${index + 1}相`;
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
        header: `${label}反击二分`,
        summaryRows: [
          { label: "耐雷水平(kA)", value: fmt(withstand) },
          {
            label: "跳闸率",
            value: tripRate === null ? "-" : tripRate.toFixed(6),
          },
          { label: "扫描次数", value: String(scanItems.length) },
        ],
        scanItems,
      });
    });
  }

  // 绕击二分
  const shieldingSearch = resultObject.shielding_binary_search as Record<string, unknown> | undefined;
  if (shieldingSearch) {
    binarySearchSteps("绕击二分", shieldingSearch, "shielding");
  }

  // 结果回填/落库
  steps.push({
    key: "finalize",
    header: "结果回填落库",
    summaryRows: [
      { label: "风险等级", value: typeof resultObject.risk_level === "string" ? resultObject.risk_level : "-" },
      { label: "是否收敛", value: Boolean(binarySearch?.converged) ? "是" : "-" },
    ],
    scanItems: [],
  });
  return steps;
}

const binaryScanColumns: ColumnsType<BinarySearchStepItem> = [
  { title: "迭代", dataIndex: "iteration", width: 60 },
  { title: "电流(kA)", dataIndex: "current_ka", width: 100, render: (v: number | null) => v ?? "-" },
  { title: "闪络相数", dataIndex: "flashover_count", width: 90, render: (v: number | null) => v ?? "-" },
  { title: "下限", dataIndex: "low", width: 100, render: (v: number | null) => v ?? "-" },
  { title: "上限", dataIndex: "high", width: 100, render: (v: number | null) => v ?? "-" },
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
  // 计算过程：从已落库结果构建可展开步骤（仅普通/同跳波形任务展示）
  const computationSteps =
    selectedJobDetailWaveformType === "normal" || selectedJobDetailWaveformType === "tongtiao"
      ? buildComputationSteps(detailResultObject, selectedJobDetailWaveformType)
      : [];

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
              {formatAtpModel(readOptionalString(detailExternalExecution, "model_name") || readOptionalString(detailExternalExecution, "model_code"))}
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
        <Descriptions.Item label="综合结论" span={2}>
          {readOptionalString(detailRow, "summary_text") ?? "-"}
        </Descriptions.Item>
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

      {computationSteps.length > 0 ? (
        <div>
          <Typography.Title level={5}>
            计算过程
          </Typography.Title>
          <Collapse
            size="small"
            items={computationSteps.map((step) => ({
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
                  {step.scanItems.length > 0 ? (
                    <Table<BinarySearchStepItem>
                      rowKey={(row) => `${step.key}-${row.iteration}`}
                      columns={binaryScanColumns}
                      dataSource={step.scanItems}
                      pagination={false}
                      size="small"
                      scroll={{ x: 500 }}
                    />
                  ) : null}
                </Space>
              ),
            }))}
          />
        </div>
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
