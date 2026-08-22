"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Space,
  Typography,
  Spin,
  Dropdown,
  Table,
  message,
  Steps,
  Collapse,
  Tag,
  Tree,
} from "antd";
import {
  DownloadOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  PictureOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { readApiError } from "@/lib/api";
import type { FaultAnalysisDetail } from "@/types/auth";

const { Title, Text, Paragraph } = Typography;

interface AnalysisDetailViewProps {
  analysisId: string;
  /** 唯一标识，用作导出容器 DOM id 前缀（多开详情 Tab 时避免重复 id） */
  tabKey: string;
}

interface ReportSectionItem {
  type: "text" | "subtitle" | "bullet" | "highlight" | "card" | "table";
  text: string;
  items?: string[];
  title?: string;
  layout?: "grid" | "key_value";
  columns?: string[];
  rows?: string[][];
}

interface ReportSection {
  title: string;
  content: ReportSectionItem[];
}

/** Build report sections from a FaultAnalysisDetail returned by the API. */
function buildSections(detail: FaultAnalysisDetail): { sections: ReportSection[]; station: string; fault_datetime: string; fault_id: string } {
  // If the backend already stored structured sections, use them.
  const storedSections = (detail.result_json?.sections as ReportSection[] | undefined);
  if (storedSections && storedSections.length > 0) {
    return {
      sections: storedSections,
      station: detail.station ?? "",
      fault_datetime: detail.fault_time ?? "",
      fault_id: `FA-${detail.id?.slice(0, 12) ?? ""}`,
    };
  }

  // Otherwise build a lightweight report from the available scalar fields.
  const sections: ReportSection[] = [];
  const station = detail.station ?? "";
  const faultDatetime = detail.fault_time ?? "";
  const faultId = `FA-${detail.id?.slice(0, 12) ?? ""}`;

  // Section 1: fault basics
  const basics: ReportSectionItem[] = [];
  if (station || faultDatetime) {
    basics.push({
      type: "text",
      text: `故障录波记录厂站: ${station}，故障时刻: ${faultDatetime}`,
    });
  }
  if (detail.fault_type) {
    basics.push({ type: "text", text: `故障类型: ${detail.fault_type}` });
  }
  if (detail.fault_phase) {
    basics.push({ type: "text", text: `故障相: ${detail.fault_phase}` });
  }
  if (detail.fault_duration_ms != null) {
    basics.push({ type: "text", text: `故障持续时间: ${detail.fault_duration_ms} ms` });
  }
  if (detail.reclosure_status) {
    basics.push({ type: "text", text: `重合闸情况: ${detail.reclosure_status}` });
  }
  if (basics.length > 0) {
    sections.push({ title: "一、故障基本信息", content: basics });
  }

  // Section 2: electrical parameters
  const electrical: ReportSectionItem[] = [];
  if (detail.fault_voltage_v != null) {
    electrical.push({ type: "text", text: `故障相电压: ${detail.fault_voltage_v} V` });
  }
  if (detail.fault_current_a != null) {
    electrical.push({ type: "text", text: `故障相电流: ${detail.fault_current_a} A` });
  }
  if (detail.max_zero_current_a != null) {
    electrical.push({ type: "text", text: `最大零序电流: ${detail.max_zero_current_a} A` });
  }
  if (detail.zero_compensation != null) {
    electrical.push({ type: "text", text: `零序补偿系数K: ${detail.zero_compensation}` });
  }
  if (detail.fault_resistance_ohm != null) {
    electrical.push({ type: "text", text: `故障电阻: ${detail.fault_resistance_ohm} Ω` });
  }
  if (detail.line_length_km != null) {
    electrical.push({ type: "text", text: `线路总长度: ${detail.line_length_km} km` });
  }
  if (electrical.length > 0) {
    sections.push({ title: "二、电气参数", content: electrical });
  }

  // Section 3: lightning & location
  const location: ReportSectionItem[] = [];
  if (detail.lightning_current_ka != null) {
    location.push({ type: "text", text: `雷电流幅值: ${detail.lightning_current_ka} kA` });
  }
  if (detail.lightning_longitude != null && detail.lightning_latitude != null) {
    location.push({ type: "text", text: `雷电定位: 经度 ${detail.lightning_longitude}°, 纬度 ${detail.lightning_latitude}°` });
  }
  if (detail.wave_distance_km != null) {
    location.push({ type: "text", text: `录波测距: ${detail.wave_distance_km} km` });
  }
  if (detail.traveling_wave_distance_km != null) {
    location.push({ type: "text", text: `行波测距: ${detail.traveling_wave_distance_km} km` });
  }
  if (detail.optical_position) {
    location.push({ type: "text", text: `光学接闪位置: ${detail.optical_position}` });
  }
  if (detail.optical_device_location) {
    location.push({ type: "text", text: `光学设备安装位置: ${detail.optical_device_location}` });
  }
  if (location.length > 0) {
    sections.push({ title: "三、雷电定位与测距", content: location });
  }

  // Section 4: conclusion
  const conclusion: ReportSectionItem[] = [];
  if (detail.confidence != null) {
    conclusion.push({
      type: "text",
      text: `综合置信度: ${detail.confidence}%`,
    });
  }
  if (detail.risk_level) {
    const riskMap: Record<string, string> = { high: "高风险", medium: "中风险", low: "低风险" };
    conclusion.push({ type: "text", text: `风险等级: ${riskMap[detail.risk_level] ?? detail.risk_level}` });
  }
  conclusion.push({
    type: "card",
    text: detail.confidence != null && detail.confidence >= 90
      ? "综合判定: 高置信度，可直接采纳分析结论。"
      : detail.confidence != null && detail.confidence >= 70
        ? `综合判定: 置信度 S=${detail.confidence}%，建议人工复核后再做决策。`
        : "综合判定: 置信度较低，建议结合现场情况综合分析。",
  });
  if (conclusion.length > 0) {
    sections.push({ title: "四、综合判定", content: conclusion });
  }

  return { sections, station, fault_datetime: faultDatetime, fault_id: faultId };
}

interface ComputationStepDef {
  key: string;
  title: string;
  header: string;
  empty: string;
  fields: { label: string; get: (rj: Record<string, unknown>) => React.ReactNode }[];
}

function rjValue(obj: Record<string, unknown> | undefined, path: string): unknown {
  if (!obj) return undefined;
  let current: unknown = obj;
  for (const segment of path.split(".")) {
    if (current == null || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function rjText(obj: Record<string, unknown> | undefined, path: string, empty = "-"): string {
  const value = rjValue(obj, path);
  if (value == null || value === "") return empty;
  return String(value);
}

function formatConfidence(value: unknown): string {
  if (value == null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return `${(num * 100).toFixed(1)}%`;
}

function buildComputationSteps(): ComputationStepDef[] {
  return [
    {
      key: "ground",
      title: "接地判断",
      header: "步骤1：接地故障判断",
      empty: "该记录未包含接地故障判断中间数据。",
      fields: [
        { label: "最大零序电流", get: (rj) => rjText(rj, "ground_fault_decision.evidence", "-") },
        { label: "故障相编码", get: (rj) => rjText(rj, "inputs.fault_record.fault_phase", "-") },
        {
          label: "故障类型",
          get: (rj) => {
            const value = rjValue(rj, "ground_fault_decision.fault_kind");
            return <Tag color={value ? "green" : "default"}>{String(value ?? "-")}</Tag>;
          },
        },
        { label: "判别置信度", get: (rj) => formatConfidence(rjValue(rj, "ground_fault_decision.confidence")) },
        {
          label: "判别状态",
          get: (rj) => {
            const status = rjText(rj, "ground_fault_decision.status", "-");
            const map: Record<string, string> = { decided: "已判定", uncertain: "不确定" };
            return map[status] ?? status;
          },
        },
        {
          label: "判定依据",
          get: (rj) => {
            const evidence = rjValue(rj, "ground_fault_decision.evidence");
            if (Array.isArray(evidence) && evidence.length > 0) {
              return (
                <ul className="mb-0 pl-4" style={{ listStyle: "disc" }}>
                  {(evidence as string[]).map((item, index) => (
                    <li key={index} className="text-sm text-gray-700">{String(item)}</li>
                  ))}
                </ul>
              );
            }
            return "-";
          },
        },
      ],
    },
    {
      key: "resistance",
      title: "过渡电阻",
      header: "步骤2：过渡电阻计算",
      empty: "该记录未包含过渡电阻计算中间数据。",
      fields: [
        { label: "零序阻抗 Zm", get: (rj) => rjText(rj, "transition_resistance.zm_ohm", "-") },
        {
          label: "过渡电阻",
          get: (rj) => {
            const value = rjValue(rj, "transition_resistance.transition_resistance_ohm");
            return value == null ? "-" : `${value} Ω`;
          },
        },
        {
          label: "分级",
          get: (rj) => {
            const category = rjText(rj, "transition_resistance.category", "-");
            const colorMap: Record<string, string> = {
              "金属性接地故障": "green",
              "低阻接地": "green",
              "中阻接地": "orange",
              "高阻接地": "red",
            };
            return <Tag color={colorMap[category] ?? "default"}>{category}</Tag>;
          },
        },
        { label: "分类说明", get: (rj) => rjText(rj, "transition_resistance.category_report_text", "-") },
        { label: "计算公式", get: (rj) => rjText(rj, "transition_resistance.formula_rf", "-") },
        {
          label: "计算依据",
          get: (rj) => {
            const evidence = rjValue(rj, "transition_resistance.evidence") ?? rjValue(rj, "transition_resistance.warnings");
            if (Array.isArray(evidence) && evidence.length > 0) {
              return (
                <ul className="mb-0 pl-4" style={{ listStyle: "disc" }}>
                  {(evidence as string[]).map((item, index) => (
                    <li key={index} className="text-sm text-gray-700">{String(item)}</li>
                  ))}
                </ul>
              );
            }
            return "-";
          },
        },
      ],
    },
    {
      key: "location",
      title: "定位融合",
      header: "步骤3：综合定位融合",
      empty: "该记录未包含综合定位中间数据。",
      fields: [
        { label: "融合结果", get: (rj) => rjText(rj, "fault_location.result_text", "-") },
        {
          label: "状态",
          get: (rj) => {
            const status = rjText(rj, "fault_location.status", "-");
            const map: Record<string, string> = { located: "已定位", needs_review: "需复核", unavailable: "无法定位" };
            return map[status] ?? status;
          },
        },
        { label: "融合置信度", get: (rj) => formatConfidence(rjValue(rj, "fault_location.confidence")) },
        {
          label: "数据源",
          get: (rj) => {
            const sources = rjValue(rj, "fault_location.sources");
            if (Array.isArray(sources) && sources.length > 0) {
              return (sources as Record<string, unknown>[]).map((source, index) => (
                <span key={index} className="mr-2 text-sm text-gray-700">
                  {String(source.label ?? "-")}: {String(source.tower ?? "-")}
                </span>
              ));
            }
            return "-";
          },
        },
        {
          label: "融合逻辑",
          get: (rj) => {
            const evidence = rjValue(rj, "fault_location.evidence");
            if (Array.isArray(evidence) && evidence.length > 0) {
              return (
                <ul className="mb-0 pl-4" style={{ listStyle: "disc" }}>
                  {(evidence as string[]).map((item, index) => (
                    <li key={index} className="text-sm text-gray-700">{String(item)}</li>
                  ))}
                </ul>
              );
            }
            return "-";
          },
        },
      ],
    },
    {
      key: "ledger",
      title: "台账匹配",
      header: "步骤4：线路台账匹配",
      empty: "该记录未包含台账匹配中间数据。",
      fields: [
        {
          label: "匹配结果",
          get: (rj) => {
            const matched = rjValue(rj, "inputs.line_ledger.matched");
            return matched == null ? "-" : (matched ? <Tag color="green">已匹配</Tag> : <Tag color="red">未匹配</Tag>);
          },
        },
        { label: "匹配线路", get: (rj) => rjText(rj, "inputs.line_ledger.requested_line_name", "-") },
        { label: "查询杆塔", get: (rj) => rjText(rj, "inputs.line_ledger.query_tower", "-") },
        { label: "匹配杆塔", get: (rj) => rjText(rj, "inputs.line_ledger.record.tower_no", "-") },
        { label: "耐雷水平（反击）", get: (rj) => rjText(rj, "inputs.line_ledger.record.backflashover_withstand_ka", "-") },
        { label: "耐雷水平（绕击）", get: (rj) => rjText(rj, "inputs.line_ledger.record.shielding_failure_withstand_ka", "-") },
        {
          label: "匹配说明",
          get: (rj) => rjText(rj, "inputs.line_ledger.diagnostic", rjText(rj, "inputs.line_ledger.reason", "-")),
        },
      ],
    },
    {
      key: "lightning",
      title: "雷击分析",
      header: "步骤5：雷击原因分析",
      empty: "该记录未包含雷击分析中间数据。",
      fields: [
        {
          label: "雷电流幅值",
          get: (rj) => {
            const value = rjValue(rj, "lightning_cause_analysis.lightning_current_ka") ?? rjValue(rj, "inputs.lightning.current_ka");
            return value == null ? "-" : `${value} kA`;
          },
        },
        { label: "结论", get: (rj) => rjText(rj, "lightning_cause_analysis.conclusion", "-") },
        { label: "机理", get: (rj) => rjText(rj, "lightning_cause_analysis.mechanism", "-") },
        {
          label: "状态",
          get: (rj) => {
            const status = rjText(rj, "lightning_cause_analysis.status", "-");
            const map: Record<string, string> = { not_applicable: "不适用", unavailable: "不可用" };
            return map[status] ?? status;
          },
        },
      ],
    },
    {
      key: "wave",
      title: "行波分析",
      header: "步骤6：行波分析",
      empty: "该记录未包含行波分析中间数据。",
      fields: [
        {
          label: "引擎类型",
          get: (rj) => {
            const method = rjText(rj, "traveling_wave_analysis.analysis_method", "-");
            return method.includes("MATLAB") ? <Tag color="blue">MATLAB</Tag> : method;
          },
        },
        {
          label: "行波记录数",
          get: (rj) => {
            const phases = rjValue(rj, "traveling_wave_analysis.phase_analyses");
            if (Array.isArray(phases)) return String(phases.length);
            return rjText(rj, "traveling_wave_analysis.active_phases", "-");
          },
        },
        { label: "分类结论", get: (rj) => rjText(rj, "traveling_wave_analysis.classification", "-") },
        { label: "机理", get: (rj) => rjText(rj, "traveling_wave_analysis.mechanism", "-") },
        { label: "置信度", get: (rj) => formatConfidence(rjValue(rj, "traveling_wave_analysis.confidence")) },
        { label: "模型预测结果", get: (rj) => rjText(rj, "traveling_wave_analysis.model_result.meaning", "-") },
        { label: "详细判定依据", get: (rj) => rjText(rj, "traveling_wave_analysis.report_conclusion", "-") },
      ],
    },
    {
      key: "overall",
      title: "综合判定",
      header: "步骤7：综合判定",
      empty: "该记录未包含综合判定中间数据。",
      fields: [
        { label: "判定结论", get: (rj) => rjText(rj, "overall_recommendation.decision", "-") },
        {
          label: "是否可自动通过",
          get: (rj) => {
            const canPass = rjValue(rj, "overall_recommendation.can_auto_pass");
            return canPass == null ? "-" : (canPass ? <Tag color="green">可以自动通过</Tag> : <Tag color="orange">建议人工复核</Tag>);
          },
        },
        {
          label: "综合置信度",
          get: (rj) => {
            const value = rjValue(rj, "confidence") ?? rjValue(rj, "overall_recommendation.confidence");
            return value == null ? "-" : `${value}%`;
          },
        },
        {
          label: "风险等级",
          get: (rj) => {
            const level = rjText(rj, "risk_level", "-");
            const map: Record<string, string> = { low: "低风险", medium: "中风险", high: "高风险", critical: "极高风险" };
            return map[level] ?? level;
          },
        },
        { label: "汇总说明", get: (rj) => rjText(rj, "overall_recommendation.summary", "-") },
        {
          label: "未通过原因",
          get: (rj) => {
            const reasons = rjValue(rj, "overall_recommendation.reasons");
            if (Array.isArray(reasons) && reasons.length > 0) {
              return (
                <ul className="mb-0 pl-4" style={{ listStyle: "disc" }}>
                  {(reasons as string[]).map((item, index) => (
                    <li key={index} className="text-sm text-gray-700">{String(item)}</li>
                  ))}
                </ul>
              );
            }
            return "-";
          },
        },
      ],
    },
  ];
}

const FAULT_ANALYSIS_KEY_PREFIX = "fault-analysis/";

function artifactIcon(key: string): React.ReactNode {
  const name = key.toLowerCase();
  if (name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".bmp")) {
    return <PictureOutlined style={{ color: "#1677ff" }} />;
  }
  if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".csv")) {
    return <FileExcelOutlined style={{ color: "#389e0d" }} />;
  }
  if (name.endsWith(".txt") || name.endsWith(".json") || name.endsWith(".log")) {
    return <FileTextOutlined style={{ color: "#8c8c8c" }} />;
  }
  return <FileTextOutlined />;
}

interface ArtifactTreeNode {
  title: React.ReactNode;
  key: string;
  isLeaf?: boolean;
  children?: ArtifactTreeNode[];
}

function buildArtifactTree(
  artifacts: Record<string, unknown> | undefined,
  onDownload: (key: string) => void,
): ArtifactTreeNode[] {
  const root: ArtifactTreeNode = { title: "产物", key: "__root__", children: [] };
  const nodes = new Map<string, ArtifactTreeNode>();
  nodes.set("__root__", root);
  const insert = (parts: string[], fullKey: string) => {
    let parent = root;
    let prefix = "";
    for (let i = 0; i < parts.length; i++) {
      prefix = prefix ? `${prefix}/${parts[i]}` : parts[i];
      const isFile = i === parts.length - 1;
      if (!nodes.has(prefix)) {
        const node: ArtifactTreeNode = {
          title: isFile ? (
            <span className="inline-flex items-center gap-2">
              {artifactIcon(parts[i])}
              {parts[i]}
              <Button size="small" icon={<DownloadOutlined />} onClick={(e) => { e.stopPropagation(); onDownload(fullKey); }}>
                下载
              </Button>
            </span>
          ) : (
            parts[i]
          ),
          key: prefix,
          ...(isFile ? { isLeaf: true } : { children: [] }),
        };
        nodes.set(prefix, node);
        parent.children!.push(node);
      }
      parent = nodes.get(prefix)!;
    }
  };
  if (artifacts) {
    for (const [category, value] of Object.entries(artifacts)) {
      const keys = Array.isArray(value) ? value : [value];
      for (const item of keys) {
        if (item == null || typeof item !== "string" || !item.trim()) continue;
        const clean = item.startsWith(FAULT_ANALYSIS_KEY_PREFIX) ? item : `${FAULT_ANALYSIS_KEY_PREFIX}${item}`;
        insert(clean.split("/"), item);
      }
    }
  }
  return root.children ?? [];
}

async function downloadObject(fetchWithAuth: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>, analysisId: string, objectKey: string) {
  const encodedKey = objectKey.split("/").map(encodeURIComponent).join("/");
  const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/artifacts/${encodedKey}`);
  if (!response.ok) {
    const errMsg = await readApiError(response).catch(() => "下载失败");
    throw new Error(errMsg);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  let filename = "";
  if (encodedMatch) {
    filename = decodeURIComponent(encodedMatch[1]);
  } else {
    const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
    filename = plainMatch ? plainMatch[1] : objectKey.split("/").pop() ?? "artifact";
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function AnalysisDetailView({ analysisId, tabKey }: AnalysisDetailViewProps) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const [exporting, setExporting] = useState(false);
  const [downloadingArtifact, setDownloadingArtifact] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"report" | "process" | "artifacts">("report");
  const exportElementId = `analysis-export-content-${tabKey}`;

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  const detailQuery = useQuery({
    queryKey: ["/api/v1/fault-analysis", analysisId],
    enabled: !!user && canRead && !!analysisId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisDetail;
    },
    // 判别为异步任务（pending/processing 时），轮询详情直至完成/失败（LP-316）。
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });

  const handleExportMatlab = async () => {
    if (!detail) return;

    setExporting(true);
    try {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/export-matlab`);
      if (!response.ok) {
        const errMsg = await readApiError(response).catch(() => "请求失败");
        throw new Error(errMsg);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") ?? "";
      let filename = "";
      const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      if (encodedMatch) {
        filename = decodeURIComponent(encodedMatch[1]);
      } else {
        const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
        filename = plainMatch ? plainMatch[1] : `fault_analysis_${analysisId}_matlab_outputs.zip`;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success("MATLAB 引擎产物导出成功");
    } catch (error) {
      console.error("导出失败", error);
      message.error(error instanceof Error ? error.message : "导出失败，请重试");
    } finally {
      setExporting(false);
    }
  };

  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spin size="large" />
      </div>
    );
  }

  if (detailQuery.error) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载失败"
        description={
          detailQuery.error instanceof Error
            ? detailQuery.error.message
            : "未知错误"
        }
      />
    );
  }

  const detail = detailQuery.data;

  if (!detail) {
    return <Alert type="info" showIcon message="未找到该故障分析记录" />;
  }

  const { sections, station, fault_datetime, fault_id } = buildSections(detail);

  const resultJson = (detail.result_json ?? {}) as Record<string, unknown>;
  const artifacts = resultJson.artifacts as Record<string, unknown> | undefined;
  const computationSteps = buildComputationSteps();
  const artifactTree = buildArtifactTree(artifacts, (key) => handleDownloadArtifact(key));
  const stepCount = computationSteps.length;

  const handleDownloadArtifact = async (objectKey: string) => {
    if (!detail) return;
    setDownloadingArtifact(objectKey);
    try {
      await downloadObject(fetchWithAuth, analysisId, objectKey);
      message.success("产物下载成功");
    } catch (error) {
      console.error("下载产物失败", error);
      message.error(error instanceof Error ? error.message : "下载失败，请重试");
    } finally {
      setDownloadingArtifact(null);
    }
  };

  const renderProcessContent = () => (
    <div className="py-4">
      <Steps
        current={stepCount - 1}
        status="finish"
        size="small"
        className="mb-6"
        items={computationSteps.map((step) => ({ title: step.title }))}
      />
      <Collapse
        accordion
        defaultActiveKey={["ground"]}
        items={computationSteps.map((step) => ({
          key: step.key,
          label: step.header,
          children: (
            <Space direction="vertical" size={12} className="w-full">
              <Descriptions column={2} bordered size="small">
                {step.fields.map((field, index) => (
                  <Descriptions.Item key={`${step.key}-${index}`} label={field.label} span={2}>
                    {field.get(resultJson)}
                  </Descriptions.Item>
                ))}
              </Descriptions>
              {resultJson.input_warnings && (resultJson.input_warnings as unknown[]).length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  message="输入警告"
                  description={(resultJson.input_warnings as string[]).join("；")}
                />
              ) : null}
            </Space>
          ),
        }))}
      />
    </div>
  );

  const renderArtifactsContent = () => (
    <div className="py-4">
      {artifactTree.length === 0 ? (
        <Alert type="info" showIcon message="该记录暂无产物清单。" />
      ) : (
        <Tree
          showLine
          defaultExpandAll
          treeData={artifactTree}
        />
      )}
    </div>
  );

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card className="flex-1 overflow-auto">
        <div className="flex gap-2 mb-4">
          <Button type={activeView === "report" ? "primary" : "default"} onClick={() => setActiveView("report")}>
            查看报告
          </Button>
          <Button type={activeView === "process" ? "primary" : "default"} onClick={() => setActiveView("process")}>
            计算过程
          </Button>
          <Button type={activeView === "artifacts" ? "primary" : "default"} onClick={() => setActiveView("artifacts")}>
            查看产物
          </Button>
        </div>
        {activeView === "report" && (
                <div id={exportElementId}>
                  <div className="border-b border-gray-200 pb-5 mb-6">
                    <div className="flex items-start justify-between mb-5">
                      <Title level={3} className="mb-0">
                        {fault_id} 故障分析报告
              </Title>
              <Dropdown
                menu={{
                  items: [
                    {
                      key: "matlab",
                      label: "导出引擎产物 (ZIP)",
                      onClick: handleExportMatlab,
                    },
                  ],
                }}
                placement="bottomRight"
                trigger={["click"]}
              >
                <Button
                  icon={<DownloadOutlined />}
                  loading={exporting}
                >
                  导出报告
                </Button>
              </Dropdown>
            </div>
            <Text type="secondary" className="text-sm">
              线路: {detail.line_name ?? "-"} | 录波记录厂站: {station} | 故障时间:{" "}
              {fault_datetime}
            </Text>
          </div>

          <Space direction="vertical" size={24} className="w-full">
            {sections.map((section, sectionIndex) => {
              const descriptionsItems = section.content.filter(
                (item) => item.type !== "table" && item.type !== "card"
              );
              const standaloneItems = section.content.filter(
                (item) => item.type === "table" || item.type === "card"
              );
              return (
                <div key={sectionIndex}>
                  <div
                    className="px-5 py-3 rounded-md mb-4"
                    style={{
                      background: 'var(--fquiz-theme-bg-active)',
                      color: 'var(--fquiz-theme-text-primary)',
                      border: '1px solid var(--fquiz-theme-border)'
                    }}
                  >
                    <Text
                      className="font-semibold text-base"
                      style={{ color: 'var(--fquiz-theme-text-primary)' }}
                    >
                      {section.title}
                    </Text>
                  </div>
                  <Space direction="vertical" size={12} className="w-full">
                    {descriptionsItems.length > 0 && (
                      <Descriptions column={2} bordered size="small">
                        {descriptionsItems.map((item, itemIndex) => {
                          if (item.type === "subtitle") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                <Text strong className="text-sm">
                                  {item.text}
                                </Text>
                              </Descriptions.Item>
                            );
                          }
                          if (item.type === "highlight") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                <Text type="warning" className="text-sm">
                                  {item.text}
                                </Text>
                              </Descriptions.Item>
                            );
                          }
                          if (item.type === "bullet") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                {item.items?.map((bullet, bulletIndex) => (
                                  <Paragraph
                                    key={bulletIndex}
                                    className="text-sm mb-2 text-gray-700"
                                  >
                                    • {bullet}
                                  </Paragraph>
                                ))}
                              </Descriptions.Item>
                            );
                          }
                          return (
                            <Descriptions.Item key={itemIndex} label="">
                              <Paragraph className="text-sm text-gray-700 mb-0">
                                {item.text}
                              </Paragraph>
                            </Descriptions.Item>
                          );
                        })}
                      </Descriptions>
                    )}
                    {standaloneItems.map((item, itemIndex) => {
                      if (item.type === "card") {
                        const lines = item.text.split("\n");
                        return (
                          <div
                            key={itemIndex}
                            className="bg-gray-50 border border-gray-200 rounded-lg p-5"
                          >
                            {lines.map((line, lineIndex) => {
                              const isHighlight =
                                line.includes("建议人工复核") ||
                                line.includes("雷击类型:");
                              const isTitle =
                                line === "综合判定" ||
                                (lineIndex === 0 && !line.includes(":"));
                              return (
                                <Paragraph
                                  key={lineIndex}
                                  className={`text-sm mb-2 ${
                                    isTitle
                                      ? "font-semibold text-gray-900"
                                      : isHighlight
                                      ? "text-orange-600 font-medium"
                                      : "text-gray-700"
                                  }`}
                                >
                                  {line}
                                </Paragraph>
                              );
                            })}
                          </div>
                        );
                      }
                      if (item.type === "table") {
                        const columns = item.columns ?? [];
                        const rawRows = item.rows ?? [];
                        let tableColumns = columns.map((col, index) => ({
                          title: col,
                          dataIndex: index,
                          key: `${index}-${col}`,
                        }));
                        let tableRows: Record<string, string>[] = [];
                        if (item.layout === "key_value" && columns.length >= 2) {
                          const pairHead = columns[0];
                          const valueHead = columns[1];
                          tableColumns = [
                            { title: pairHead, dataIndex: 0, key: "kv-key" },
                            { title: valueHead, dataIndex: 1, key: "kv-value" },
                          ];
                          rawRows.forEach((row, rowIndex) => {
                            for (let index = 0; index + 1 < row.length; index += 2) {
                              tableRows.push({
                                key: `r${rowIndex}-c${index}`,
                                0: row[index] ?? "",
                                1: row[index + 1] ?? "",
                              });
                            }
                          });
                        } else {
                          rawRows.forEach((row, rowIndex) => {
                            const record: Record<string, string> = { key: `r${rowIndex}` };
                            columns.forEach((_, index) => {
                              record[index] = row[index] ?? "";
                            });
                            tableRows.push(record);
                          });
                        }
                        return (
                          <div
                            key={itemIndex}
                            className="bg-white border border-gray-200 rounded-lg"
                            style={{ padding: 12, overflowY: "auto" }}
                          >
                            {item.title ? (
                              <Text strong className="text-sm block mb-2">
                                {item.title}
                              </Text>
                            ) : null}
                            <Table
                              size="small"
                              bordered
                              pagination={false}
                              columns={tableColumns}
                              dataSource={tableRows}
                            />
                          </div>
                        );
                      }
                      return null;
                    })}
                  </Space>
                </div>
              );
            })}
          </Space>
        </div>
        )}
        {activeView === "process" && renderProcessContent()}
        {activeView === "artifacts" && renderArtifactsContent()}
        </Card>
    </div>
  );
}