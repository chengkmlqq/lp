from __future__ import annotations

import base64
import struct
import zlib
from collections import Counter
from datetime import datetime
from html import escape
from typing import Any, Mapping, Sequence

from .tower_topology import infer_line_kind as infer_topology_line_kind
from .tower_topology import infer_structure_count as infer_topology_structure_count


_RISK_LEVEL_LABELS = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
_RISK_GRADE_LABELS = {
    1: "I",
    2: "II",
    3: "III",
    4: "IV",
}
_AC_STANDARD_BY_VOLTAGE: dict[int, tuple[float, dict[int, float]]] = {
    35: (450.0, {1: 16.0, 2: 23.0, 4: 40.0}),
    66: (850.0, {1: 18.0, 2: 25.0, 4: 42.0}),
    110: (1314.0, {1: 20.0, 2: 28.0, 4: 44.0}),
    220: (2265.0, {1: 33.0, 2: 45.0, 4: 50.0}),
    330: (3155.0, {1: 35.0, 2: 46.0, 4: 52.0}),
    500: (4575.0, {1: 39.0, 2: 67.0, 4: 80.0}),
    750: (6745.0, {1: 55.0, 2: 124.0, 4: 130.0}),
}
_DEFAULT_AC_STANDARD = (9000.0, {1: 60.0, 2: 130.0, 4: 140.0})
_DC_STANDARD_BY_VOLTAGE: dict[int, tuple[float, float]] = {
    500: (6000.0, 50.0),
    800: (8500.0, 77.0),
}
_DEFAULT_DC_STANDARD = (9000.0, 90.0)
_AC_RISK_THRESHOLDS = {
    35: 0.8,
    66: 0.65,
    110: 0.525,
    220: 0.315,
    330: 0.2,
    500: 0.14,
    750: 0.1,
    1000: 0.1,
}
_DC_RISK_THRESHOLDS = {
    400: 0.15,
    500: 0.15,
    660: 0.1,
    800: 0.1,
}
_HEIGHT_RULES = [
    ("1级", "Hi > 1.3×S", True),
    ("2级", "1.2×S < Hi ≤ 1.3×S", True),
    ("3级", "1.1×S < Hi ≤ 1.2×S", True),
    ("4级", "S < Hi ≤ 1.1×S", False),
    ("5级", "Hi ≤ S", False),
]
_SLOPE_RULES = [
    ("1级", "θ > 15°", True),
    ("2级", "10° < θ ≤ 15°", True),
    ("3级", "5° < θ ≤ 10°", True),
    ("4级", "0° < θ ≤ 5°", False),
    ("5级", "θ ≤ 0°", False),
]
_INSULATOR_RULES = [
    ("1级", "Hi ≤ S", True),
    ("2级", "S < Hi ≤ 1.1×S", True),
    ("3级", "1.1×S < Hi ≤ 1.2×S", True),
    ("4级", "1.2×S < Hi ≤ 1.3×S", False),
    ("5级", "Hi > 1.3×S", False),
]
_PROTECTION_RULES = [
    ("1级", "α > 25°", True),
    ("2级", "20° < α ≤ 25°", True),
    ("3级", "15° < α ≤ 20°", True),
    ("4级", "10° < α ≤ 15°", False),
    ("5级", "α ≤ 10°", False),
]
_RISK_LEVEL_RULE_ROWS = [
    ["雷击风险等级", "I", "II", "III", "IV"],
    ["雷击风险程度", "较低", "一般", "较高", "严重"],
    ["杆塔雷击跳闸率", "Ri ≤ 1.0×S", "1.0×S < Ri ≤ 1.5×S", "1.5×S < Ri ≤ 3.0×S", "Ri > 3.0×S"],
    ["线路雷击跳闸率", "R ≤ 1.0×S", "1.0×S < R ≤ 1.5×S", "1.5×S < R ≤ 3.0×S", "R > 3.0×S"],
]
_LIGHTNING_ZONE_RULES = [
    {"code": "A", "zone": "少雷区", "rule": "Ng ≤ 0.78", "color_name": "灰色", "color": "#6B7280"},
    {"code": "B1", "zone": "中雷区", "rule": "0.78 < Ng ≤ 2.0", "color_name": "蓝色", "color": "#2563EB"},
    {"code": "B2", "zone": "中雷区", "rule": "2.0 < Ng ≤ 2.78", "color_name": "青色", "color": "#06B6D4"},
    {"code": "C1", "zone": "多雷区", "rule": "2.78 < Ng ≤ 5.0", "color_name": "黄色", "color": "#EAB308"},
    {"code": "C2", "zone": "多雷区", "rule": "5.0 < Ng ≤ 7.98", "color_name": "橙色", "color": "#F97316"},
    {"code": "D1", "zone": "强雷区", "rule": "7.98 < Ng ≤ 11.0", "color_name": "紫红", "color": "#C026D3"},
    {"code": "D2", "zone": "强雷区", "rule": "Ng > 11.0", "color_name": "深红", "color": "#B91C1C"},
]
_DEFAULT_BAR_COLORS = ["#0F766E", "#2563EB", "#D97706", "#9333EA", "#DC2626", "#4B5563"]


def build_report_filename(
    *,
    line_name: str | None,
    report_job_name: str | None,
    generated_at: datetime,
) -> str:
    base_name = _sanitize_filename(report_job_name or line_name or "防雷分析")
    timestamp = generated_at.strftime("%Y%m%d%H%M%S")
    return f"{base_name}-防雷报告-{timestamp}.doc"


def build_report_summary_payload(report_data: Mapping[str, Any]) -> dict[str, Any]:
    report = _read_mapping(report_data, "report")
    risk_rows = _read_rows(report_data, "risk_rows")
    selected_risk_rows = _read_rows(report_data, "selected_risk_rows")
    selected_mitigation_rows = _read_rows(report_data, "selected_mitigation_rows")
    selected_scenario_rows = _read_rows(report_data, "selected_scenario_rows")

    factor_counts: Counter[str] = Counter()
    cause_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for row in selected_risk_rows:
        result_json = _row_result(row)
        for detail in _read_sequence(result_json, "reason_details"):
            label = str(detail.get("label") or detail.get("code") or "-").strip()
            if not label:
                continue
            grade = _as_int(detail.get("grade"))
            triggered = bool(detail.get("triggered"))
            if triggered or (grade is not None and grade <= 2):
                factor_counts[label] += 1
        for item in _split_cn_list(result_json.get("cause_analysis")):
            cause_counts[item] += 1

    for row in selected_mitigation_rows:
        result_json = _row_result(row)
        for action in _read_sequence(result_json, "mitigation_actions"):
            label = str(action.get("label") or action.get("code") or "-").strip()
            if label:
                action_counts[label] += 1

    generated_at = report.get("generated_at")
    filename = build_report_filename(
        line_name=_read_mapping(report_data, "line").get("name"),
        report_job_name=_as_optional_str(report.get("job_name")),
        generated_at=generated_at if isinstance(generated_at, datetime) else datetime.utcnow(),
    )

    return {
        "report_kind": "fl-analysis",
        "generated_at": generated_at.isoformat() if isinstance(generated_at, datetime) else None,
        "document_filename": filename,
        "source_job_id": _as_optional_str(report.get("source_job_id")),
        "source_job_type": _as_optional_str(report.get("source_job_type")),
        "source_job_name": _as_optional_str(report.get("source_job_name")),
        "risk_job_id": _as_optional_str(report.get("risk_job_id")),
        "risk_job_name": _as_optional_str(report.get("risk_job_name")),
        "mitigation_job_id": _as_optional_str(report.get("mitigation_job_id")),
        "mitigation_job_name": _as_optional_str(report.get("mitigation_job_name")),
        "scenario_job_id": _as_optional_str(report.get("scenario_job_id")),
        "scenario_job_name": _as_optional_str(report.get("scenario_job_name")),
        "selected_tower_count": len(selected_risk_rows),
        "report_row_count": len(selected_mitigation_rows),
        "scenario_row_count": len(selected_scenario_rows),
        "risk_counts": _count_risk_levels(risk_rows),
        "selected_risk_counts": _count_risk_levels(selected_risk_rows),
        "post_mitigation_risk_counts": _count_risk_levels(selected_mitigation_rows),
        "post_recalc_risk_counts": _count_risk_levels(selected_scenario_rows),
        "selected_factor_trigger_counts": dict(factor_counts.most_common()),
        "selected_cause_counts": dict(cause_counts.most_common()),
        "mitigation_action_counts": dict(action_counts.most_common()),
        "has_mitigation_data": bool(selected_mitigation_rows),
        "has_scenario_data": bool(selected_scenario_rows),
        "non_construction": bool(report.get("non_construction")),
    }


