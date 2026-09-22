"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Anchor,
  App,
  Button,
  Descriptions,
  Segmented,
  Space,
  Typography,
  Spin,
  Table,
  Collapse,
  Tag,
  Tree,
} from "antd";
import {
  DownloadOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  PictureOutlined,
  FileSearchOutlined,
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
  defaultView?: "report" | "process" | "artifacts";
  /** 打开分析执行日志抽屉（参照雷电流幅值页的日志查看） */
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
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
  key?: string;
  group?: string;
  content: ReportSectionItem[];
}

/** 详情页 Tabs 分组：将 docx 章节 sections 归并为大的选项卡。
 * 单章节 → 独立 tab（tab 名即标题）；5.1/5.2 并入「分布式行波分析与故障原因融合」，
 * A.1~A.4 并入「附表A 输入信息汇总」；空容器章节（5 / 附表A）不单独成组。
 */
interface ReportTabGroup {
  key: string;
  label: string;
  sections: ReportSection[];
}

/** 后端下发的「计算过程」声明式视图模型（build_view_model 输出）。 */
interface ProcessViewModelField {
  label: string;
  kind: "text" | "tag" | "bullets" | "kv";
  value?: string | null;
  options?: Record<string, string>;
  items?: { key?: string; value?: string }[] | string[];
}

interface ProcessViewModelStep {
  key: string;
  title: string;
  header: string;
  empty: string;
  available: boolean;
  fields: ProcessViewModelField[];
}

interface ProcessViewModel {
  steps: ProcessViewModelStep[];
}

