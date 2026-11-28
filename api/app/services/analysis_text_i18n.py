"""线路/杆塔分析建议文本与枚举值的 中→英 翻译层。

用于英文界面（lang=en）下让塔详情「Analysis suggestions」章节的值、
以及杆塔 CSV 导出的表头/枚举值/分析文本不再出现中文。

数据来源说明：
- 原因分析 / 措施推荐 文本由规则引擎（fl_analysis_rules.py）以中文模板
  生成后存入 tower_analysis，且历史数据、CSV 导入数据、用户手填数据均可能
  为中文自由文本。前端无法逐字段重算，因此这里维护一份「中文模板 → 英文」
  的映射 + 少量动态正则，在展示/导出时按语言翻译；未命中片段原样回落。
- 枚举值（直线/耐张、绕击/反击、是/否、风险等级、地形等）同样按语言翻译。

本模块为纯函数，供 CSV 导出（line_service）使用；前端（web/src/lib/analysis-text.ts）
维护等价逻辑用于塔详情展示，两侧独立、互不耦合。
"""

from __future__ import annotations

import re
from typing import Any

# LP-149：整句兜底译文（整句命中优先，避免局部替换产生「中英夹生」）
_CONDUCTOR_POS_EN = (
    "Conductor left/right position info missing; approximated with symmetric coordinates"
)
_WAVE_RECHECK_EN = (
    "It is recommended to further recheck insulation coordination and grounding "
    "parameters based on the worst head/tail time point"
)

# ───────────────────────── 固定短语（原因分析 / 措施推荐） ─────────────────────────

ANALYSIS_TEXT_EN: dict[str, str] = {
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
    "导线左右位置信息缺失，当前按对称坐标近似": _CONDUCTOR_POS_EN,
    # LP-149：历史/导入数据里已被旧逻辑局部翻译过的夹生句，整句命中优先
    "导线左右位置信息缺失, 当前Scanned per 对称坐标近似": _CONDUCTOR_POS_EN,
    "按Heidler waveform, intersection method criterion: 2.60/50.00 μs":
        "Scan per Heidler waveform and intersection method criterion: 2.60/50.00 μs",
    "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数": _WAVE_RECHECK_EN,
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
}

# 动态片段前缀:中文 → 英文（尾部动态参数由 _translate_dynamic 处理）
ANALYSIS_TEXT_PREFIX_EN: dict[str, str] = {
    "规程法雷击风险等级为": "Regulation-based lightning risk grade:",
    "补齐以下输入可提升结果可信度:": "Complete the following inputs to improve result confidence:",
}

# 回退输入字段名（fallback_missing 元素）:中文 → 英文
FALLBACK_FIELD_EN: dict[str, str] = {
    "反击耐雷水平": "back-flashover withstand level",
    "反击跳闸率": "back-flashover trip rate",
    "绕击耐雷水平": "shielding withstand level",
    "绕击跳闸率": "shielding trip rate",
}

# ───────────────────────── 枚举值 ─────────────────────────

ENUM_VALUE_EN: dict[str, str] = {
    # 直线/耐张
    "直线": "Tangent",
    "耐张": "Strain",
    "直线/耐张": "Tangent / Strain",
    "直线耐张": "Tangent / Strain",
    "直线-耐张": "Tangent / Strain",
    "直线塔": "Tangent tower",
    "耐张塔": "Strain tower",
    "直线或耐张": "Tangent or strain",
    "直线或耐张杆塔": "Tangent or strain tower",
    # 绕击/反击模式
    "绕击": "Shielding Failure",
    "反击": "Back Flashover",
    "绕击/反击": "Shielding / back-flashover",
    "绕击反击": "Shielding / back-flashover",
    "反击绕击": "Back-flashover / shielding",
    # 是/否（避雷器安装）
    "是": "Yes",
    "否": "No",
    "有": "Yes",
    "无": "No",
    "未装": "No",
    "已装": "Yes",
    "安装": "Yes",
    "未安装": "No",
    # 风险等级
    "低风险": "Low risk",
    "中风险": "Medium risk",
    "高风险": "High risk",
    "严重": "Severe",
    "低": "Low",
    "中": "Medium",
    "高": "High",
    # 地形
    "平原": "Plain",
    "山地": "Mountain",
    "山区": "Mountainous area",
    "丘陵": "Hilly",
    "丘陵地带": "Hilly area",
    "水域": "Water area",
    "平原地区": "Plain area",
}

# ───────────────────────── 动态正则（含参数的中文模板） ─────────────────────────

