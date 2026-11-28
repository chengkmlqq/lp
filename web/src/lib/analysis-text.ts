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

// LP-149：整句兜底译文（整句命中优先，避免局部替换产生「中英夹生」）
const CONDUCTOR_POS_EN =
  "Conductor left/right position info missing; approximated with symmetric coordinates";
const WAVE_RECHECK_EN =
  "It is recommended to further recheck insulation coordination and grounding parameters based on the worst head/tail time point";

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
  "导线左右位置信息缺失，当前按对称坐标近似": CONDUCTOR_POS_EN,
  // LP-149：历史/导入数据里已被旧逻辑局部翻译过的夹生句，整句命中优先
  "导线左右位置信息缺失, 当前Scanned per 对称坐标近似": CONDUCTOR_POS_EN,
  "按Heidler waveform, intersection method criterion: 2.60/50.00 μs":
    "Scan per Heidler waveform and intersection method criterion: 2.60/50.00 μs",
  "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数": WAVE_RECHECK_EN,
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
// 中文模板：按{波形}波形、{判据}口径扫描 {a}/{b} μs
const RE_WAVE_SCAN = /按(.+?)波形、(.+?)口径扫描\s*([\d.]+)\/([\d.]+)\s*μs/;
// LP-149：已被旧逻辑局部翻译过的夹生句 按{wave} waveform, {method} criterion: {a}/{b} μs
const RE_WAVE_SCAN_MIXED = /按\s*(.+?)\s*waveform\s*,\s*(.+?)\s*criterion\s*:\s*([\d.]+)\s*\/\s*([\d.]+)\s*μs/;
// LP-149：中文逗号/半角逗号 + 当前按/当前Scanned per 两种历史写法
const RE_CONDUCTOR_POS = /导线左右位置信息缺失\s*[，,]\s*当前\s*(?:按|Scanned\s+per)?\s*对称坐标近似/;
const HAS_ZH = /[\u4e00-\u9fff]/;

const WAVEFORM_EN: Record<string, string> = {
  Heidler: "Heidler",
  双斜角: "double slope",
  双指数: "double exponential",
};
const METHOD_EN: Record<string, string> = {
  规程法: "guideline method",
  相交法: "intersection method",
  先导发展法: "leader development method",
};
const RISK_EN: Record<string, string> = { 高: "high", 中: "medium", 低: "low" };
const CALC_EN: Record<string, string> = { 同跳: "same-strike", 普通: "normal" };
const TRIP_RATE_EN: Record<string, string> = {
  反击跳闸率: "Back-flashover trip rate",
  绕击跳闸率: "Shielding trip rate",
};
const SUMMARY_STATIC_EN: Record<string, string> = {
  含历史结果回退: "includes historical-result fallback",
  当前杆塔: "current tower",
  多相: "multi-phase",
};

function waveScanText(m: RegExpExecArray): string {
  return `Scan per ${WAVEFORM_EN[m[1]] ?? m[1]} waveform and ${METHOD_EN[m[2]] ?? m[2]} criterion: ${m[3]}/${m[4]} μs`;
}

/** 兜底：逐片段替换已知中文残字，未知片段仍原样回落（不留中文残字）。 */
function translateFragments(segment: string): string {
  let out = segment.replace(/^按\s*/, "Scan per ");
  out = out.replace(/waveform,/g, "waveform and");
  out = out.replace(/导线左右位置信息缺失/g, "Conductor left/right position info missing");
  out = out.replace(/[，,]\s*当前\s*(?:按|Scanned\s+per)?\s*对称坐标近似/g, "; approximated with symmetric coordinates");
  out = out.replace(/建议结合波头\/波尾最不利点继续复核绝缘配合与接地参数/g, WAVE_RECHECK_EN);
  return out;
}

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
  const wave = RE_WAVE_SCAN.exec(segment) ?? RE_WAVE_SCAN_MIXED.exec(segment);
  if (wave) {
    return waveScanText(wave);
  }
  if (RE_CONDUCTOR_POS.test(segment)) {
    return CONDUCTOR_POS_EN;
  }
  if (segment === "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数") {
    return WAVE_RECHECK_EN;
  }
  if (HAS_ZH.test(segment)) {
    return translateFragments(segment);
  }
  return SUMMARY_STATIC_EN[segment] ?? null;
}

/** 摘要文本（「，」拼接）里的动态短语：整段替换后再拆段。 */
function translateSummaryPatterns(text: string): string {
  let out = text.replace(RE_WAVE_SCAN, (_all, wave, method, a, b) =>
    `Scan per ${WAVEFORM_EN[wave] ?? wave} waveform and ${METHOD_EN[method] ?? method} criterion: ${a}/${b} μs`
  );
  out = out.replace(RE_WAVE_SCAN_MIXED, (_all, wave, method, a, b) =>
    `Scan per ${WAVEFORM_EN[wave] ?? wave} waveform and ${METHOD_EN[method] ?? method} criterion: ${a}/${b} μs`
  );
  out = out.replace(/最不利点\s*([\d.]+)\/([\d.]+)\s*μs/g, (_all, a, b) => `Worst point ${a}/${b} μs`);
  out = out.replace(/规程法等级\s*(\d+)/g, (_all, n) => `Regulation grade ${n}`);
  out = out.replace(/(反击跳闸率|绕击跳闸率)\s*([\d.]+)/g, (_all, label, value) => `${TRIP_RATE_EN[label] ?? label} ${value}`);
  out = out.replace(/(.+?)评估为(.+?)风险/g, (_all, tower, risk) => `${tower} assessed as ${RISK_EN[risk] ?? risk} risk`);
  out = out.replace(/(高|中|低)风险/g, (_all, risk) => `${RISK_EN[risk] ?? risk} risk`);
  out = out.replace(/(.+?)(同跳|普通)计算/g, (_all, tower, calc) => `${tower} ${CALC_EN[calc] ?? calc} calculation`);
  out = out.replace(/(.+?)\s+(\S+)\s+跳闸率\s+([\d.]+)/g, (_all, label, phase, value) => `${label} ${phase} trip rate ${value}`);
  for (const [zh, en] of Object.entries(SUMMARY_STATIC_EN)) {
    out = out.split(zh).join(en);
  }
  return out;
}

/** 按“；”拆分分析文本逐段翻译；zh 原样返回；英文界面用半角分号拼接。 */
export function translateAnalysisText(text: string | null | undefined, lang: AppLang): string {
  if (!text || lang !== "en") {
    return text ?? "";
  }
  const translated = translateSummaryPatterns(text);
  const parts = translated
    .split(/[；;]/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return text;
  }
  return parts
    .map((part) => {
      // 整句命中优先：先查完整句词典，再做动态/片段兜底，避免局部替换夹生
      if (ANALYSIS_TEXT_EN[part] !== undefined) {
        return ANALYSIS_TEXT_EN[part];
      }
      const dynamic = translateDynamic(part);
      if (dynamic) {
        return dynamic;
      }
      return EN_DICT[part] ?? part;
    })
    .join("; ")
    .replace(/，/g, ", ");
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