function groupReportSections(sections: ReportSection[]): ReportTabGroup[] {
  const groups = new Map<string, ReportTabGroup>();
  const findGroup = (key: string): ReportTabGroup | undefined => groups.get(key);

  // 优先使用后端下发的 key/group；旧记录无该字段时回退到标题匹配。
  const resolve = (section: ReportSection): { key: string; label: string } => {
    if (section.group === "wave") return { key: "wave", label: "分布式行波分析与故障原因融合" };
    if (section.group === "appendix") return { key: "appendix", label: "附表A 输入信息汇总" };
    const title = section.title ?? "";
    if (section.key === "overview" || title.includes("报告总览")) return { key: "overview", label: "故障总览" };
    if (section.key === "ground" || title.includes("接地故障及过渡电阻判别")) return { key: "ground", label: "接地故障及过渡电阻判别" };
    if (section.key === "location" || title.includes("故障定位")) return { key: "location", label: "故障定位" };
    if (section.key === "lightning" || title.includes("耐雷水平与雷击原因分析")) return { key: "lightning", label: "耐雷水平与雷击原因分析" };
    if (section.key === "wave_process" || section.key === "wave_fusion" || section.key === "recommendation") {
      return { key: "wave", label: "分布式行波分析与故障原因融合" };
    }
    // 旧记录标题回退（兼容 LP-537 之前的存储）
    if (title.startsWith("5.") || title.includes("分布式行波分析") || title.includes("故障原因融合") || title.includes("总体状态与后续意见")) {
      return { key: "wave", label: "分布式行波分析与故障原因融合" };
    }
    if (title.startsWith("A.") || title.includes("附表A")) return { key: "appendix", label: "附表A 输入信息汇总" };
    return { key: title, label: title };
  };

  for (const section of sections) {
    // 空容器章节（仅标题无内容）跳过，其子章节已归入对应 tab
    if (section.content.length === 0) continue;
    const { key, label } = resolve(section);
    let group = findGroup(key);
    if (!group) {
      group = { key, label, sections: [] };
      groups.set(key, group);
    }
    group.sections.push(section);
  }
  return Array.from(groups.values());
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
    sections.push({ title: "一、故障基本信息", key: "overview", group: "overview", content: basics });
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
    sections.push({ title: "二、电气参数", key: "overview", group: "overview", content: electrical });
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
    sections.push({ title: "三、雷电定位与测距", key: "overview", group: "overview", content: location });
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
    sections.push({ title: "四、综合判定", key: "overview", group: "overview", content: conclusion });
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
  const resolve = (base: unknown): unknown => {
    let current = base;
    for (const segment of path.split(".")) {
      if (current == null || typeof current !== "object") return undefined;
      current = (current as Record<string, unknown>)[segment];
    }
    return current;
  };
  const direct = resolve(obj);
  if (direct !== undefined) return direct;
  // LP-539：判别中间数据存储于 result_json.diagnosis 子对象（build_result_json 组装），
  // 过程 tab 各步骤字段按 diagnosis 内部路径读取；兼容顶层直存的历史/直传结构：
  // 顶层取不到时自动回退到 obj.diagnosis 再按同一路径查找。
  return resolve(obj.diagnosis);
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

/** 产物树节点段中文映射（固定目录/文件翻译；动态 run_id 与任意技术文件名保留原样）。 */
const ARTIFACT_SEGMENT_LABELS: Record<string, string> = {
  "fault-analysis": "故障分析",
  Output: "输出",
  matlab: "MATLAB 计算",
  debug: "调试输入",
  "result.json": "判别结果",
  "wave_module_prediction.txt": "行波模块预测结果",
  "fault_raw.json": "录波输入数据",
  "lightning_raw.json": "雷电定位输入数据",
  "ledger_rows.json": "线路台账输入数据",
  "traveling_wave_records.json": "行波输入数据",
};

/** 节点段翻译：记录 id 段显示为分析标题；run-* 显示为「运行记录 N」；已知固定段走映射；其余保留。 */
function translateSegment(segment: string, analysisId?: string | null, analysisTitle?: string | null): string {
  if (analysisId && segment === analysisId) {
    return analysisTitle?.trim() || segment;
  }
  if (ARTIFACT_SEGMENT_LABELS[segment]) {
    return ARTIFACT_SEGMENT_LABELS[segment];
  }
  if (segment.startsWith("run-")) {
    return `运行记录 ${segment.slice(4)}`;
  }
  return segment;
}

function buildArtifactTree(
  artifacts: Record<string, unknown> | undefined,
  onDownload: (key: string) => void,
  analysisId?: string | null,
  analysisTitle?: string | null,
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
      const label = translateSegment(parts[i], analysisId, analysisTitle);
      if (!nodes.has(prefix)) {
        const node: ArtifactTreeNode = {
          title: isFile ? (
            <span className="inline-flex items-center gap-2">
              {artifactIcon(parts[i])}
              {label}
              <Button size="small" icon={<DownloadOutlined />} onClick={(e) => { e.stopPropagation(); onDownload(fullKey); }}>
                下载
              </Button>
            </span>
          ) : (
            label
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

async function downloadObject(fetchWithAuth: (path: string, init?: RequestInit) => Promise<Response>, analysisId: string, objectKey: string) {
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

interface ReportViewProps {
  tabKey: string;
  exportElementId: string;
  detail: FaultAnalysisDetail;
  sections: { sections: ReportSection[]; station: string; fault_datetime: string; fault_id: string };
  exportLoading: boolean;
  onExportReport: () => void;
  /** 打开分析执行日志抽屉（参照雷电流幅值页的日志查看） */
  onOpenLog?: (taskId: string | null | undefined, label: string, title: string) => void;
}

interface ProcessViewProps {
  tabKey: string;
  computationSteps: ComputationStepDef[];
  resultJson: Record<string, unknown>;
}

interface ArtifactsViewProps {
  tabKey: string;
  artifactTree: ArtifactTreeNode[];
  downloadingArtifact: string | null;
  onDownload: (key: string) => void;
}

/** 渲染一节 section 的 content 列表（段落/子标题/bullet/卡片/表格，与 docx 同源按序交错）。
 * 组件化排版：子标题带主题色竖条、highlight 琥珀提示条、卡片按语义分级着色、表格统一紧凑样式。
 */
function SectionContent({ content }: { content: ReportSectionItem[] }) {
  return (
    <Space direction="vertical" size={12} className="w-full">
      {content.map((item, itemIndex) => {
        if (item.type === "subtitle") {
          return (
            <div key={itemIndex} className="fa-detail-subtitle">
              {item.text}
            </div>
          );
        }
        if (item.type === "highlight") {
          return (
            <div key={itemIndex} className="fa-detail-highlight">
              {item.text}
            </div>
          );
        }
        if (item.type === "bullet") {
          return (
            <ul key={itemIndex} className="fa-detail-bullets">
              {item.items?.map((bullet, bulletIndex) => (
                <li key={bulletIndex}>{bullet}</li>
              ))}
            </ul>
          );
        }
        if (item.type === "card") {
          const lines = item.text.split("\n");
          const tone = item.text.includes("综合判定")
            ? "conclusion"
            : item.text.includes("建议人工复核")
              ? "warning"
              : "info";
          return (
            <div key={itemIndex} className={`fa-detail-card fa-detail-card--${tone}`}>
              {lines.map((line, lineIndex) => {
                const isTitle =
                  line === "综合判定" ||
                  (lineIndex === 0 && !line.includes(":"));
                return (
                  <Paragraph
                    key={lineIndex}
                    className={`fa-detail-card-line mb-1 ${isTitle ? "fa-detail-card-line--title" : ""}`}
                  >
                    {line}
                  </Paragraph>
                );
              })}
            </div>
          );
        }
        if (item.type === "table") {
          const isKvTable = item.layout === "key_value";
          if (isKvTable) {
            const rawRows = item.rows ?? [];
            const pairs: { label: string; value: string }[] = [];
            rawRows.forEach((row) => {
              for (let index = 0; index + 1 < row.length; index += 2) {
                pairs.push({
                  label: row[index] ?? "",
                  value: row[index + 1] ?? "",
                });
              }
            });
            return (
              <div key={itemIndex} className="fa-detail-table-box">
                {item.title ? (
                  <div className="fa-detail-table-title">{item.title}</div>
                ) : null}
                <Descriptions size="small" bordered column={2}>
                  {pairs.map((pair, pairIndex) => (
                    <Descriptions.Item key={pairIndex} label={pair.label}>
                      {pair.value}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </div>
            );
          }
          const columns = item.columns ?? [];
          const rawRows = item.rows ?? [];
          const tableColumns = columns.map((col, index) => ({
            title: col,
            dataIndex: index,
            key: `${index}-${col}`,
          }));
          const tableRows: Record<string, string>[] = [];
          rawRows.forEach((row, rowIndex) => {
            const record: Record<string, string> = { key: `r${rowIndex}` };
            columns.forEach((_, index) => {
              record[index] = row[index] ?? "";
            });
            tableRows.push(record);
          });
          return (
            <div key={itemIndex} className="fa-detail-table-box">
              {item.title ? (
                <div className="fa-detail-table-title">{item.title}</div>
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
        return (
          <Paragraph key={itemIndex} className="fa-detail-md-p mb-0">
            {item.text}
          </Paragraph>
        );
      })}
    </Space>
  );
}

function ReportView({ tabKey, exportElementId, detail, sections, exportLoading, onExportReport, onOpenLog }: ReportViewProps) {
  const tabGroups = groupReportSections(sections.sections);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  return (
    <div className="flex flex-1 min-h-0 py-4">
      {tabGroups.length > 1 ? (
        <div className="w-44 flex-shrink-0 overflow-auto border-r pl-4 pr-3 fa-detail-anchor">
          <Anchor
            getContainer={() => scrollRef.current ?? document.body}
            offsetTop={8}
            items={tabGroups.map((group) => ({
              key: group.key,
              href: `#fa-group-${group.key}`,
              title: group.label,
            }))}
          />
        </div>
      ) : null}
      <div
        ref={scrollRef}
        id={exportElementId}
        className="flex-1 min-h-0 overflow-auto px-6 fa-detail-report-scroll"
      >
        <div className="border-b pb-4 mb-6 fa-detail-report-header">
          <div className="flex items-start justify-between mb-4">
            <Title level={3} className="mb-0">
              {sections.fault_id} 故障分析报告
            </Title>
            <Space size={8}>
              {onOpenLog ? (
                <Button
                  icon={<FileSearchOutlined />}
                  onClick={() => onOpenLog(detail.task_id, "分析日志", detail.title ?? `FA-${detail.id?.slice(0, 12) ?? ""}`)}
                >
                  查看日志
                </Button>
              ) : null}
              <Button icon={<DownloadOutlined />} loading={exportLoading} onClick={onExportReport}>
                导出报告
              </Button>
            </Space>
          </div>
          <Space size={16} wrap className="fa-detail-meta">
            <span>
              线路：<Text strong>{detail.line_name ?? "-"}</Text>
            </span>
            <span>
              录波记录厂站：<Text>{sections.station || "-"}</Text>
            </span>
            <span>
              故障时间：<Text>{sections.fault_datetime || "-"}</Text>
            </span>
            {detail.fault_phase ? (
              <span>
                故障相：<Text strong>{detail.fault_phase}</Text>
              </span>
            ) : null}
          </Space>
        </div>

        {tabGroups.map((group) => (
          <section key={group.key} id={`fa-group-${group.key}`} className="mb-10 fa-detail-report-group">
            <div className="fa-detail-group-title">
              <span>{group.label}</span>
            </div>
            <Space direction="vertical" size={20} className="w-full">
              {group.sections.map((section, sectionIndex) => (
                <div key={sectionIndex}>
                  {group.sections.length > 1 ? (
                    <div className="fa-detail-section-title">
                      <span>{section.title}</span>
                    </div>
                  ) : null}
                  <SectionContent content={section.content} />
                </div>
              ))}
            </Space>
          </section>
        ))}
      </div>
    </div>
  );
}

function renderViewModelField(field: ProcessViewModelField): React.ReactNode {
  if (field.kind === "tag") {
    return field.value ? (
      <Tag color={field.options?.[field.value] ?? "default"}>{field.value}</Tag>
    ) : "-";
  }
  if (field.kind === "bullets") {
    const items = Array.isArray(field.items) ? field.items : [];
    return items.length > 0 ? (
      <ul className="fa-detail-bullets">
        {items.map((item, index) => (
          <li key={index}>{typeof item === "string" ? item : String(item)}</li>
        ))}
      </ul>
    ) : "-";
  }
  if (field.kind === "kv") {
    const pairs = Array.isArray(field.items) ? (field.items as { key?: string; value?: string }[]) : [];
    return pairs.length > 0 ? (
      <Descriptions column={1} size="small" className="w-full">
        {pairs.map((pair, index) => (
          <Descriptions.Item key={index} label={pair.key ?? "-"}>
            {pair.value ?? "-"}
          </Descriptions.Item>
        ))}
      </Descriptions>
    ) : "-";
  }
  return field.value ?? "-";
}

/** 字段是否占整行（bullets/kv/长文本 → 整行展示，短值 → 与下一字段并排）。 */
function isWideField(field: { kind?: string; value?: unknown }): boolean {
  if (field.kind === "bullets" || field.kind === "kv") return true;
  if (typeof field.value === "string" && field.value.length > 28) return true;
  return false;
}

function ProcessView({ computationSteps, resultJson }: ProcessViewProps) {
  const viewModel = resultJson.view_model as ProcessViewModel | undefined;
  // 优先消费后端下发的 view_model（声明式 schema，前端不再硬编码 diagnosis 路径）；
  // 旧记录无 view_model 时回退到 buildComputationSteps 兜底。
  if (viewModel && Array.isArray(viewModel.steps) && viewModel.steps.length > 0) {
    const steps = viewModel.steps;
    // 进入页面默认展开第一个步骤；可同时展开多个
    const defaultStepKey = steps[0]?.key;
    return (
      <div className="py-4 px-4">
        <Collapse
          defaultActiveKey={defaultStepKey ? [defaultStepKey] : undefined}
          items={steps.map((step, index) => {
            // 短值字段两列并排（column=2）、宽字段（bullets/kv/长文本）整行展示（column=1），
            // 拆成两个 Descriptions，避免混用 span 触发 antd「Sum of column span」告警。
            const narrowFields = step.fields.filter((field) => !isWideField(field));
            const wideFields = step.fields.filter((field) => isWideField(field));
            return {
              key: step.key,
              label: (
                <div className="fa-detail-step-header">
                  <span className="fa-detail-step-index">{index + 1}</span>
                  <span>{step.header.replace(/^步骤\d+：/, "")}</span>
                </div>
              ),
              children: (
                <Space direction="vertical" size={12} className="w-full">
                  {step.fields.length === 0 ? (
                    <Alert type="info" showIcon message={step.empty} />
                  ) : (
                    <>
                      {narrowFields.length > 0 ? (
                        <Descriptions column={2} bordered size="small">
                          {narrowFields.map((field, index) => (
                            <Descriptions.Item key={`${step.key}-n${index}`} label={field.label} span={1}>
                              {renderViewModelField(field)}
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      ) : null}
                      {wideFields.length > 0 ? (
                        <Descriptions column={1} bordered size="small">
                          {wideFields.map((field, index) => (
                            <Descriptions.Item key={`${step.key}-w${index}`} label={field.label} span={1}>
                              {renderViewModelField(field)}
                            </Descriptions.Item>
                          ))}
                        </Descriptions>
                      ) : null}
                    </>
                  )}
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
            };
          })}
        />
      </div>
    );
  }

  // 进入页面默认展开第一个步骤；可同时展开多个
  const defaultStepKey = computationSteps[0]?.key;
  return (
    <div className="py-4 px-4">
      <Collapse
        defaultActiveKey={defaultStepKey ? [defaultStepKey] : undefined}
        items={computationSteps.map((step, index) => ({
          key: step.key,
          label: (
            <div className="fa-detail-step-header">
              <span className="fa-detail-step-index">{index + 1}</span>
              <span>{step.header.replace(/^步骤\d+：/, "")}</span>
            </div>
          ),
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
}

function ArtifactsView({ onDownload, downloadingArtifact, artifactTree }: ArtifactsViewProps) {
  return (
    <div className="py-4">
      {artifactTree.length === 0 ? (
        <Alert type="info" showIcon message="该记录暂无产物清单。" />
      ) : (
        <Tree showLine defaultExpandAll treeData={artifactTree} />
      )}
    </div>
  );
}

export function AnalysisDetailView({ analysisId, tabKey, defaultView, onOpenLog }: AnalysisDetailViewProps) {
  const { message: messageApi } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const [exporting, setExporting] = useState(false);
  const [downloadingArtifact, setDownloadingArtifact] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"report" | "process" | "artifacts">(defaultView ?? "report");
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

  const handleExportReport = async () => {
    if (!detail) return;

    setExporting(true);
    try {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/report`);
      if (!response.ok) {
        const errMsg = await readApiError(response).catch(() => "请求失败");
        throw new Error(errMsg);
      }
      const blob = await response.blob();
      const taskName = detail.title?.trim() || `FA-${detail.id?.slice(0, 12) ?? ""}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${taskName}_故障分析报告.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      messageApi.success("Word报告导出成功");
    } catch (error) {
      console.error("导出报告失败", error);
      messageApi.error(error instanceof Error ? error.message : "导出失败，请重试");
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
  const viewModel = resultJson.view_model as ProcessViewModel | undefined;
  const artifactTree = buildArtifactTree(
    artifacts,
    (key) => handleDownloadArtifact(key),
    detail.id,
    detail.title,
  );

  const handleDownloadArtifact = async (objectKey: string) => {
    if (!detail) return;
    setDownloadingArtifact(objectKey);
    try {
      await downloadObject(fetchWithAuth, analysisId, objectKey);
      messageApi.success("产物下载成功");
    } catch (error) {
      console.error("下载产物失败", error);
      messageApi.error(error instanceof Error ? error.message : "下载失败，请重试");
    } finally {
      setDownloadingArtifact(null);
    }
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card
        className="flex-1 overflow-hidden"
        styles={{ body: { height: "100%", display: "flex", flexDirection: "column", minHeight: 0 } }}
      >
        <div className="flex items-center justify-between gap-3 flex-shrink-0 px-4 py-3 border-b border-gray-200">
          <Segmented
            value={activeView}
            onChange={(value) => setActiveView(value as "report" | "process" | "artifacts")}
            options={[
              { label: "报告", value: "report" },
              { label: "计算过程", value: "process" },
              { label: "产物", value: "artifacts" },
            ]}
          />
        </div>
        {activeView === "report" && (
          <ReportView
            tabKey={tabKey}
            exportElementId={exportElementId}
            detail={detail}
            sections={buildSections(detail)}
            exportLoading={exporting}
            onExportReport={handleExportReport}
            onOpenLog={onOpenLog}
          />
        )}
        {activeView === "process" && (
          <div className="flex-1 min-h-0 overflow-auto">
            <ProcessView
              tabKey={tabKey}
              computationSteps={computationSteps}
              resultJson={resultJson}
            />
          </div>
        )}
        {activeView === "artifacts" && (
          <div className="flex-1 min-h-0 overflow-auto">
            <ArtifactsView
              tabKey={tabKey}
              artifactTree={artifactTree}
              downloadingArtifact={downloadingArtifact}
              onDownload={handleDownloadArtifact}
            />
          </div>
        )}
      </Card>
    </div>
  );
}