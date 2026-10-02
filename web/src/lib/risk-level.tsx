import { Tag } from "antd";

type RiskLevelDisplay = {
  label: string;
  color: string;
};

/**
 * 杆塔风险等级 → 中文标签 + Tag 颜色。
 * 兼容历史数据多种形态：数字(1-4)、全角罗马(Ⅰ-Ⅳ)、英文(high/medium/low)、单字中文(高/中/低)。
 * 颜色口径与防雷计算详情（fl-analysis riskColor）一致：低=绿、中=橙、高=红；
 * 数据中另存在第四档 4/Ⅳ（对应防雷报告规则表的"严重"），用 magenta 深化以示区分。
 */
const RISK_LEVEL_DISPLAYS: Record<string, RiskLevelDisplay> = {
  low: { label: "低风险", color: "green" },
  medium: { label: "中风险", color: "orange" },
  high: { label: "高风险", color: "red" },
  severe: { label: "严重", color: "magenta" },
};

/** 历史取值（trim + toLowerCase 后）→ 标准化 key，与 RISK_LEVEL_DISPLAYS 对齐。 */
const RISK_VALUE_TO_KEY: Record<string, string> = {
  // 低风险：1 / Ⅰ / low / 低 / 较低 / 低风险
  "1": "low",
  i: "low",
  "Ⅰ": "low",
  "ⅰ": "low",
  low: "low",
  低: "low",
  较低: "low",
  低风险: "low",
  // 中风险：2 / Ⅱ / medium / 中 / 一般 / 中风险
  "2": "medium",
  ii: "medium",
  "Ⅱ": "medium",
  "ⅱ": "medium",
  medium: "medium",
  中: "medium",
  一般: "medium",
  中风险: "medium",
  // 高风险：3 / Ⅲ / high / 高 / 较高 / 高风险
  "3": "high",
  iii: "high",
  "Ⅲ": "high",
  "ⅲ": "high",
  high: "high",
  高: "high",
  较高: "high",
  高风险: "high",
  // 严重：4 / Ⅳ / 严重 / 极高 / 极高风险
  "4": "severe",
  iv: "severe",
  "Ⅳ": "severe",
  "ⅳ": "severe",
  严重: "severe",
  极高: "severe",
  极高风险: "severe",
};

function toRiskKey(value: string | null | undefined): string | null {
  if (value == null) return null;
  const text = value.trim().toLowerCase();
  if (!text || text === "/") return null;
  return RISK_VALUE_TO_KEY[text] ?? null;
}

/** 风险等级 → 中文标签（未识别返回 "-"）。 */
export function formatRiskLevel(value: string | null | undefined): string {
  const key = toRiskKey(value);
  if (!key) return "-";
  return RISK_LEVEL_DISPLAYS[key].label;
}

/** 风险等级 → antd Tag 颜色（未识别返回 "default"）。 */
export function riskColor(value: string | null | undefined): string {
  const key = toRiskKey(value);
  if (!key) return "default";
  return RISK_LEVEL_DISPLAYS[key].color;
}

/** 风险等级中文 Tag；空值/未识别显示 "-"。 */
export function RiskLevelTag({ value }: { value: string | null | undefined }) {
  const key = toRiskKey(value);
  if (!key) return "-";
  return <Tag color={RISK_LEVEL_DISPLAYS[key].color}>{RISK_LEVEL_DISPLAYS[key].label}</Tag>;
}