def build_report_document(report_data: Mapping[str, Any]) -> tuple[str, bytes]:
    line = _read_mapping(report_data, "line")
    report = _read_mapping(report_data, "report")
    risk_rows = _read_rows(report_data, "risk_rows")
    selected_risk_rows = _read_rows(report_data, "selected_risk_rows")
    selected_mitigation_rows = _read_rows(report_data, "selected_mitigation_rows")
    selected_scenario_rows = _read_rows(report_data, "selected_scenario_rows")
    summary = build_report_summary_payload(report_data)

    generated_at = report.get("generated_at")
    if isinstance(generated_at, datetime):
        generated_at_text = generated_at.strftime("%Y-%m-%d %H:%M:%S")
    else:
        generated_at_text = "-"

    source_job_type = _format_job_type(_as_optional_str(report.get("source_job_type")))
    source_job_name = _as_optional_str(report.get("source_job_name")) or "-"
    mitigation_job_name = _as_optional_str(report.get("mitigation_job_name")) or "未关联措施任务"
    scenario_job_name = _as_optional_str(report.get("scenario_job_name")) or "未关联复算任务"
    scenario_base_job_type = _format_job_type(_as_optional_str(report.get("scenario_base_job_type")))
    if scenario_base_job_type == "-":
        scenario_base_job_type = "原计算任务"

    tower_type_entries = _build_named_distribution(
        risk_rows,
        lambda row: _row_tower_type(row) or "未标注杆塔种类",
        preferred_order=["直线", "耐张"],
    )
    terrain_entries = _build_named_distribution(
        risk_rows,
        lambda row: _row_base(row).get("terrain") or "未标注地形",
    )
    height_entries = _build_grade_distribution(risk_rows, code="shield_wire_height", rules=_HEIGHT_RULES)
    slope_entries = _build_grade_distribution(risk_rows, code="terrain_slope", rules=_SLOPE_RULES)
    insulator_entries = _build_grade_distribution(risk_rows, code="insulator_length", rules=_INSULATOR_RULES)
    lightning_entries = _build_lightning_zone_distribution(risk_rows)
    protection_entries = _build_grade_distribution(risk_rows, code="protection_angle", rules=_PROTECTION_RULES)
    risk_grade_entries = _build_risk_grade_distribution(risk_rows)

    line_voltage = _as_int(line.get("voltage_kv"))
    standard_rows = _build_standard_reference_rows(risk_rows, fallback_voltage=line_voltage)
    risk_threshold_rows = _build_risk_threshold_reference_rows(risk_rows, fallback_voltage=line_voltage)
    risk_result_rows = _build_risk_result_rows(risk_rows)
    lightning_map_rows = _build_lightning_map_rows(risk_rows)
    lightning_map_section = _render_lightning_map_section(risk_rows, lightning_map_rows)
    high_risk_reason_rows = _build_high_risk_reason_rows(selected_risk_rows)
    mitigation_table_rows = _build_mitigation_detail_rows(selected_mitigation_rows)
    scenario_table_rows = _build_scenario_table_rows(selected_scenario_rows)
    overview_stats = _build_overview_stats(risk_rows, selected_risk_rows)
    overview_text = _build_overview_text(overview_stats)
    mitigation_note = _build_mitigation_note(summary=summary, non_construction=bool(report.get("non_construction")))

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{escape(summary["document_filename"])}</title>
  <style>
    body {{
      font-family: "SimSun", "Noto Serif CJK SC", serif;
      font-size: 12pt;
      line-height: 1.65;
      color: #222;
      margin: 28px 36px;
    }}
    h1, h2, h3, h4 {{
      color: #0f2742;
      margin: 0 0 12px;
    }}
    h1 {{
      font-size: 22pt;
      text-align: center;
      margin-top: 24px;
    }}
    h2 {{
      font-size: 16pt;
      margin-top: 28px;
      border-bottom: 1px solid #c8d3df;
      padding-bottom: 4px;
    }}
    h3 {{
      font-size: 13pt;
      margin-top: 18px;
    }}
    h4 {{
      font-size: 12pt;
      margin-top: 14px;
      font-weight: 700;
    }}
    p {{
      margin: 8px 0;
      text-indent: 2em;
    }}
    .meta {{
      margin: 20px auto 0;
      width: 100%;
      border-collapse: collapse;
    }}
    .meta td {{
      border: 1px solid #cad5df;
      padding: 8px 10px;
      vertical-align: top;
    }}
    table.data {{
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0 18px;
      table-layout: fixed;
    }}
    table.data th,
    table.data td {{
      border: 1px solid #cad5df;
      padding: 8px 10px;
      vertical-align: top;
      word-break: break-word;
    }}
    table.data th {{
      background: #edf3f8;
      font-weight: 700;
    }}
    table.chart td {{
      text-align: left;
    }}
    .caption {{
      margin: 10px 0 4px;
      text-indent: 0;
      text-align: center;
      font-weight: 700;
      color: #16324f;
    }}
    .muted {{
      color: #5f6c7b;
      text-indent: 0;
    }}
    .bar-graphic {{
      width: 100%;
      border-collapse: collapse;
    }}
    .bar-graphic td {{
      padding: 0;
      border: 0;
      height: 12px;
    }}
    .bar-fill {{
      background: #0f766e;
    }}
    .bar-rest {{
      background: #e5edf5;
    }}
    .figure-card {{
      margin: 10px auto 6px;
      width: 100%;
      text-align: center;
    }}
    .report-image {{
      display: block;
      width: 100%;
      max-width: 720px;
      margin: 0 auto;
      border: 1px solid #cad5df;
      background: #fff;
    }}
    .figure-note {{
      margin: 6px 0 14px;
      text-align: center;
      text-indent: 0;
      color: #475569;
      font-size: 10.5pt;
    }}
  </style>