_RE_REGULATORY_GRADE = re.compile(r"规程法雷击风险等级为\s*(\S+?)\s*级")
_RE_COMPLETE_INPUTS = re.compile(r"补齐以下输入可提升结果可信度:\s*(.+)")
# 中文模板：按{波形}波形、{判据}口径扫描 {a}/{b} μs
_RE_WAVE_SCAN = re.compile(r"按(.+?)波形、(.+?)口径扫描\s*([\d.]+)/([\d.]+)\s*μs")
# LP-149：已被旧逻辑局部翻译过的夹生句 按{wave} waveform, {method} criterion: {a}/{b} μs
_RE_WAVE_SCAN_MIXED = re.compile(
    r"按\s*(.+?)\s*waveform\s*,\s*(.+?)\s*criterion\s*:\s*([\d.]+)\s*/\s*([\d.]+)\s*μs"
)
# LP-149：中文逗号/半角逗号 + 当前按/当前Scanned per 两种历史写法
_RE_CONDUCTOR_POS = re.compile(
    r"导线左右位置信息缺失\s*[，,]\s*当前\s*(?:按|Scanned\s+per)?\s*对称坐标近似"
)
_JOIN_SPLIT = re.compile(r"[；;]")

# 摘要文本（以「，」拼接）中的动态片段
_WAVEFORM_EN = {"Heidler": "Heidler", "双斜角": "double slope", "双指数": "double exponential"}
_METHOD_EN = {
    "规程法": "guideline method",
    "相交法": "intersection method",
    "先导发展法": "leader development method",
}
_RISK_EN = {"高": "high", "中": "medium", "低": "low"}
_CALC_EN = {"同跳": "same-strike", "普通": "normal"}
_TRIP_RATE_EN = {"反击跳闸率": "Back-flashover trip rate", "绕击跳闸率": "Shielding trip rate"}
_SUMMARY_STATIC_EN = {
    "含历史结果回退": "includes historical-result fallback",
    "当前杆塔": "current tower",
    "多相": "multi-phase",
}


def _wave_scan_en(wave: str, method: str, a: str, b: str) -> str:
    """波形扫描句统一译文；method 已是英文术语时原样复用。"""
    return (
        f"Scan per {_WAVEFORM_EN.get(wave, wave)} waveform and "
        f"{_METHOD_EN.get(method, method)} criterion: {a}/{b} μs"
    )


def _translate_fragments(segment: str) -> str:
    """兜底：逐片段替换已知中文残字，未知片段仍原样回落（不留中文残字）。"""
    out = re.sub(r"^按\s*", "Scan per ", segment)
    out = out.replace("waveform,", "waveform and")
    out = out.replace("导线左右位置信息缺失", "Conductor left/right position info missing")
    out = re.sub(
        r"[，,]\s*当前\s*(?:按|Scanned\s+per)?\s*对称坐标近似",
        "; approximated with symmetric coordinates",
        out,
    )
    out = out.replace("建议结合波头/波尾最不利点继续复核绝缘配合与接地参数", _WAVE_RECHECK_EN)
    return out


def _translate_dynamic(segment: str) -> str | None:
    """对含参数的中文片段做正则翻译；无法识别返回 None。"""
    stripped = segment.strip()
    m = _RE_REGULATORY_GRADE.match(stripped)
    if m:
        return f"Regulation-based lightning risk grade: {m.group(1)}"
    m = _RE_COMPLETE_INPUTS.match(stripped)
    if m:
        fields = re.split(r"[、,，]", m.group(1))
        translated = [FALLBACK_FIELD_EN.get(f.strip(), f.strip()) for f in fields if f.strip()]
        return "Complete the following inputs to improve result confidence: " + ", ".join(translated)
    for pattern in (_RE_WAVE_SCAN, _RE_WAVE_SCAN_MIXED):
        m = pattern.match(stripped)
        if m:
            return _wave_scan_en(m.group(1), m.group(2), m.group(3), m.group(4))
    if _RE_CONDUCTOR_POS.match(stripped):
        return _CONDUCTOR_POS_EN
    if stripped == "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数":
        return _WAVE_RECHECK_EN
    if re.search(r"[\u4e00-\u9fff]", stripped):
        return _translate_fragments(stripped)
    return _SUMMARY_STATIC_EN.get(stripped)


def _translate_summary_patterns(text: str) -> str:
    """摘要文本里夹在「，」之间的动态短语：先整段替换，再按「，」转半角。"""
    def _wave(m: re.Match[str]) -> str:
        return _wave_scan_en(m.group(1), m.group(2), m.group(3), m.group(4))

    def _eval(m: re.Match[str]) -> str:
        return f"{m.group(1)} assessed as {_RISK_EN.get(m.group(2), m.group(2))} risk"

    def _calc(m: re.Match[str]) -> str:
        return f"{m.group(1)} {_CALC_EN.get(m.group(2), m.group(2))} calculation"

    def _dominant(m: re.Match[str]) -> str:
        return f"{m.group(1)} {m.group(2)} trip rate {m.group(3)}"

    text = _RE_WAVE_SCAN.sub(_wave, text)
    text = _RE_WAVE_SCAN_MIXED.sub(
        lambda m: _wave_scan_en(m.group(1), m.group(2), m.group(3), m.group(4)), text
    )
    text = re.sub(r"最不利点\s*([\d.]+)/([\d.]+)\s*μs",
                  lambda m: f"Worst point {m.group(1)}/{m.group(2)} μs", text)
    text = re.sub(r"规程法等级\s*(\d+)",
                  lambda m: f"Regulation grade {m.group(1)}", text)
    text = re.sub(r"(反击跳闸率|绕击跳闸率)\s*([\d.]+)",
                  lambda m: f"{_TRIP_RATE_EN[m.group(1)]} {m.group(2)}", text)
    text = re.sub(r"(.+?)评估为(.+?)风险", _eval, text)
    text = re.sub(r"(高|中|低)风险", lambda m: f"{_RISK_EN[m.group(1)]} risk", text)
    text = re.sub(r"(.+?)(同跳|普通)计算", _calc, text)
    text = re.sub(r"(.+?)\s+(\S+)\s+跳闸率\s+([\d.]+)", _dominant, text)
    for zh, en in _SUMMARY_STATIC_EN.items():
        text = text.replace(zh, en)
    return text


