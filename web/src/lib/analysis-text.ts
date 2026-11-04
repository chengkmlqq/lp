/**
 * 线路/杆塔「分析建议」文本与枚举值 中→英 翻译（前端展示层）。
 *
 * 与后端 app/services/analysis_text_i18n.py 等价（两侧独立、互不耦合）：
 * - 原因分析 / 措施推荐 文本由规则引擎以中文模板生成后入库，历史/导入数据亦为中文，
 *   无法逐字段重算，因此此处维护「中文模板 → 英文」映射 + 少量动态正则，
 *   在英文界面（lang=en）下按“；”拆段逐段翻译；未命中片段原样回落（保留中文）。
 * - 枚举值（直线/耐张、绕击/反击、是/否、风险等级、地形）由 i18n EN_DICT / 本表翻译。
 *
 * 用法：<Descriptions.Item label={t("措施推荐")}>
 *         {translateAnalysisText(tower.analysis?.mitigation_recommendation ?? "", lang)}
 *       </Descriptions.Item>
 */
import { EN_DICT, type AppLang } from "./i18n";

/** 固定短语：中文模板 → 英文（与规则引擎 fl_analysis_rules.py 生成文本对齐）。 */
const ANALYSIS_TEXT_EN: Record<string, string> = {
  "按高雷区口径校核绝缘与屏蔽配置":
    "Check insulation and shielding configuration per high-lightning-zone standard",
  "保护角暴露偏大": "Protection angle exposure is excessive",
  "保护角裕度一般": "Protection angle margin is moderate",
  "避雷器配置不足": "Insufficient arrester configuration",
  "补充关键相避雷器并复核安装位置":
    "Add arresters to critical phases and verify installation position",
  "部分规程法输入缺失，已回退到已保存的历史结果":
    "Some regulatory-method inputs are missing; fell back to saved historical results",
  "大号侧档距过大": "Large-side span is excessive",
  "当前输入下未见显著高风险因素":
    "No significant high-risk factor under current inputs",
  "当前以反击风险为主": "Back-flashover risk dominates",
  "档距偏大": "Span is relatively large",
  "导线左右位置信息缺失，当前按对称坐标近似":
    "Left/right conductor position info missing; approximated with symmetric coordinates",
  "地面倾角较大": "Ground slope is large",
  "地面倾角偏大": "Ground slope is relatively large",
  "地闪密度较高": "Lightning density is high",
  "地闪密度位于高雷区": "Lightning density is in the high-lightning zone",
  "地闪密度中等偏高": "Lightning density is moderately high",
  "反击跳闸率明显高于绕击跳闸率":
    "Back-flashover trip rate significantly exceeds shielding trip rate",
  "复核大跨距杆塔绝缘配合与防雷保护":
    "Recheck insulation coordination and lightning protection for large-span towers",
  "复核塔型高度与屏蔽布置": "Recheck tower height and shielding arrangement",
  "杆塔高度暴露偏高": "Tower height exposure is high",
  "关注地形暴露影响并加强接地与巡检":
    "Pay attention to terrain exposure; strengthen grounding and inspection",
  "建议按高雷区口径复核绝缘与屏蔽配置":
    "Recheck insulation and shielding configuration per high-lightning-zone standard",
  "建议复核绝缘配合和塔头布置":
    "Recheck insulation coordination and tower-head arrangement",
  "建议将该塔纳入优先治理清单并安排复测":
    "Add this tower to the priority treatment list and arrange re-testing",
  "建议优先实施接地降阻治理":
    "Prioritize grounding-resistance reduction treatment",
  "接地电阻偏高": "Grounding resistance is high",
  "接地电阻偏高趋势明显": "Grounding resistance shows a clear upward trend",
  "接地电阻有偏高趋势": "Grounding resistance shows an upward trend",
  "绝缘配置裕度一般": "Insulation margin is moderate",
  "绝缘子串长度偏短": "Insulator string length is short",
  "耐张杆塔参数更敏感": "Strain tower parameters are more sensitive",
  "全相装设避雷器的场景建议再用 ATP 方法复核":
    "Full-phase arrester scenario: verify with the ATP method",
  "绕击跳闸率占主导": "Shielding trip rate dominates",
  "提高绝缘子串长度并校核绝缘配置":
    "Increase insulator string length and check insulation configuration",
  "维持现有防雷配置并保持常规巡检":
    "Maintain the current lightning protection configuration and regular inspection",
  "优化避雷线与保护角配置":
    "Optimize shield-wire and protection-angle configuration",
  "优先关注反击耐雷水平与接地改造":
    "Prioritize back-flashover withstand level and grounding improvement",
  "优先降低接地电阻并复核杆塔耦合与接地通道":
    "Prioritize grounding-resistance reduction; recheck tower coupling and grounding path",
  "优先降低接地电阻，复核接地网与冲击接地通道":
    "Prioritize grounding-resistance reduction; recheck grounding grid and impulse grounding path",
  "优先优化避雷线保护角与导线屏蔽关系":
    "Prioritize shield-wire protection angle and conductor shielding relationship",
  "主要输入参数处于低风险区间":
    "Main input parameters are in the low-risk range",
};

/** 回退输入字段名（fallback_missing 元素）：中文 → 英文。 */
const FALLBACK_FIELD_EN: Record<string, string> = {
  反击耐雷水平: "back-flashover withstand level",
  反击跳闸率: "back-flashover trip rate",
  绕击耐雷水平: "shielding withstand level",
  绕击跳闸率: "shielding trip rate",
};

const RE_REGULATORY_GRADE = /规程法雷击风险等级为\s*(\S+?)\s*级/;
const RE_COMPLETE_INPUTS = /补齐以下输入可提升结果可信度:\s*(.+)/;

function translateDynamic(segment: string): string | null {
  const grade = RE_REGULATORY_GRADE.exec(segment);
  if (grade) {
    return `Regulation-based lightning risk grade: ${grade[1]}`;
  }
  const inputs = RE_COMPLETE_INPUTS.exec(segment);
  if (inputs) {
    const fields = inputs[1]
      .split(/[、,，]/)
      .map((field) => field.trim())
      .filter(Boolean)
      .map((field) => FALLBACK_FIELD_EN[field] ?? field);
    return `Complete the following inputs to improve result confidence: ${fields.join(", ")}`;
  }
  return null;
}

/** 按“；”拆分分析文本逐段翻译；zh 原样返回；未命中片段保留原文。 */
export function translateAnalysisText(text: string | null | undefined, lang: AppLang): string {
  if (!text || lang !== "en") {
    return text ?? "";
  }
  const parts = text
    .split(/[；;]/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return text;
  }
  return parts
    .map((part) => {
      const dynamic = translateDynamic(part);
      if (dynamic) {
        return dynamic;
      }
      return ANALYSIS_TEXT_EN[part] ?? EN_DICT[part] ?? part;
    })
    .join("；");
}

/** 枚举值（直线/耐张、绕击/反击、是/否、风险等级、地形）按语言翻译；未识别原样。 */
export function translateEnumValue(value: string | null | undefined, lang: AppLang): string {
  if (!value || lang !== "en") {
    return value ?? "";
  }
  const stripped = value.trim();
  if (!stripped) {
    return value ?? "";
  }
  return EN_DICT[stripped] ?? value;
}