</head>
<body>
  <h1>{escape(_display(report.get("job_name") or line.get("name") or "防雷报告"))}</h1>
  <table class="meta">
    <tr>
      <td><strong>线路名称</strong><br />{escape(_display(line.get("name")))}</td>
      <td><strong>线路编码</strong><br />{escape(_display(line.get("code")))}</td>
      <td><strong>电压等级</strong><br />{escape(_display(line.get("voltage_kv")))} kV</td>
    </tr>
    <tr>
      <td><strong>生成时间</strong><br />{escape(generated_at_text)}</td>
      <td><strong>报告来源</strong><br />{escape(source_job_type)} / {escape(source_job_name)}</td>
      <td><strong>关联任务</strong><br />措施：{escape(mitigation_job_name)}<br />复算：{escape(scenario_job_name)}</td>
    </tr>
  </table>

  <h2>一、线路概况</h2>
  <p>{escape(overview_text)}</p>
  <p>线路整体风险分布为：高风险 {summary["risk_counts"]["high"]} 座，中风险 {summary["risk_counts"]["medium"]} 座，低风险 {summary["risk_counts"]["low"]} 座。纳入报告输出的重点杆塔中，高风险 {summary["selected_risk_counts"]["high"]} 座，中风险 {summary["selected_risk_counts"]["medium"]} 座，低风险 {summary["selected_risk_counts"]["low"]} 座。</p>

  <h2>二、线路基本信息</h2>
  <h3>2.1线路杆塔种类</h3>
  <p>{escape(_build_named_distribution_text("在线路杆塔种类上", tower_type_entries, len(risk_rows), unit="基"))}</p>
  <p class="caption">表1 线路杆塔种类统计表</p>
  {_render_table(["杆塔种类", "数量", "占比"], _distribution_rows(tower_type_entries) or [["未提取到杆塔种类", "0", "0%"]])}
  {_render_bar_chart("图1 线路杆塔种类统计图", tower_type_entries)}

  <h3>2.2线路杆塔地形</h3>
  <p>{escape(_build_named_distribution_text("在线路杆塔地形上", terrain_entries, len(risk_rows), unit="基"))}</p>
  <p class="caption">表1-1 线路杆塔地形统计表</p>
  {_render_table(["地形", "数量", "占比"], _distribution_rows(terrain_entries) or [["未提取到地形分类", "0", "0%"]])}
  {_render_bar_chart("图2 线路杆塔地形统计图", terrain_entries)}

  <h3>2.3线路杆塔高度</h3>
  <h4>2.3.1线路杆塔高度分类规则</h4>
  <p>线路杆塔高度参考值 S 由电流类型、回路数和电压等级共同确定，报告按当前线路的杆塔画像逐基匹配对应标准值。</p>
  <p class="caption">表2 当前线路杆塔高度与绝缘参考值</p>
  {_render_table(["电流类型", "回路", "电压等级(kV)", "绝缘子串参考值S(mm)", "杆塔高度参考值S(m)"], standard_rows or [["-", "-", "-", "-", "-"]])}
  <p class="caption">表3 输电线路杆塔高度影响因素等级划分规则</p>
  {_render_rule_table("杆塔高度", _HEIGHT_RULES)}
  <h4>2.3.2线路杆塔高度分类结果</h4>
  <p>{escape(_build_grade_distribution_text("在线路杆塔高度方面", height_entries, len(risk_rows), suffix="座"))}</p>
  {_render_table(["档级", "判定规则", "是否高风险", "杆塔数", "占比"], _grade_distribution_rows(height_entries))}
  {_render_bar_chart("图3 线路杆塔高度影响因素档级信息统计图", height_entries)}

  <h3>2.4线路杆塔地面倾角</h3>
  <h4>2.4.1线路杆塔地面倾角分类规则</h4>
  <p class="caption">表4 输电线路杆塔地面倾角影响因素等级划分规则</p>
  {_render_rule_table("地面倾角", _SLOPE_RULES)}
  <h4>2.4.2线路杆塔地面倾角分类结果</h4>
  <p>{escape(_build_grade_distribution_text("在线路杆塔地面倾角方面", slope_entries, len(risk_rows), suffix="座"))}</p>
  {_render_table(["档级", "判定规则", "是否高风险", "杆塔数", "占比"], _grade_distribution_rows(slope_entries))}
  {_render_bar_chart("图4 线路杆塔地面倾角信息统计图", slope_entries)}

  <h3>2.5线路杆塔绝缘子串长</h3>
  <h4>2.5.1线路杆塔绝缘子串长分类规则</h4>
  <p class="caption">表6 输电线路杆塔绝缘子串长影响因素等级划分规则</p>
  {_render_rule_table("绝缘子串长度", _INSULATOR_RULES)}
  <h4>2.5.2线路杆塔绝缘子串长分类结果</h4>
  <p>{escape(_build_grade_distribution_text("在线路杆塔绝缘子串长度方面", insulator_entries, len(risk_rows), suffix="座"))}</p>
  {_render_table(["档级", "判定规则", "是否高风险", "杆塔数", "占比"], _grade_distribution_rows(insulator_entries))}
  {_render_bar_chart("图5 线路杆塔绝缘子串长信息统计图", insulator_entries)}

  <h3>2.6线路杆塔地闪密度</h3>
  <h4>2.6.1线路杆塔地闪密度分类规则</h4>
  <p class="caption">表7 线路杆塔地闪密度雷区划分规则</p>
  {_render_table(["雷区", "等级", "地闪密度Ng(次/(km²·a))", "渲染颜色"], _lightning_zone_rule_rows())}
  <h4>2.6.2线路杆塔地闪密度分类结果</h4>
  <p>{escape(_build_lightning_distribution_text(lightning_entries, len(risk_rows)))}</p>
  {_render_table(["雷区", "等级", "范围", "杆塔数", "占比"], _lightning_distribution_rows(lightning_entries))}
  {_render_bar_chart("图6 线路杆塔雷区统计图", lightning_entries)}
  {lightning_map_section}

  <h3>2.7线路杆塔避雷线保护角</h3>
  <h4>2.7.1线路杆塔避雷线保护角分类规则</h4>
  <p class="caption">表8 输电线路杆塔避雷线保护角影响因素等级划分规则</p>
  {_render_rule_table("避雷线保护角", _PROTECTION_RULES)}
  <h4>2.7.2线路杆塔避雷线保护角分类结果</h4>
  <p>{escape(_build_grade_distribution_text("在线路杆塔避雷线保护角方面", protection_entries, len(risk_rows), suffix="座"))}</p>
  {_render_table(["档级", "判定规则", "是否高风险", "杆塔数", "占比"], _grade_distribution_rows(protection_entries))}
  {_render_bar_chart("图8 线路杆塔避雷线保护角信息统计图", protection_entries)}

  <h2>三、输电线路雷害风险评估结果</h2>
  <h3>3.1输电线路雷害风险评估规则</h3>
  <p>线路雷击风险等级按基准参考值 S 与杆塔雷击跳闸率的相对关系分级。当前报告优先展示与本线路电压等级和交直流类型匹配的参考值。</p>
  <p class="caption">表9 当前线路雷击跳闸率基准参考值</p>
  {_render_table(["电流类型", "电压等级(kV)", "基准参考值S(次/(100km·a))"], risk_threshold_rows or [["-", "-", "-"]])}
  <p class="caption">表10 输电线路雷击风险等级划分规则</p>
  {_render_table(["指标", "I", "II", "III", "IV"], _RISK_LEVEL_RULE_ROWS)}
  <h3>3.2输电线路雷害风险评估结果</h3>
  <p>{escape(_build_risk_distribution_text(risk_grade_entries, len(risk_rows)))}</p>
  {_render_bar_chart("图9 线路杆塔雷害风险等级统计图", risk_grade_entries)}
  <p class="caption">表11 雷害风险评估结果一览表</p>
  {_render_table(["杆塔号", "反击耐雷水平(kA)", "反击跳闸率", "绕击耐雷水平(kA)", "绕击跳闸率", "总雷击跳闸率", "输电线路雷害风险等级"], risk_result_rows or [["-", "-", "-", "-", "-", "-", "当前任务暂无风险结果"]])}

  <h2>四、高风险杆塔差异化防雷</h2>
  <h3>4.1高风险杆塔原因分析</h3>
  <p>本节优先展示纳入报告范围的高风险杆塔原因分析结果；若当前选塔范围内暂无高风险杆塔，则保留所选杆塔的风险原因供复核。</p>
  <p class="caption">表12 高风险杆塔原因表</p>
  {_render_table(["杆塔号", "风险等级", "高风险原因"], high_risk_reason_rows or [["-", "-", "当前任务暂无高风险原因数据"]])}

  <h3>4.2高风险杆塔差异化防雷措施</h3>
  <p>{escape(mitigation_note)}</p>
  <p class="caption">表13 高风险杆塔差异化防雷措施</p>
  {_render_table(["杆塔号", "原风险等级", "措施前数据", "采取差异化防雷措施", "措施后数据", "采取措施后风险等级"], mitigation_table_rows or [["-", "-", "-", "当前未关联成功的措施推荐任务", "-", "-"]])}

  <p class="caption">表14 采取措施后的计算结果表</p>
  <p>若已生成与措施任务关联的加装避雷器复算任务，则下表按 {escape(scenario_base_job_type)} 口径展示补装避雷器后的耐雷水平、跳闸率与风险等级；若未生成复算任务，则此表保留为空。</p>
  {_render_table(["杆塔号", "反击耐雷水平(kA)", "反击跳闸率", "绕击耐雷水平(kA)", "绕击跳闸率", "总雷击跳闸率", "风险等级"], scenario_table_rows or [["-", "-", "-", "-", "-", "-", "当前未关联成功的加装避雷器复算任务"]])}

  <p class="muted">说明：本报告为可直接下载的 Word 兼容文档，优先补齐源端章节结构，并将目标端已落库的风险评估、地闪密度、地面倾角与措施推荐数据统一汇总输出。</p>