def translate_analysis_text(text: str | None, lang: str) -> str:
    """英文界面下逐段翻译；'；' 拼接的原因/措施用 '; '，'，，' 拼接的摘要用 ', '。"""
    if not text:
        return text or ""
    if lang != "en":
        return text
    translated = _translate_summary_patterns(text)
    parts = [p for p in _JOIN_SPLIT.split(translated) if p.strip()]
    if not parts:
        return text
    out: list[str] = []
    for part in parts:
        stripped = part.strip()
        # 整句命中优先：先查完整句词典，再做动态/片段兜底，避免局部替换夹生
        exact = ANALYSIS_TEXT_EN.get(stripped)
        if exact is not None:
            out.append(exact)
            continue
        dynamic = _translate_dynamic(stripped)
        out.append(dynamic if dynamic is not None else ANALYSIS_TEXT_EN.get(stripped, stripped))
    return "; ".join(out).replace("，", ", ")


def translate_enum_value(value: str | None, lang: str) -> str:
    """枚举值（直线/耐张、绕击/反击、是/否、风险等级、地形）按语言翻译。"""
    if not value:
        return value or ""
    if lang != "en":
        return value
    stripped = value.strip()
    if not stripped:
        return value
    return ENUM_VALUE_EN.get(stripped, value)


def translate_csv_cell(value: Any, lang: str) -> str:
    """CSV 单元格翻译：枚举值走 ENUM_VALUE_EN，其余原样。"""
    if value is None:
        return ""
    text = str(value)
    if lang != "en":
        return text
    return ENUM_VALUE_EN.get(text.strip(), text)


# ───────────────────────── CSV 英文表头（69 列，与中文表头严格对齐） ─────────────────────────

LINE_TOWER_CSV_HEADERS_EN: tuple[str, ...] = (
    "Line code",
    "Seq No.",
    "Line name",
    "Voltage level (kV)",
    "Tower No.",
    "Tower model",
    "Tower type",
    "Longitude",
    "Latitude",
    "Circuit I phase sequence",
    "Circuit II phase sequence",
    "Circuit III phase sequence",
    "Circuit IV phase sequence",
    "Arrester on phase A",
    "Arrester on phase B",
    "Arrester on phase C",
    "Ground resistance (ohm)",
    "Left shield-wire mid distance (m)",
    "Right shield-wire mid distance (m)",
    "Shield-wire height (m)",
    "Insulator string length (mm)",
    "Tower call height (m)",
    "Circuit I upper phase spacing (m)",
    "Circuit I middle phase spacing (m)",
    "Circuit I lower phase spacing (m)",
    "Circuit I upper phase height (m)",
    "Circuit I middle phase height (m)",
    "Circuit I lower phase height (m)",
    "Circuit II upper phase spacing (m)",
    "Circuit II middle phase spacing (m)",
    "Circuit II lower phase spacing (m)",
    "Circuit II upper phase height (m)",
    "Circuit II middle phase height (m)",
    "Circuit II lower phase height (m)",
    "Circuit III upper phase spacing (m)",
    "Circuit III middle phase spacing (m)",
    "Circuit III lower phase spacing (m)",
    "Circuit III upper phase height (m)",
    "Circuit III middle phase height (m)",
    "Circuit III lower phase height (m)",
    "Circuit IV upper phase spacing (m)",
    "Circuit IV middle phase spacing (m)",
    "Circuit IV lower phase spacing (m)",
    "Circuit IV upper phase height (m)",
    "Circuit IV middle phase height (m)",
    "Circuit IV lower phase height (m)",
    "Span on small side (m)",
    "Span on large side (m)",
    "Electrical angle (deg)",
    "Lightning current amplitude a (kA)",
    "Lightning current amplitude b (kA)",
    "Ground slope 1",
    "Ground slope 2",
    "Altitude (m)",
    "Terrain",
    "Lightning density",
    "Tangent or strain tower",
    "Shielding / back-flashover mode",
    "Back-flashover withstand level (kA)",
    "Back-flashover trip rate (per 100km.a)",
    "Shielding withstand level (kA)",
    "Shielding trip rate (per 100km.a)",
    "Lightning risk level",
    "Cause analysis",
    "Mitigation recommendation",
    "Wave speed (m/s)",
    "Main material surge impedance (ohm)",
    "Cross material surge impedance (ohm)",
    "Diagonal material surge impedance (ohm)",
)