</body>
</html>
"""

    return summary["document_filename"], html.encode("utf-8")


def _sanitize_filename(value: str) -> str:
    cleaned = "".join("-" if char in '<>:"/\\|?*' else char for char in value).strip()
    return cleaned[:80] or "防雷分析"


def _count_risk_levels(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for row in rows:
        risk_level = _normalize_risk_level(row.get("risk_level"))
        if risk_level in counts:
            counts[risk_level] += 1
    return counts


def _format_job_type(value: str | None) -> str:
    if value == "risk":
        return "风险评估任务"
    if value == "mitigation":
        return "措施推荐任务"
    if value == "normal":
        return "普通计算任务"
    if value == "tongtiao":
        return "同跳计算任务"
    if value == "scenario":
        return "加装避雷器复算任务"
    if value == "report":
        return "报告任务"
    return value or "-"


def _format_risk_level(value: Any) -> str:
    normalized = _normalize_risk_level(value)
    if normalized is None:
        return _display(value)
    return _RISK_LEVEL_LABELS[normalized]


def _normalize_risk_level(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"high", "高", "高风险"}:
        return "high"
    if text in {"medium", "中", "中风险"}:
        return "medium"
    if text in {"low", "低", "低风险"}:
        return "low"
    return None


def _join_action_summaries(result_json: Mapping[str, Any]) -> str:
    actions = []
    for action in _read_sequence(result_json, "mitigation_actions"):
        summary = str(action.get("summary") or action.get("label") or action.get("code") or "").strip()
        if summary:
            actions.append(summary)
    return "；".join(actions) if actions else "-"


def _split_cn_list(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).replace("\n", "；")
    items = []
    for separator in ("；", ";", "、", ",", "，"):
        if separator in text:
            text = text.replace(separator, "；")
    for item in text.split("；"):
        cleaned = item.strip()
        if cleaned:
            items.append(cleaned)
    return items


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    header_html = "".join(f"<th>{escape(str(item))}</th>" for item in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<table class="data"><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>'


def _render_rule_table(label: str, rules: Sequence[tuple[str, str, bool]]) -> str:
    rows = [
        ["影响因素档级", *[rule_label for rule_label, _, _ in rules]],
        ["影响因素是否高风险", *["是" if is_risky else "否" for _, _, is_risky in rules]],
        [label, *[rule_text for _, rule_text, _ in rules]],
    ]
    return _render_table(["指标", "1", "2", "3", "4", "5"], rows)


def _render_bar_chart(caption: str, entries: Sequence[Mapping[str, Any]]) -> str:
    if not entries:
        return ""
    max_count = max((int(item.get("count") or 0) for item in entries), default=0)
    if max_count <= 0:
        max_count = 1
    body_rows = []
    for item in entries:
        count = int(item.get("count") or 0)
        ratio = float(item.get("ratio") or 0.0)
        color = str(item.get("color") or "#0F766E")
        width = round(count / max_count * 100.0, 2) if count > 0 else 0.0
        bar_html = (
            '<table class="bar-graphic" role="presentation"><tr>'
            f'<td class="bar-fill" style="width:{width}%;background:{escape(color)};"></td>'
            '<td class="bar-rest"></td>'
            "</tr></table>"
        )
        body_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('label') or '-'))}</td>"
            f"<td>{count}</td>"
            f"<td>{escape(_format_percentage(ratio))}</td>"
            f"<td>{bar_html}</td>"
            "</tr>"
        )
    return (
        f'<p class="caption">{escape(caption)}</p>'
        '<table class="data chart"><thead><tr><th>类别</th><th>数量</th><th>占比</th><th>可视化</th></tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def _render_lightning_map_section(
    rows: Sequence[Mapping[str, Any]],
    fallback_rows: Sequence[Sequence[Any]],
) -> str:
    figure_html = _render_lightning_map_figure(rows)
    if figure_html:
        return (
            '<p class="muted">说明：图7按当前报告中的杆塔经纬度与地闪密度结果渲染，颜色与表7雷区划分保持一致，灰色折线表示线路走向。</p>'
            '<p class="caption">图7 线路杆塔地闪密度雷区分布图</p>'
            f"{figure_html}"
        )
    return (
        '<p class="muted">说明：当前未提取到足够的杆塔坐标或地闪密度数据，图7暂以坐标明细表替代。</p>'
        '<p class="caption">图7 线路杆塔地闪密度雷区分布图（表格替代）</p>'
        + _render_table(
            ["杆塔号", "经度", "纬度", "雷区", "地闪密度Ng"],
            fallback_rows or [["-", "-", "-", "当前未提取到可用于分布展示的坐标或雷区数据", "-"]],
        )
    )


def _render_lightning_map_figure(rows: Sequence[Mapping[str, Any]]) -> str:
    points = _build_lightning_map_points(rows)
    if not points:
        return ""

    encoded_png = base64.b64encode(_render_lightning_map_png(points)).decode("ascii")
    skipped_count = max(len(rows) - len(points), 0)
    note = f"共渲染 {len(points)} 座杆塔，颜色表示雷区等级，灰色折线表示线路走向。"
    if skipped_count > 0:
        note += f" 另有 {skipped_count} 座因缺少坐标或地闪密度未纳入图形。"
    return (
        '<div class="figure-card">'
        f'<img class="report-image" src="data:image/png;base64,{encoded_png}" alt="线路杆塔地闪密度雷区分布图" />'
        "</div>"
        f'<p class="figure-note">{escape(note)}</p>'
    )


def _build_lightning_map_points(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for row in rows:
        base = _row_base(row)
        longitude = _as_optional_float(base.get("longitude"))
        latitude = _as_optional_float(base.get("latitude"))
        density = _row_lightning_density(row)
        code = _classify_lightning_zone_code(density)
        if longitude is None or latitude is None or code is None:
            continue
        if not _is_valid_geo_point(longitude=longitude, latitude=latitude):
            continue
        zone = next((item for item in _LIGHTNING_ZONE_RULES if item["code"] == code), None)
        rendered.append(
            {
                "tower_no": _display(row.get("tower_no")),
                "longitude": longitude,
                "latitude": latitude,
                "density": density,
                "zone_code": code,
                "zone_label": f'{zone["code"]} {zone["zone"]}' if zone else code,
                "color": str(zone["color"]) if zone else "#0F766E",
            }
        )
    return rendered


def _render_lightning_map_png(points: Sequence[Mapping[str, Any]]) -> bytes:
    width = 720
    height = 420
    plot_left = 54
    plot_right = width - 42
    plot_top = 28
    plot_bottom = height - 58
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    pixels = bytearray(width * height * 3)
    _fill_rect(pixels, width, height, 0, 0, width, height, (251, 252, 253))
    _fill_rect(pixels, width, height, plot_left, plot_top, plot_width, plot_height, (245, 249, 252))

    longitudes = [float(point["longitude"]) for point in points]
    latitudes = [float(point["latitude"]) for point in points]
    min_lon = min(longitudes)
    max_lon = max(longitudes)
    min_lat = min(latitudes)
    max_lat = max(latitudes)
    lon_span = max(max_lon - min_lon, 1e-6)
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_pad = max(lon_span * 0.08, 0.002)
    lat_pad = max(lat_span * 0.08, 0.002)
    min_lon -= lon_pad
    max_lon += lon_pad
    min_lat -= lat_pad
    max_lat += lat_pad

    for step in range(6):
        x = plot_left + round(step * plot_width / 5)
        y = plot_top + round(step * plot_height / 5)
        _draw_line(pixels, width, height, x, plot_top, x, plot_bottom, (224, 232, 240))
        _draw_line(pixels, width, height, plot_left, y, plot_right, y, (224, 232, 240))

    _draw_rect(pixels, width, height, plot_left, plot_top, plot_width, plot_height, (148, 163, 184))

    def project(longitude: float, latitude: float) -> tuple[int, int]:
        lon_ratio = (longitude - min_lon) / max(max_lon - min_lon, 1e-6)
        lat_ratio = (latitude - min_lat) / max(max_lat - min_lat, 1e-6)
        x = plot_left + round(lon_ratio * plot_width)
        y = plot_bottom - round(lat_ratio * plot_height)
        return x, y

    projected = [project(float(point["longitude"]), float(point["latitude"])) for point in points]
    for start, end in zip(projected, projected[1:]):
        _draw_thick_line(pixels, width, height, start[0], start[1], end[0], end[1], (100, 116, 139), thickness=3)

    peak_density = max((float(point["density"]) for point in points if point.get("density") is not None), default=0.0)
    for point, (x, y) in zip(points, projected):
        density = _as_optional_float(point.get("density")) or 0.0
        radius = 5 if peak_density <= 0 else 5 + int(round((density / max(peak_density, 1e-6)) * 2))
        _draw_filled_circle(pixels, width, height, x, y, radius + 2, (255, 255, 255))
        _draw_filled_circle(pixels, width, height, x, y, radius, _hex_to_rgb(str(point.get("color") or "#0F766E")))

    return _encode_png(width, height, pixels)


def _is_valid_geo_point(*, longitude: float, latitude: float) -> bool:
    return -180.0 <= longitude <= 180.0 and -90.0 <= latitude <= 90.0


def _fill_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
) -> None:
    x_start = max(x, 0)
    y_start = max(y, 0)
    x_end = min(x + rect_width, width)
    y_end = min(y + rect_height, height)
    for row in range(y_start, y_end):
        for col in range(x_start, x_end):
            _set_pixel(pixels, width, height, col, row, color)


def _draw_rect(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int],
) -> None:
    _draw_line(pixels, width, height, x, y, x + rect_width, y, color)
    _draw_line(pixels, width, height, x, y, x, y + rect_height, color)
    _draw_line(pixels, width, height, x + rect_width, y, x + rect_width, y + rect_height, color)
    _draw_line(pixels, width, height, x, y + rect_height, x + rect_width, y + rect_height, color)


def _draw_thick_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    *,
    thickness: int,
) -> None:
    half = max(thickness // 2, 0)
    if abs(x1 - x0) >= abs(y1 - y0):
        for offset in range(-half, half + 1):
            _draw_line(pixels, width, height, x0, y0 + offset, x1, y1 + offset, color)
    else:
        for offset in range(-half, half + 1):
            _draw_line(pixels, width, height, x0 + offset, y0, x1 + offset, y1, color)


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    current_x = x0
    current_y = y0
    while True:
        _set_pixel(pixels, width, height, current_x, current_y, color)
        if current_x == x1 and current_y == y1:
            break
        doubled = err * 2
        if doubled >= dy:
            err += dy
            current_x += sx
        if doubled <= dx:
            err += dx
            current_y += sy


def _draw_filled_circle(
    pixels: bytearray,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
    color: tuple[int, int, int],
) -> None:
    if radius <= 0:
        return
    radius_sq = radius * radius
    for offset_y in range(-radius, radius + 1):
        for offset_x in range(-radius, radius + 1):
            if offset_x * offset_x + offset_y * offset_y <= radius_sq:
                _set_pixel(pixels, width, height, center_x + offset_x, center_y + offset_y, color)


def _set_pixel(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    color: tuple[int, int, int],
) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    offset = (y * width + x) * 3
    pixels[offset] = color[0]
    pixels[offset + 1] = color[1]
    pixels[offset + 2] = color[2]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        return (15, 118, 110)
    try:
        return (
            int(cleaned[0:2], 16),
            int(cleaned[2:4], 16),
            int(cleaned[4:6], 16),
        )
    except ValueError:
        return (15, 118, 110)


def _encode_png(width: int, height: int, pixels: bytearray) -> bytes:
    stride = width * 3
    raw = bytearray()
    for row in range(height):
        start = row * stride
        raw.append(0)
        raw.extend(pixels[start:start + stride])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack("!I", len(payload))
            + tag
            + payload
            + struct.pack("!I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
        + chunk(b"IEND", b"")
    )


def _read_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _read_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _read_sequence(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _display(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _format_number(value: Any) -> str:
    parsed = _as_optional_float(value)
    if parsed is None:
        return "-"
    return f"{parsed:.4f}".rstrip("0").rstrip(".")


def _format_total_trip_rate(result_json: Mapping[str, Any]) -> str:
    counterstrike_value = _as_optional_float(result_json.get("counterstrike_trip_rate"))
    shielding_value = _as_optional_float(result_json.get("shielding_trip_rate"))
    if counterstrike_value is None and shielding_value is None:
        return "-"
    return _format_number((counterstrike_value or 0.0) + (shielding_value or 0.0))


def _format_percentage(value: float) -> str:
    return f"{value:.1f}%"


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _row_result(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _read_mapping(row, "result_json")


def _row_base(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _read_mapping(row, "base_tower_json")


def _row_profile(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _read_mapping(row, "profile_json")


def _row_inputs(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _read_mapping(_row_result(row), "inputs")


def _row_reason_detail(row: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    for detail in _read_sequence(_row_result(row), "reason_details"):
        if str(detail.get("code") or "").strip() == code:
            return detail
    return {}


def _row_tower_type(row: Mapping[str, Any]) -> str | None:
    candidates = (
        row.get("tower_type"),
        _row_base(row).get("tower_type"),
        _row_profile(row).get("structure_kind"),
    )
    for candidate in candidates:
        text = _as_optional_str(candidate)
        if text:
            return text
    return None


def _row_risk_grade(row: Mapping[str, Any]) -> int | None:
    result_json = _row_result(row)
    for candidate in (result_json.get("risk_grade"), row.get("risk_grade")):
        grade = _as_int(candidate)
        if grade is not None and 1 <= grade <= 4:
            return grade
    normalized = _normalize_risk_level(row.get("risk_level"))
    if normalized == "low":
        return 1
    if normalized == "medium":
        return 2
    if normalized == "high":
        return 3
    return None


def _format_risk_grade_label(grade: int | None, fallback_level: Any = None) -> str:
    if grade in _RISK_GRADE_LABELS:
        return _RISK_GRADE_LABELS[int(grade)]
    return _format_risk_level(fallback_level)


def _build_named_distribution(
    rows: Sequence[Mapping[str, Any]],
    extractor,
    *,
    preferred_order: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        label = _as_optional_str(extractor(row))
        if label:
            counts[label] += 1
    total = sum(counts.values()) or len(rows)
    if preferred_order:
        order = {value: index for index, value in enumerate(preferred_order)}
        items = sorted(counts.items(), key=lambda item: (order.get(item[0], len(order)), -item[1], item[0]))
    else:
        items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    entries: list[dict[str, Any]] = []
    for index, (label, count) in enumerate(items):
        entries.append(
            {
                "label": label,
                "count": count,
                "ratio": (count * 100.0 / total) if total else 0.0,
                "color": _DEFAULT_BAR_COLORS[index % len(_DEFAULT_BAR_COLORS)],
            }
        )
    return entries


def _build_grade_distribution(
    rows: Sequence[Mapping[str, Any]],
    *,
    code: str,
    rules: Sequence[tuple[str, str, bool]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    total = len(rows)
    for row in rows:
        detail = _row_reason_detail(row, code)
        grade = _as_int(detail.get("grade"))
        if grade is None or grade < 1 or grade > len(rules):
            continue
        counts[f"{grade}级"] += 1
    entries: list[dict[str, Any]] = []
    for index, (label, rule_text, is_risky) in enumerate(rules):
        count = counts[label]
        entries.append(
            {
                "label": label,
                "rule": rule_text,
                "is_risky": is_risky,
                "count": count,
                "ratio": (count * 100.0 / total) if total else 0.0,
                "color": _DEFAULT_BAR_COLORS[index % len(_DEFAULT_BAR_COLORS)],
            }
        )
    return entries


def _build_lightning_zone_distribution(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    total = len(rows)
    for row in rows:
        density = _row_lightning_density(row)
        code = _classify_lightning_zone_code(density)
        if code:
            counts[code] += 1
    entries: list[dict[str, Any]] = []
    for item in _LIGHTNING_ZONE_RULES:
        code = str(item["code"])
        count = counts[code]
        entries.append(
            {
                "label": f'{item["code"]} {item["zone"]}',
                "zone": item["zone"],
                "code": code,
                "rule": item["rule"],
                "count": count,
                "ratio": (count * 100.0 / total) if total else 0.0,
                "color": item["color"],
                "color_name": item["color_name"],
            }
        )
    return entries


def _build_risk_grade_distribution(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[int] = Counter()
    total = len(rows)
    for row in rows:
        grade = _row_risk_grade(row)
        if grade is not None:
            counts[grade] += 1
    severity = {1: "较低", 2: "一般", 3: "较高", 4: "严重"}
    entries: list[dict[str, Any]] = []
    for index, grade in enumerate((1, 2, 3, 4)):
        count = counts[grade]
        entries.append(
            {
                "label": _RISK_GRADE_LABELS[grade],
                "rule": severity[grade],
                "count": count,
                "ratio": (count * 100.0 / total) if total else 0.0,
                "color": _DEFAULT_BAR_COLORS[index % len(_DEFAULT_BAR_COLORS)],
            }
        )
    return entries


def _build_standard_reference_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback_voltage: int | None,
) -> list[list[str]]:
    seen: set[tuple[str, int, int, float, float]] = set()
    rendered: list[list[str]] = []
    for row in rows:
        base = _row_base(row)
        profile = _row_profile(row)
        voltage = _infer_voltage_kv(base, profile, fallback_voltage)
        if voltage is None:
            continue
        is_dc = _infer_line_kind(base, profile) == "dc"
        structure_count = _infer_structure_count(base, profile)
        insulator_standard, height_standard = _standard_values_for_line(is_dc=is_dc, voltage_kv=voltage, structure_count=structure_count)
        key = ("直流" if is_dc else "交流", structure_count, voltage, insulator_standard, height_standard)
        if key in seen:
            continue
        seen.add(key)
        rendered.append(
            [
                key[0],
                _structure_count_label(structure_count),
                str(voltage),
                _format_number(insulator_standard),
                _format_number(height_standard),
            ]
        )
    if rendered:
        return rendered
    if fallback_voltage is None:
        return []
    insulator_standard, height_standard = _standard_values_for_line(is_dc=False, voltage_kv=fallback_voltage, structure_count=1)
    return [["交流", "单回", str(fallback_voltage), _format_number(insulator_standard), _format_number(height_standard)]]


def _build_risk_threshold_reference_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fallback_voltage: int | None,
) -> list[list[str]]:
    seen: set[tuple[str, int, float]] = set()
    rendered: list[list[str]] = []
    for row in rows:
        base = _row_base(row)
        profile = _row_profile(row)
        voltage = _infer_voltage_kv(base, profile, fallback_voltage)
        if voltage is None:
            continue
        is_dc = _infer_line_kind(base, profile) == "dc"
        threshold = _risk_threshold(is_dc=is_dc, voltage_kv=voltage)
        if threshold is None:
            continue
        key = ("直流" if is_dc else "交流", voltage, threshold)
        if key in seen:
            continue
        seen.add(key)
        rendered.append([key[0], str(voltage), _format_number(threshold)])
    if rendered:
        return rendered
    if fallback_voltage is None:
        return []
    threshold = _risk_threshold(is_dc=False, voltage_kv=fallback_voltage)
    if threshold is None:
        return []
    return [["交流", str(fallback_voltage), _format_number(threshold)]]


def _build_risk_result_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in rows:
        result_json = _row_result(row)
        rendered.append(
            [
                _display(row.get("tower_no")),
                _format_number(result_json.get("counterstrike_withstand_ka")),
                _format_number(result_json.get("counterstrike_trip_rate")),
                _format_number(result_json.get("shielding_withstand_ka")),
                _format_number(result_json.get("shielding_trip_rate")),
                _format_total_trip_rate(result_json),
                _format_risk_grade_label(_row_risk_grade(row), row.get("risk_level")),
            ]
        )
    return rendered


def _build_lightning_map_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in rows:
        base = _row_base(row)
        longitude = _format_number(base.get("longitude"))
        latitude = _format_number(base.get("latitude"))
        density = _row_lightning_density(row)
        code = _classify_lightning_zone_code(density)
        if code is None:
            continue
        zone = next((item for item in _LIGHTNING_ZONE_RULES if item["code"] == code), None)
        rendered.append(
            [
                _display(row.get("tower_no")),
                longitude,
                latitude,
                f'{zone["code"]} {zone["zone"]}' if zone else code,
                _format_number(density),
            ]
        )
    return rendered


def _build_high_risk_reason_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    focus_rows = [row for row in rows if (_row_risk_grade(row) or 0) >= 3 or _normalize_risk_level(row.get("risk_level")) == "high"]
    if not focus_rows:
        focus_rows = list(rows)
    rendered: list[list[str]] = []
    for row in focus_rows:
        rendered.append(
            [
                _display(row.get("tower_no")),
                _format_risk_grade_label(_row_risk_grade(row), row.get("risk_level")),
                _display(_row_result(row).get("cause_analysis")),
            ]
        )
    return rendered


def _build_mitigation_detail_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in rows:
        result_json = _row_result(row)
        rendered.append(
            [
                _display(row.get("tower_no")),
                _format_risk_level(result_json.get("current_risk_level")),
                _build_pre_measure_data_text(result_json),
                _join_action_summaries(result_json),
                _build_post_measure_data_text(result_json),
                _format_risk_level(result_json.get("expected_risk_level") or row.get("risk_level")),
            ]
        )
    return rendered


def _build_scenario_table_rows(rows: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rendered: list[list[str]] = []
    for row in rows:
        result_json = _row_result(row)
        rendered.append(
            [
                _display(row.get("tower_no")),
                _format_number(result_json.get("counterstrike_withstand_ka")),
                _format_number(result_json.get("counterstrike_trip_rate")),
                _format_number(result_json.get("shielding_withstand_ka")),
                _format_number(result_json.get("shielding_trip_rate")),
                _format_total_trip_rate(result_json),
                _format_risk_level(row.get("risk_level")),
            ]
        )
    return rendered


def _build_pre_measure_data_text(result_json: Mapping[str, Any]) -> str:
    inputs = _read_mapping(result_json, "inputs")
    parts = []
    ground = _format_metric_text("接地电阻", inputs.get("ground_resistance_ohm"), "Ω")
    insulator = _format_metric_text("绝缘子串长", inputs.get("insulator_length_mm"), "mm")
    angle = _format_metric_text("保护角", inputs.get("protection_angle_deg"), "°")
    density = _format_metric_text("地闪密度", inputs.get("lightning_density"), "")
    for item in (ground, insulator, angle, density):
        if item:
            parts.append(item)
    return "；".join(parts) if parts else "-"


def _build_post_measure_data_text(result_json: Mapping[str, Any]) -> str:
    parts = []
    for action in _read_sequence(result_json, "mitigation_actions"):
        code = str(action.get("code") or "").strip()
        if code == "grounding_upgrade":
            parts.append(_format_target_metric_text("接地电阻", action.get("target_value"), "Ω"))
        elif code == "insulator_upgrade":
            parts.append(_format_target_metric_text("绝缘子串长", action.get("target_value"), "mm"))
        elif code == "shielding_geometry":
            parts.append(_format_target_metric_text("保护角", action.get("target_value"), "°"))
        elif code == "arrester_install":
            phase_text = _read_action_phase_text(action)
            parts.append(f"补装避雷器({phase_text})" if phase_text else "补装避雷器")
        else:
            summary = _as_optional_str(action.get("summary"))
            if summary:
                parts.append(summary)
    recommendation_result = _as_optional_str(result_json.get("recommendation_result"))
    if recommendation_result:
        parts.append(recommendation_result)
    return "；".join(parts) if parts else "-"


def _read_action_phase_text(action: Mapping[str, Any]) -> str | None:
    phases = action.get("phases")
    if not isinstance(phases, Sequence) or isinstance(phases, (str, bytes, bytearray)):
        return None
    values = [str(phase).strip() for phase in phases if str(phase).strip()]
    return ",".join(values) if values else None


def _format_metric_text(label: str, value: Any, unit: str) -> str | None:
    number = _format_number(value)
    if number == "-":
        return None
    if unit:
        return f"{label} {number}{unit}"
    return f"{label} {number}"


def _format_target_metric_text(label: str, value: Any, unit: str) -> str:
    number = _format_number(value)
    return f"{label} → {number}{unit}" if number != "-" else label


def _build_overview_stats(
    risk_rows: Sequence[Mapping[str, Any]],
    selected_risk_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    density_ready = 0
    slope_ready = 0
    protection_ready = 0
    insulator_ready = 0
    for row in risk_rows:
        if _row_lightning_density(row) is not None:
            density_ready += 1
        if _as_optional_float(_row_inputs(row).get("terrain_slope_deg")) is not None or _row_reason_detail(row, "terrain_slope"):
            slope_ready += 1
        if _as_optional_float(_row_inputs(row).get("protection_angle_deg")) is not None or _row_reason_detail(row, "protection_angle"):
            protection_ready += 1
        if _as_optional_float(_row_inputs(row).get("insulator_length_mm")) is not None or _row_reason_detail(row, "insulator_length"):
            insulator_ready += 1
    return {
        "total_towers": len(risk_rows),
        "selected_towers": len(selected_risk_rows),
        "density_ready": density_ready,
        "slope_ready": slope_ready,
        "protection_ready": protection_ready,
        "insulator_ready": insulator_ready,
    }


def _build_overview_text(stats: Mapping[str, int]) -> str:
    total_towers = int(stats.get("total_towers") or 0)
    selected_towers = int(stats.get("selected_towers") or 0)
    density_ready = int(stats.get("density_ready") or 0)
    slope_ready = int(stats.get("slope_ready") or 0)
    protection_ready = int(stats.get("protection_ready") or 0)
    insulator_ready = int(stats.get("insulator_ready") or 0)
    return (
        f"本报告基于线路既有防雷分析任务结果生成，共覆盖 {total_towers} 座杆塔，其中纳入本次报告范围的重点杆塔为 {selected_towers} 座。"
        f" 当前可直接参与报告统计的地闪密度数据 {density_ready} 座、地面倾角数据 {slope_ready} 座、保护角数据 {protection_ready} 座、"
        f"绝缘子串长度数据 {insulator_ready} 座。"
    )


def _build_named_distribution_text(prefix: str, entries: Sequence[Mapping[str, Any]], total: int, *, unit: str) -> str:
    if total <= 0 or not entries:
        return f"{prefix}当前暂无可统计的分类数据。"
    parts = [f'{entry["label"]}{entry["count"]}{unit}，占比{_format_percentage(float(entry["ratio"]))}' for entry in entries]
    return f"{prefix}共统计 {total}{unit}，其中" + "；".join(parts) + "。"


def _build_grade_distribution_text(prefix: str, entries: Sequence[Mapping[str, Any]], total: int, *, suffix: str) -> str:
    if total <= 0 or not entries:
        return f"{prefix}当前暂无可统计的分级结果。"
    parts = [f'{entry["label"]}{entry["count"]}{suffix}，占比{_format_percentage(float(entry["ratio"]))}' for entry in entries]
    return f"{prefix}共统计 {total}{suffix}，其中" + "；".join(parts) + "。"


def _build_lightning_distribution_text(entries: Sequence[Mapping[str, Any]], total: int) -> str:
    if total <= 0 or not entries:
        return "在线路杆塔地闪密度方面，当前暂无可统计的雷区分布结果。"
    parts = [f'{entry["label"]}{entry["count"]}座，占比{_format_percentage(float(entry["ratio"]))}' for entry in entries if int(entry["count"]) > 0]
    if not parts:
        return "在线路杆塔地闪密度方面，当前风险结果尚未形成有效雷区分布。"
    return "在线路杆塔地闪密度方面，" + "；".join(parts) + "。"


def _build_risk_distribution_text(entries: Sequence[Mapping[str, Any]], total: int) -> str:
    if total <= 0 or not entries:
        return "当前暂无可统计的雷害风险等级结果。"
    parts = [f'{entry["label"]}级 {entry["count"]}座，占比{_format_percentage(float(entry["ratio"]))}' for entry in entries]
    return f"全线共统计 {total} 座杆塔，风险等级分布为：" + "；".join(parts) + "。"


def _build_mitigation_note(*, summary: Mapping[str, Any], non_construction: bool) -> str:
    actions = list((summary.get("mitigation_action_counts") or {}).keys())
    action_text = "、".join(actions) if actions else "降低接地电阻、提高绝缘子串长度、补装避雷器"
    if non_construction:
        return (
            "当前报告按未建线口径输出差异化防雷措施，除接地治理、绝缘提升和补装避雷器外，"
            f"还允许结合规划阶段条件同步优化保护角。综合建议主要包括：{action_text}。"
        )
    return (
        "当前报告按已建线口径输出差异化防雷措施，重点围绕接地治理、绝缘提升、补装避雷器及既有塔位复核展开。"
        f"综合建议主要包括：{action_text}。"
    )


def _distribution_rows(entries: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [
        [
            _display(entry.get("label")),
            str(int(entry.get("count") or 0)),
            _format_percentage(float(entry.get("ratio") or 0.0)),
        ]
        for entry in entries
    ]


def _grade_distribution_rows(entries: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [
        [
            _display(entry.get("label")),
            _display(entry.get("rule")),
            "是" if bool(entry.get("is_risky")) else "否",
            str(int(entry.get("count") or 0)),
            _format_percentage(float(entry.get("ratio") or 0.0)),
        ]
        for entry in entries
    ]


def _lightning_zone_rule_rows() -> list[list[str]]:
    return [
        [str(item["zone"]), str(item["code"]), str(item["rule"]), str(item["color_name"])]
        for item in _LIGHTNING_ZONE_RULES
    ]


def _lightning_distribution_rows(entries: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [
        [
            _display(entry.get("zone")),
            _display(entry.get("code")),
            _display(entry.get("rule")),
            str(int(entry.get("count") or 0)),
            _format_percentage(float(entry.get("ratio") or 0.0)),
        ]
        for entry in entries
    ]


def _row_lightning_density(row: Mapping[str, Any]) -> float | None:
    inputs = _row_inputs(row)
    for candidate in (inputs.get("lightning_density"), _row_base(row).get("lightning_density")):
        parsed = _as_optional_float(candidate)
        if parsed is not None:
            return parsed
    return None


def _classify_lightning_zone_code(value: float | None) -> str | None:
    if value is None:
        return None
    if value <= 0.78:
        return "A"
    if value <= 2.0:
        return "B1"
    if value <= 2.78:
        return "B2"
    if value <= 5.0:
        return "C1"
    if value <= 7.98:
        return "C2"
    if value <= 11.0:
        return "D1"
    return "D2"


def _infer_line_kind(base: Mapping[str, Any], profile: Mapping[str, Any]) -> str:
    geometry_layers = profile.get("geometry_layers_json") if isinstance(profile.get("geometry_layers_json"), Mapping) else {}
    return infer_topology_line_kind(
        tower_model=base.get("tower_model"),
        tower_type=base.get("tower_type"),
        structure_kind=profile.get("structure_kind"),
        geometry_topology=geometry_layers.get("topology_kind") if isinstance(geometry_layers, Mapping) else None,
    )


def _infer_voltage_kv(base: Mapping[str, Any], profile: Mapping[str, Any], fallback_voltage: int | None) -> int | None:
    raw_extra = base.get("raw_extra_json") if isinstance(base.get("raw_extra_json"), Mapping) else {}
    for candidate in (
        raw_extra.get("voltage_kv") if isinstance(raw_extra, Mapping) else None,
        base.get("line_voltage_kv"),
        profile.get("voltage_kv"),
        fallback_voltage,
    ):
        parsed = _as_int(candidate)
        if parsed is not None and parsed > 0:
            return parsed
    marker = "|".join(
        [
            str(base.get("tower_model") or ""),
            str(base.get("tower_type") or ""),
            str(profile.get("structure_kind") or ""),
        ]
    )
    for voltage in (1000, 800, 750, 500, 330, 220, 110, 66, 35):
        if str(voltage) in marker:
            return voltage
    return None


def _infer_structure_count(base: Mapping[str, Any], profile: Mapping[str, Any]) -> int:
    geometry_layers = profile.get("geometry_layers_json") if isinstance(profile.get("geometry_layers_json"), Mapping) else {}
    return infer_topology_structure_count(
        tower_model=base.get("tower_model"),
        tower_type=base.get("tower_type"),
        structure_kind=profile.get("structure_kind"),
        geometry_topology=geometry_layers.get("topology_kind") if isinstance(geometry_layers, Mapping) else None,
    )


def _standard_values_for_line(*, is_dc: bool, voltage_kv: int, structure_count: int) -> tuple[float, float]:
    if is_dc:
        return _DC_STANDARD_BY_VOLTAGE.get(voltage_kv, _DEFAULT_DC_STANDARD)
    insulator_standard, structure_heights = _AC_STANDARD_BY_VOLTAGE.get(voltage_kv, _DEFAULT_AC_STANDARD)
    return insulator_standard, structure_heights.get(structure_count, structure_heights[max(structure_heights)])


def _risk_threshold(*, is_dc: bool, voltage_kv: int) -> float | None:
    if is_dc:
        return _DC_RISK_THRESHOLDS.get(voltage_kv)
    return _AC_RISK_THRESHOLDS.get(voltage_kv)


def _structure_count_label(value: int) -> str:
    if value == 1:
        return "单回"
    if value == 2:
        return "双回"
    if value == 4:
        return "四回"
    return f"{value}回"
