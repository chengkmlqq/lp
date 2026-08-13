#!/usr/bin/env python3
# NOTE(LP-316): 本文件为「输电线路故障综合判别系统 v1.0.4」交付版 app\source\fault_diagnosis.py
# 的逐字移植（纯 Python，仅依赖标准库），以保证判别结果与交付版一致。请勿在此文件直接修改业务逻辑；
# 集成/降级/字段映射在 fault_diagnosis_service.py 中处理。
"""多源故障综合判别的前四步。

1. 读取并归一化录波、雷电定位、线路台账和光学监测输入；
2. 判断是否为接地故障；
3. 按《判别流程及分析报告.docx》计算过渡电阻并分级。
4. 融合录波、行波、雷电定位，并按杆塔耐雷水平分析雷击原因。

本模块既可作为命令行工具运行，也可由后续定位、原因分析和报告模块导入。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


FAULT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "station": ("station", "录波记录厂站", "厂站名称"),
    "fault_time": ("fault_time", "故障时刻", "故障时间", "故障开始时间"),
    "line_name": ("line_name", "故障线路名称", "故障线路", "线路名称"),
    "fault_phase": ("fault_phase", "故障相", "故障相别"),
    "duration_ms": ("duration_ms", "故障持续时间(ms)", "故障持续时间"),
    "reclosing": ("reclosing", "重合闸情况", "重合闸"),
    "phase_voltage": ("phase_voltage", "故障相电压", "故障相电压(V)"),
    "phase_current": ("phase_current", "故障相电流", "故障相电流(A)"),
    "zero_sequence_current": (
        "zero_sequence_current",
        "最大零序电流(A)",
        "最大零序电流",
        "零序电流",
        "I0",
        "3I0",
    ),
    "zero_sequence_compensation_k": (
        "zero_sequence_compensation_k",
        "零序补偿系数K",
        "零序电抗补偿系数",
    ),
    "line_length_km": ("line_length_km", "线路总长度L(km)", "线路总长度L（km）", "线路总长度"),
    "sensitive_angle_deg": (
        "sensitive_angle_deg",
        "线路正序灵敏角(°)",
        "线路正序灵敏角°",
        "线路正序灵敏角",
    ),
    "positive_sequence_impedance_ohm": (
        "positive_sequence_impedance_ohm",
        "线路正序阻抗定值(Ω)",
        "线路正序阻抗定值（Ω）",
        "线路正序阻抗定值",
    ),
}

LEDGER_OUTPUT_FIELDS: dict[str, str] = {
    "线路名称": "line_name",
    "电压等级": "voltage_level_kv",
    "塔号": "tower_no",
    "地形": "terrain",
    "地闪密度": "ground_flash_density",
    "海拔m": "elevation_m",
    "杆塔模型": "tower_model",
    "塔形": "tower_shape",
    "直线或耐张杆塔": "tower_function",
    "绝缘子串长度mm": "insulator_length_mm",
    "接地电阻": "ground_resistance_ohm",
    "反击耐雷水平kA": "backflashover_withstand_ka",
    "绕击耐雷水平kA": "shielding_failure_withstand_ka",
    "雷击风险等级": "lightning_risk_level",
    "经度": "longitude",
    "纬度": "latitude",
}

LIGHTNING_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("event_id", "事件编号", "故障编号"),
    "line_name": ("line_name", "线路名称", "故障线路名称"),
    "fault_time": ("fault_time", "故障时刻", "故障时间"),
    "query_result": ("query_result", "是否存在落雷记录", "雷电定位查询结果"),
    "location_time": ("location_time", "雷电定位时刻", "落雷时刻"),
    "current_ka": (
        "current_ka",
        "雷电流幅值(kA)",
        "雷电流幅值（kA）",
        "雷电流幅值I(kA)",
        "雷电流幅值",
    ),
    "nearest_tower": (
        "nearest_tower",
        "雷电定位最近杆塔",
        "雷电定位最近杆塔号",
        "最近杆塔",
    ),
    "distance_to_line_km": (
        "distance_to_line_km",
        "雷击点距线路距离(km)",
        "雷击点距线路距离（km）",
        "距线路距离(km)",
    ),
    "distance_to_nearest_tower_m": (
        "distance_to_nearest_tower_m",
        "雷击点距最近杆塔距离(m)",
        "雷击点距最近杆塔距离（m）",
        "距最近杆塔距离(m)",
    ),
    "line_side_distances_km": (
        "line_side_distances_km",
        "线路两侧距离(km)",
        "线路两侧距离（km）",
    ),
    "recording_distance_km": (
        "recording_distance_km",
        "录波测距(km)",
        "录波测距（km）",
        "录波测距",
    ),
    "recording_nearest_tower": (
        "recording_nearest_tower",
        "录波测距最近杆塔",
        "录波测距最近杆塔号",
    ),
    "traveling_wave_distance_km": (
        "traveling_wave_distance_km",
        "行波测距(km)",
        "行波测距（km）",
        "行波测距",
    ),
    "traveling_wave_nearest_tower": (
        "traveling_wave_nearest_tower",
        "行波测距最近杆塔",
        "行波测距最近杆塔号",
    ),
    "remarks": ("remarks", "数据来源/备注", "备注"),
}


class InputError(ValueError):
    """输入缺失、格式错误或物理量无法计算。"""


@dataclass
class GroundDecision:
    status: str
    is_ground_fault: bool | None
    fault_kind: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ResistanceResult:
    status: str
    zm_ohm: float | None = None
    transition_resistance_ohm: float | None = None
    category: str | None = None
    category_report_text: str | None = None
    formula_zm: str | None = None
    formula_rf: str = "Rf ≈ Zm × cos(φ) - Z+ / L"
    selected_zero_sequence_representation: str | None = None
    selection_reason: str | None = None
    zero_sequence_comparison: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "None", "nan", "NaN"}


def canonicalize_fault_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把中文表头或英文 API 字段统一为内部字段名。"""
    result: dict[str, Any] = {}
    for canonical, aliases in FAULT_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw and _has_value(raw[alias]):
                result[canonical] = raw[alias]
                break
    return result


def canonicalize_lightning_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把雷电定位 Excel 表头统一为内部字段名。"""
    result: dict[str, Any] = {}
    for canonical, aliases in LIGHTNING_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in raw and _has_value(raw[alias]):
                result[canonical] = raw[alias]
                break
    return result


def _first_tabular_row(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if any(_has_value(v) for v in row.values()):
            return dict(row)
    raise InputError("输入表格中没有有效数据行")


def _read_csv_rows(path: Path, *, wrapper_aware: bool = False) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line.strip()]
    if wrapper_aware:
        lines = [line for line in lines if not line.lstrip().startswith("<")]
    if not lines:
        return []
    return list(csv.DictReader(lines))


def _read_xlsx_first_row(path: Path) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:
        raise InputError("读取 XLSX 需要 openpyxl；请使用项目的 Python 运行环境") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = sheet.iter_rows(values_only=True)
        headers = [str(v).strip() if v is not None else "" for v in next(rows)]
        for values in rows:
            row = {headers[i]: values[i] for i in range(min(len(headers), len(values))) if headers[i]}
            if any(_has_value(v) for v in row.values()):
                return row
    except StopIteration as exc:
        raise InputError(f"XLSX 为空: {path}") from exc
    finally:
        workbook.close()
    raise InputError(f"XLSX 没有有效数据行: {path}")


def _load_pdf_fault_info(path: Path, extractor_path: Path | None, ocr_engine: str) -> dict[str, Any]:
    if extractor_path is None:
        extractor_path = Path(__file__).resolve().parent.parent / "录波" / "extract_fault_report.py"
    if not extractor_path.exists():
        raise InputError(f"找不到录波 PDF 提取器: {extractor_path}")

    spec = importlib.util.spec_from_file_location("fault_report_extractor", extractor_path)
    if spec is None or spec.loader is None:
        raise InputError(f"无法加载录波 PDF 提取器: {extractor_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    text = module.extract_pdf_text(path)
    if not text and ocr_engine != "text":
        text = module.ocr_pdf(path, engine=ocr_engine, dpi=150, tesseract_lang="chi_sim+eng", pages=None)
    if not text:
        raise InputError("PDF 没有可用文本；请启用 OCR 或先运行录波提取程序")
    return dict(module.parse_fault_info(text))


def load_fault_source(path: Path, *, extractor_path: Path | None = None, ocr_engine: str = "auto") -> dict[str, Any]:
    """读取录波提取结果；支持 PDF、JSON、CSV 和 XLSX。"""
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, Mapping):
            raise InputError("录波 JSON 顶层必须是对象")
        if isinstance(raw.get("fault_record"), Mapping):
            raw = raw["fault_record"]
        return dict(raw)
    if suffix == ".csv":
        return _first_tabular_row(_read_csv_rows(path))
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx_first_row(path)
    if suffix == ".pdf":
        return _load_pdf_fault_info(path, extractor_path, ocr_engine)
    raise InputError(f"不支持的录波输入格式: {suffix}")


def load_lightning_source(path: Path) -> dict[str, Any]:
    """读取人工整理的雷电流与定位 Excel；CSV 仅用于测试或临时交换。"""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        raw = _read_xlsx_first_row(path)
    elif suffix == ".csv":
        raw = _first_tabular_row(_read_csv_rows(path))
    else:
        raise InputError("雷电定位输入必须是 XLSX/XLSM（也兼容 CSV）")
    result = canonicalize_lightning_fields(raw)
    if not result:
        expected = "、".join(aliases[1] for aliases in LIGHTNING_FIELD_ALIASES.values())
        raise InputError(f"雷电定位表未识别到有效字段，建议表头包括：{expected}")
    return result


def load_manual_input(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise InputError("人工输入 JSON 顶层必须是对象")
    return raw


def _to_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise InputError(f"{field_name} 不能是布尔值")
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(value).replace(",", ""))
    if not match:
        raise InputError(f"{field_name} 不是数值: {value!r}")
    return float(match.group(0))


def _normalize_binary_scores(first: Any, second: Any) -> tuple[float, float] | None:
    """将二分类原始判别值归一化为工程展示概率，不作为校准后的统计概率。"""
    if not _has_value(first) or not _has_value(second):
        return None
    try:
        first_value = float(first)
        second_value = float(second)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(first_value) or not math.isfinite(second_value):
        return None
    maximum = max(first_value, second_value)
    first_exp = math.exp(first_value - maximum)
    second_exp = math.exp(second_value - maximum)
    total = first_exp + second_exp
    return (first_exp / total, second_exp / total) if total else None


def _split_measurements(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    text = str(value).strip()
    return [part.strip() for part in re.split(r"[/；;，,]", text) if part.strip()]


def _unit_factor(token: Any, kind: str, default_unit: str) -> float:
    text = str(token).lower().replace(" ", "")
    if kind == "voltage":
        if "kv" in text:
            return 1000.0
        if re.search(r"(?<!k)v", text):
            return 1.0
        return 1000.0 if default_unit.lower() == "kv" else 1.0
    if kind == "current":
        if "ka" in text:
            return 1000.0
        if re.search(r"(?<!k)a", text):
            return 1.0
        return 1000.0 if default_unit.lower() == "ka" else 1.0
    return 1.0


def parse_measurements(value: Any, *, kind: str, default_unit: str, field_name: str) -> list[float]:
    if not _has_value(value):
        raise InputError(f"缺少{field_name}")
    values: list[float] = []
    for token in _split_measurements(value):
        values.append(_to_float(token, field_name) * _unit_factor(token, kind, default_unit))
    if not values:
        raise InputError(f"缺少{field_name}")
    return values


def _normalize_phase(value: Any) -> tuple[str, list[str], bool]:
    text = str(value or "").upper().replace("相", "")
    letters: list[str] = []
    for phase in re.findall(r"[ABC]", text):
        if phase not in letters:
            letters.append(phase)
    explicit_ground = bool(re.search(r"[NG]|接地|GROUND", text, flags=re.IGNORECASE))
    return text, letters, explicit_ground


def decide_ground_fault(
    fault: Mapping[str, Any],
    *,
    default_current_unit: str = "kA",
    zero_sequence_ratio_threshold: float = 0.10,
    zero_sequence_absolute_threshold_a: float = 100.0,
) -> GroundDecision:
    """依据故障相编码与零序电流作可解释判别。"""
    raw_phase = fault.get("fault_phase", "")
    normalized, phases, explicit_ground = _normalize_phase(raw_phase)
    evidence: list[str] = []
    warnings: list[str] = []

    zero_sequence_a: float | None = None
    phase_current_a: list[float] = []
    if _has_value(fault.get("zero_sequence_current")):
        try:
            zero_sequence_a = abs(
                parse_measurements(
                    fault["zero_sequence_current"],
                    kind="current",
                    default_unit=default_current_unit,
                    field_name="最大零序电流",
                )[0]
            )
        except InputError as exc:
            warnings.append(str(exc))
    if _has_value(fault.get("phase_current")):
        try:
            phase_current_a = [
                abs(v)
                for v in parse_measurements(
                    fault["phase_current"],
                    kind="current",
                    default_unit=default_current_unit,
                    field_name="故障相电流",
                )
            ]
        except InputError as exc:
            warnings.append(str(exc))

    zero_sequence_significant = False
    if zero_sequence_a is not None:
        if phase_current_a and max(phase_current_a) > 0:
            ratio = zero_sequence_a / max(phase_current_a)
            # 有故障相电流时优先使用相对比例，兼容保护二次侧 A 量和一次侧 kA 量。
            zero_sequence_significant = ratio >= zero_sequence_ratio_threshold
            evidence.append(f"零序/故障相电流比={ratio:.3f}")
        else:
            zero_sequence_significant = zero_sequence_a >= zero_sequence_absolute_threshold_a
        evidence.append(f"最大零序电流={zero_sequence_a:.3f} A")

    if explicit_ground:
        evidence.insert(0, f"故障相编码“{raw_phase}”含接地标志 N/G/接地")
        kind = "单相接地" if len(phases) == 1 else "两相接地" if len(phases) == 2 else "多相接地"
        return GroundDecision("decided", True, kind, 0.99, evidence, warnings)

    if len(phases) == 1:
        evidence.insert(0, f"仅检测到一个故障相（{phases[0]}），输电线路单相短路按单相接地处理")
        if zero_sequence_a is None:
            warnings.append("未提供最大零序电流，接地结论主要来自故障相型")
        elif not zero_sequence_significant:
            warnings.append("故障相型与零序电流显著性不一致，建议复核量纲及提取值")
        return GroundDecision("decided", True, "单相接地", 0.95 if zero_sequence_significant else 0.85, evidence, warnings)

    if len(phases) in {2, 3}:
        if zero_sequence_significant:
            evidence.insert(0, "多相故障且零序电流显著，判为接地故障")
            kind = "两相接地" if len(phases) == 2 else "三相接地"
            return GroundDecision("decided", True, kind, 0.90, evidence, warnings)
        evidence.insert(0, f"故障相编码“{normalized}”无接地标志，且零序电流不显著或缺失")
        kind = "相间短路" if len(phases) == 2 else "三相短路"
        return GroundDecision("decided", False, kind, 0.90 if zero_sequence_a is not None else 0.80, evidence, warnings)

    if zero_sequence_significant:
        evidence.insert(0, "故障相编码不完整，但零序电流显著")
        warnings.append("无法由故障相数量确定单相/两相接地类型")
        return GroundDecision("decided", True, "接地故障（相别待复核）", 0.70, evidence, warnings)

    warnings.append("缺少可识别的故障相编码，且没有显著零序电流证据")
    return GroundDecision("uncertain", None, "无法判定", 0.0, evidence, warnings)


def _required_float(fault: Mapping[str, Any], key: str, label: str) -> float:
    if not _has_value(fault.get(key)):
        raise InputError(f"缺少{label}")
    return _to_float(fault[key], label)


def _classify_transition_resistance(rf_ohm: float) -> tuple[str, str, str, list[str]]:
    if rf_ohm < 0:
        return (
            "needs_review",
            "计算异常（负值）",
            "建议人工复核电气量单位、相量与零序电流定义",
            ["计算得到负过渡电阻，未强制截断为0"],
        )
    if rf_ohm < 3.0:
        return "ok", "金属性接地故障", "金属性接地", []
    if rf_ohm < 500.0:
        return "ok", "低阻接地故障", "小电阻接地", []
    return "ok", "高阻接地故障", "高阻接地", []


def calculate_transition_resistance(
    fault: Mapping[str, Any],
    decision: GroundDecision,
    *,
    default_voltage_unit: str = "kV",
    default_current_unit: str = "kA",
    zero_sequence_representation: str = "3I0",
) -> ResistanceResult:
    """严格按 Word 公式计算，并对单相故障同时比较 3I0/I0 两种输入定义。"""
    if decision.is_ground_fault is False:
        return ResistanceResult(status="not_applicable", warnings=["相间故障不计算接地过渡电阻"])
    if decision.is_ground_fault is None:
        return ResistanceResult(status="unavailable", warnings=["接地属性未确定，暂不计算过渡电阻"])

    _, phases, _ = _normalize_phase(fault.get("fault_phase", ""))
    if not decision.fault_kind.startswith("单相") or len(phases) != 1:
        return ResistanceResult(
            status="not_applicable",
            warnings=["当前过渡电阻公式仅用于单相接地故障；两相接地、三相接地及相间故障均不计算"],
        )

    result = ResistanceResult(status="ok")
    try:
        voltages_v = parse_measurements(
            fault.get("phase_voltage"),
            kind="voltage",
            default_unit=default_voltage_unit,
            field_name="故障相电压",
        )
        currents_a = parse_measurements(
            fault.get("phase_current"),
            kind="current",
            default_unit=default_current_unit,
            field_name="故障相电流",
        )

        single_phase_candidates: dict[str, dict[str, float]] = {}
        if len(phases) <= 1 or decision.fault_kind.startswith("单相"):
            i0_a = parse_measurements(
                fault.get("zero_sequence_current"),
                kind="current",
                default_unit=default_current_unit,
                field_name="最大零序电流",
            )[0]
            k = _required_float(fault, "zero_sequence_compensation_k", "零序补偿系数K")
            representation = zero_sequence_representation.strip().upper()
            if representation not in {"I0", "3I0"}:
                raise InputError("zero_sequence_representation 只能是 I0 或 3I0")
            for candidate_representation in ("3I0", "I0"):
                three_i0_a = i0_a if candidate_representation == "3I0" else i0_a * 3.0
                denominator_a = currents_a[0] + k * three_i0_a
                if abs(denominator_a) < 1e-12:
                    raise InputError(
                        f"按输入为{candidate_representation}计算时，分母 Iφ + K·3I0 为零"
                    )
                single_phase_candidates[candidate_representation] = {
                    "three_i0_a_used": three_i0_a,
                    "denominator_a": denominator_a,
                    "zm_ohm": voltages_v[0] / denominator_a,
                }
            selected_candidate = single_phase_candidates[representation]
            three_i0_a = selected_candidate["three_i0_a_used"]
            zm_ohm = selected_candidate["zm_ohm"]
            result.formula_zm = "Zm = Uφ / (Iφ + K × 3I0)"
            result.selected_zero_sequence_representation = representation
            result.selection_reason = (
                "录波提取字段已确认存储3I0，主结果按输入值直接作为3I0；I0假设仅作对照"
                if representation == "3I0"
                else "计算设置明确指定输入值为I0；仍保留3I0假设作对照"
            )
            result.inputs.update(
                {
                    "phase_voltage_v": voltages_v[0],
                    "phase_current_a": currents_a[0],
                    "provided_zero_sequence_current_a": i0_a,
                    "zero_sequence_representation": representation,
                    "three_i0_a_used": three_i0_a,
                    "zero_sequence_compensation_k": k,
                }
            )
        else:
            if len(voltages_v) < 2 or len(currents_a) < 2:
                raise InputError("两相接地计算需要两个故障相的电压和电流（可用斜杠分隔）")
            current_difference_a = currents_a[0] - currents_a[1]
            if abs(current_difference_a) < 1e-12:
                raise InputError("两相接地阻抗分母 Iφ1-Iφ2 为零")
            zm_ohm = (voltages_v[0] - voltages_v[1]) / current_difference_a
            result.formula_zm = "Zm = (Uφ1 - Uφ2) / (Iφ1 - Iφ2)"
            result.inputs.update(
                {
                    "phase_voltages_v": voltages_v[:2],
                    "phase_currents_a": currents_a[:2],
                }
            )

        line_length_km = _required_float(fault, "line_length_km", "线路总长度L")
        sensitive_angle_deg = _required_float(fault, "sensitive_angle_deg", "线路正序灵敏角φ")
        z_positive_ohm = _required_float(
            fault, "positive_sequence_impedance_ohm", "线路正序阻抗定值Z+"
        )
        if line_length_km <= 0:
            raise InputError("线路总长度L必须大于0")

        rf_ohm = zm_ohm * math.cos(math.radians(sensitive_angle_deg)) - z_positive_ohm / line_length_km
        result.zm_ohm = round(zm_ohm, 9)
        result.transition_resistance_ohm = round(rf_ohm, 9)
        result.inputs.update(
            {
                "line_length_km": line_length_km,
                "sensitive_angle_deg": sensitive_angle_deg,
                "positive_sequence_impedance_ohm": z_positive_ohm,
                "zm_cos_phi_ohm": zm_ohm * math.cos(math.radians(sensitive_angle_deg)),
                "z_positive_over_length_ohm": z_positive_ohm / line_length_km,
            }
        )

        status, category, report_text, classification_warnings = _classify_transition_resistance(rf_ohm)
        result.status = status
        result.category = category
        result.category_report_text = report_text
        result.warnings.extend(classification_warnings)

        if single_phase_candidates:
            comparison: dict[str, Any] = {}
            for candidate_representation, candidate in single_phase_candidates.items():
                candidate_rf = (
                    candidate["zm_ohm"] * math.cos(math.radians(sensitive_angle_deg))
                    - z_positive_ohm / line_length_km
                )
                candidate_status, candidate_category, _, candidate_warnings = (
                    _classify_transition_resistance(candidate_rf)
                )
                comparison[f"provided_as_{candidate_representation}"] = {
                    "assumption": f"提取值按{candidate_representation}解释",
                    "three_i0_a_used": round(candidate["three_i0_a_used"], 9),
                    "denominator_a": round(candidate["denominator_a"], 9),
                    "zm_ohm": round(candidate["zm_ohm"], 9),
                    "transition_resistance_ohm": round(candidate_rf, 9),
                    "status": candidate_status,
                    "category": candidate_category,
                    "warnings": candidate_warnings,
                    "selected": candidate_representation == result.selected_zero_sequence_representation,
                }
            result.zero_sequence_comparison = comparison
            alternate_key = "provided_as_I0" if representation == "3I0" else "provided_as_3I0"
            alternate = comparison[alternate_key]
            if alternate["status"] == "needs_review" and result.status == "ok":
                result.warnings.append(
                    f"对照计算“{alternate['assumption']}”得到负值；主结果依据字段定义选择{representation}"
                )
    except InputError as exc:
        result.status = "unavailable"
        result.warnings.append(str(exc))
    return result


def load_ledger_rows(path: Path) -> list[dict[str, str]]:
    rows = _read_csv_rows(path, wrapper_aware=True)
    return [row for row in rows if _has_value(row.get("线路名称")) and _has_value(row.get("塔号"))]


def _normalize_line_name(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\d+(?:\.\d+)?\s*KV", lambda m: m.group(0).replace("KV", ""), text)
    text = re.sub(r"[·•\s_\-—－]", "", text)
    text = text.replace("线路", "")
    if text.endswith("线"):
        text = text[:-1]
    return text


def _normalize_tower(value: Any) -> str:
    text = str(value or "").upper()
    return re.sub(r"(?:杆塔|塔号|塔|#|＃|\s)", "", text)


def _tower_number(value: Any) -> str | None:
    match = re.search(r"\d+", _normalize_tower(value))
    return str(int(match.group(0))) if match else None


def _tower_numbers(value: Any) -> list[str]:
    numbers: list[str] = []
    for token in re.findall(r"\d+", _normalize_tower(value)):
        normalized = str(int(token))
        if normalized not in numbers:
            numbers.append(normalized)
    return numbers


def _clean_ledger_value(value: Any) -> Any:
    if not _has_value(value):
        return None
    text = str(value).strip()
    try:
        number = float(text)
        return int(number) if number.is_integer() else number
    except ValueError:
        return text


def lookup_ledger(
    rows: Sequence[Mapping[str, Any]], line_name: Any, tower_no: Any
) -> dict[str, Any]:
    target_line = _normalize_line_name(line_name)
    target_tower = _normalize_tower(tower_no)
    target_numbers = _tower_numbers(tower_no)
    if not target_line:
        return {"matched": False, "reason": "缺少线路名称"}
    if not target_tower:
        return {"matched": False, "reason": "缺少用于查询台账的杆塔号"}

    available_line_names = sorted(
        {
            str(row.get("线路名称")).strip()
            for row in rows
            if _has_value(row.get("线路名称"))
        }
    )
    line_candidates = [row for row in rows if _normalize_line_name(row.get("线路名称")) == target_line]
    exact = [row for row in line_candidates if _normalize_tower(row.get("塔号")) == target_tower]
    if not exact and target_numbers:
        exact = [row for row in line_candidates if _tower_number(row.get("塔号")) in target_numbers]
        exact.sort(
            key=lambda row: target_numbers.index(_tower_number(row.get("塔号")) or "")
            if (_tower_number(row.get("塔号")) or "") in target_numbers
            else len(target_numbers)
        )
    if not exact:
        return {
            "matched": False,
            "reason": f"台账中未找到线路={line_name!s}、杆塔={tower_no!s}",
            "line_candidate_count": len(line_candidates),
            "requested_line_name": str(line_name) if _has_value(line_name) else None,
            "available_line_names": available_line_names,
        }

    records: list[dict[str, Any]] = []
    for source in exact:
        record = {
            output_name: _clean_ledger_value(source.get(source_name))
            for source_name, output_name in LEDGER_OUTPUT_FIELDS.items()
        }
        insulator_mm = record.get("insulator_length_mm")
        if isinstance(insulator_mm, (int, float)):
            record["insulator_length_m"] = round(float(insulator_mm) / 1000.0, 6)
        records.append(record)
    return {
        "matched": True,
        "requested_line_name": str(line_name),
        "available_line_names": available_line_names,
        "query_tower": str(tower_no),
        "match_type": "tower_range" if len(records) > 1 else "single_tower",
        "record": records[0],
        "records": records,
    }


def fuse_fault_location(
    lightning: Mapping[str, Any],
    *,
    validation: Mapping[str, Any] | None = None,
    distance_agreement_tolerance_km: float = 0.5,
) -> dict[str, Any]:
    """融合雷电定位、录波测距和行波测距的最近杆塔结果。"""
    source_specs = (
        ("lightning_location", "雷电定位", "nearest_tower", None),
        ("recording_distance", "录波测距", "recording_nearest_tower", "recording_distance_km"),
        ("traveling_wave_distance", "行波测距", "traveling_wave_nearest_tower", "traveling_wave_distance_km"),
    )
    sources: list[dict[str, Any]] = []
    for source_key, label, tower_key, distance_key in source_specs:
        raw_tower = lightning.get(tower_key)
        tower_numbers = [int(value) for value in _tower_numbers(raw_tower)]
        entry: dict[str, Any] = {
            "source": source_key,
            "label": label,
            "tower": str(raw_tower).strip() if _has_value(raw_tower) else None,
            "tower_numbers": tower_numbers,
            "available": bool(tower_numbers),
        }
        if distance_key and _has_value(lightning.get(distance_key)):
            try:
                entry["distance_km"] = _to_float(lightning[distance_key], label)
            except InputError:
                entry["distance_km"] = None
        sources.append(entry)

    available = [entry for entry in sources if entry["available"]]
    evidence: list[str] = []
    warnings: list[str] = []
    support: dict[int, list[str]] = {}
    for entry in available:
        for tower_number in entry["tower_numbers"]:
            support.setdefault(tower_number, []).append(entry["label"])

    recording = next(entry for entry in sources if entry["source"] == "recording_distance")
    traveling = next(entry for entry in sources if entry["source"] == "traveling_wave_distance")
    if recording.get("distance_km") is not None and traveling.get("distance_km") is not None:
        difference = abs(recording["distance_km"] - traveling["distance_km"])
        evidence.append(f"录波与行波测距差值为 {difference:.3f} km")
        if difference <= distance_agreement_tolerance_km:
            evidence.append("录波与行波距离数值相互吻合")
        else:
            warnings.append(
                f"录波与行波测距相差 {difference:.3f} km，超过 {distance_agreement_tolerance_km:.3f} km"
            )
        if set(recording["tower_numbers"]).isdisjoint(traveling["tower_numbers"]):
            warnings.append("录波与行波的测距数值接近，但最近杆塔字段不一致，建议复核杆塔映射")

    result: dict[str, Any] = {
        "status": "unavailable",
        "result_text": "无法定位",
        "fused_tower": None,
        "query_tower": None,
        "candidate_section": lightning.get("nearest_tower"),
        "confidence": 0.0,
        "source_count": len(available),
        "supporting_source_count": 0,
        "sources": sources,
        "evidence": evidence,
        "warnings": warnings,
        "provisional": False,
    }
    if support:
        max_support = max(len(labels) for labels in support.values())
        winners = sorted(number for number, labels in support.items() if len(labels) == max_support)
        if max_support >= 2:
            if len(winners) == 1:
                fused_tower = f"N{winners[0]}"
                result_text = f"{fused_tower}附近"
            else:
                fused_tower = "-".join(f"N{number}" for number in winners)
                result_text = f"{fused_tower}区段"
            result.update(
                {
                    "status": "located",
                    "result_text": result_text,
                    "fused_tower": fused_tower,
                    "query_tower": fused_tower,
                    "confidence": 0.95 if max_support == 3 else 0.80,
                    "supporting_source_count": max_support,
                }
            )
            labels = "、".join(support[winners[0]])
            evidence.append(f"{labels}共同指向 {result_text}")
        else:
            lightning_entry = next(
                (entry for entry in available if entry["source"] == "lightning_location"), None
            )
            fallback = lightning_entry or available[0]
            result.update(
                {
                    "status": "needs_review",
                    "result_text": f"候选位置：{fallback['tower']}",
                    "fused_tower": fallback["tower"],
                    "query_tower": fallback["tower"],
                    "confidence": 0.50,
                    "supporting_source_count": 1,
                    "provisional": True,
                }
            )
            warnings.append("三路定位没有形成两源共识，暂以雷电定位（或唯一可用来源）作为候选")

    validation_issues = validation.get("issues", []) if isinstance(validation, Mapping) else []
    if any(item.get("code") == "event_time_mismatch" for item in validation_issues):
        if result["status"] == "located":
            result["status"] = "needs_review"
        result["provisional"] = True
        warnings.append("录波与雷电定位时刻不一致，综合位置仅作候选，不能自动确认同一事件")
    return result


def analyze_lightning_withstand(
    lightning: Mapping[str, Any],
    ledger_result: Mapping[str, Any],
    *,
    validation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """用实际雷电流依次比较反击和绕击耐雷水平，给出初步原因候选。"""
    query_result = str(lightning.get("query_result", "")).strip().upper()
    if query_result in {"否", "无", "不存在", "N", "NO", "FALSE"}:
        return {
            "status": "not_applicable",
            "conclusion": "未查询到同期落雷记录，不进行耐雷水平原因判别",
            "mechanism": "无同期落雷记录",
            "tower_analyses": [],
            "warnings": [],
            "provisional": False,
        }
    if not _has_value(lightning.get("current_ka")):
        return {
            "status": "unavailable",
            "conclusion": "缺少雷电流幅值，无法进行耐雷水平分析",
            "mechanism": "无法判定",
            "tower_analyses": [],
            "warnings": ["缺少雷电流幅值(kA)"],
            "provisional": False,
        }
    current_ka = abs(_to_float(lightning["current_ka"], "雷电流幅值"))
    records = ledger_result.get("records", []) if isinstance(ledger_result, Mapping) else []
    if not records:
        return {
            "status": "unavailable",
            "conclusion": "未匹配到故障位置杆塔台账，无法进行耐雷水平分析",
            "mechanism": "无法判定",
            "lightning_current_ka": current_ka,
            "tower_analyses": [],
            "warnings": [str(ledger_result.get("reason", "台账无匹配记录"))],
            "provisional": False,
        }

    tower_analyses: list[dict[str, Any]] = []
    mechanisms: list[str] = []
    for record in records:
        back = record.get("backflashover_withstand_ka")
        shielding = record.get("shielding_failure_withstand_ka")
        back_value = _to_float(back, "反击耐雷水平") if _has_value(back) else None
        shielding_value = _to_float(shielding, "绕击耐雷水平") if _has_value(shielding) else None
        if back_value is not None and current_ka >= back_value:
            mechanism = "反击候选"
            report_text = "雷电流幅值达到反击耐雷水平，接近反击"
            basis = f"雷电流 {current_ka:.3f} kA 已达到反击耐雷水平 {back_value:.3f} kA"
        elif shielding_value is not None and current_ka >= shielding_value:
            mechanism = "绕击候选"
            report_text = "雷电流幅值接近绕击"
            basis = f"雷电流 {current_ka:.3f} kA 未达到反击阈值，但已达到绕击耐雷水平 {shielding_value:.3f} kA"
        elif back_value is None and shielding_value is None:
            mechanism = "无法判定"
            report_text = "耐雷水平数据不足"
            basis = "杆塔台账缺少反击和绕击耐雷水平"
        else:
            mechanism = "未达到耐雷阈值"
            report_text = "雷电流幅值未达到绕击或反击耐雷水平"
            available_thresholds = [value for value in (back_value, shielding_value) if value is not None]
            basis = f"雷电流 {current_ka:.3f} kA 低于可用耐雷阈值最小值 {min(available_thresholds):.3f} kA"
        mechanisms.append(mechanism)
        tower_analyses.append(
            {
                "tower_no": record.get("tower_no"),
                "lightning_current_ka": current_ka,
                "backflashover_withstand_ka": back_value,
                "shielding_failure_withstand_ka": shielding_value,
                "current_to_backflash_ratio": round(current_ka / back_value, 6)
                if back_value and back_value > 0
                else None,
                "current_to_shielding_ratio": round(current_ka / shielding_value, 6)
                if shielding_value and shielding_value > 0
                else None,
                "mechanism": mechanism,
                "report_text": report_text,
                "basis": basis,
                "environment": {
                    "terrain": record.get("terrain"),
                    "elevation_m": record.get("elevation_m"),
                    "ground_flash_density": record.get("ground_flash_density"),
                    "ground_resistance_ohm": record.get("ground_resistance_ohm"),
                    "lightning_risk_level": record.get("lightning_risk_level"),
                },
            }
        )

    distinct = sorted(set(mechanisms))
    mechanism = distinct[0] if len(distinct) == 1 else "多杆塔结论不一致"
    report_text = (
        tower_analyses[0]["report_text"]
        if len(distinct) == 1
        else "不同候选杆塔的雷电流幅值比较结果不一致"
    )
    status = "analyzed" if len(distinct) == 1 and mechanism != "无法判定" else "needs_review"
    conclusion = (
        f"耐雷水平初判：{report_text}（|I|={current_ka:.3f} kA）"
        if mechanism != "多杆塔结论不一致"
        else f"候选杆塔的耐雷阈值结论不一致（|I|={current_ka:.3f} kA），需复核具体落点"
    )
    warnings: list[str] = ["本结论仅比较雷电流幅值与台账耐雷阈值，属于初步原因分析"]
    provisional = False
    validation_issues = validation.get("issues", []) if isinstance(validation, Mapping) else []
    if any(item.get("code") == "event_time_mismatch" for item in validation_issues):
        status = "needs_review"
        provisional = True
        warnings.append("录波与雷电定位时刻不一致，不能据此自动确认雷击为本次故障原因")
    return {
        "status": status,
        "conclusion": conclusion,
        "mechanism": mechanism,
        "report_text": report_text,
        "confidence": None,
        "confidence_available": False,
        "confidence_explanation": "雷电流与耐雷阈值的固定比较只能给出是否达到判据，不能据此计算概率或置信度",
        "lightning_current_ka": current_ka,
        "tower_analyses": tower_analyses,
        "warnings": warnings,
        "provisional": provisional,
    }


def load_traveling_wave_file(path: Path) -> dict[str, Any]:
    """读取分布式行波 TXT/JSON。"""
    text: str | None = None
    used_encoding = "utf-8-sig"
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = path.read_text(encoding=encoding)
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise InputError(f"无法解码行波文件: {path}")

    if path.suffix.lower() == ".json" or text.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"行波JSON格式错误: {path.name}") from exc

        def find_json_value(node: Any, aliases: set[str]) -> Any:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    if str(key).lower() in aliases:
                        return value
                for value in node.values():
                    found = find_json_value(value, aliases)
                    if found is not None:
                        return found
            elif isinstance(node, list):
                for value in node:
                    found = find_json_value(value, aliases)
                    if found is not None:
                        return found
            return None

        sample_aliases = {
            "wavedatas", "wavedata", "currentdatainput", "data", "values", "samples"
        }
        raw_samples = find_json_value(payload, sample_aliases)
        if isinstance(raw_samples, str):
            raw_samples = [token.strip() for token in raw_samples.split(",") if token.strip()]
        if isinstance(raw_samples, Mapping):
            raw_samples = next((value for value in raw_samples.values() if isinstance(value, list)), None)
        if not isinstance(raw_samples, list):
            raise InputError(f"行波JSON缺少采样数组: {path.name}")
        try:
            samples = [float(value) for value in raw_samples]
        except (TypeError, ValueError) as exc:
            raise InputError(f"行波JSON含非数值采样点: {path.name}") from exc
        if len(samples) < 32:
            raise InputError(f"行波文件采样点不足32个: {path.name}")
        phase_raw = find_json_value(payload, {"phase", "phasename", "channelname", "sltype"})
        phase_match = re.search(r"[ABC]", str(phase_raw or path.stem), flags=re.IGNORECASE)
        tower_match = re.search(r"(\d+\s*号杆塔)", path.stem)
        sample_rate_raw = find_json_value(
            payload,
            {"samplingrate", "samplerate", "samplefrequency", "smaplefrequency", "fs"},
        )
        sample_rate_hz = (
            _to_float(sample_rate_raw, "行波采样率") if _has_value(sample_rate_raw) else None
        )
        return {
            "path": str(path.resolve()),
            "file_name": path.name,
            "encoding": used_encoding,
            "phase": phase_match.group(0).upper() if phase_match else None,
            "device_tower": tower_match.group(1).replace(" ", "") if tower_match else None,
            "sample_rate_hz": sample_rate_hz,
            "head_time": find_json_value(payload, {"headtime", "starttime", "time"}),
            "voltage_level": find_json_value(payload, {"volevel", "voltagelevel"}),
            "left_distance_ohl_m": _clean_ledger_value(
                find_json_value(payload, {"leftdistohl", "leftdistanceohl"})
            ),
            "right_distance_ohl_m": _clean_ledger_value(
                find_json_value(payload, {"rightdistohl", "rightdistanceohl"})
            ),
            "samples": samples,
        }

    fields: dict[str, str] = {}
    for line in re.split(r"[\r\n]+", text.strip()):
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key.strip()] = value.strip()
    current_key = next(
        (key for key in fields if key.strip().lower() == "currentdatainput"), None
    )
    if current_key is None:
        match = re.search(r"CurrentDataInput\s*=\s*(.*)", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            raise InputError(f"行波文件缺少 CurrentDataInput: {path.name}")
        current_text = match.group(1).strip()
    else:
        current_text = fields[current_key]
    try:
        samples = [float(token.strip()) for token in current_text.split(",") if token.strip()]
    except ValueError as exc:
        raise InputError(f"行波文件含非数值采样点: {path.name}") from exc
    if len(samples) < 32:
        raise InputError(f"行波文件采样点不足32个: {path.name}")

    phase_match = re.search(r"([ABC])\s*相", path.stem, flags=re.IGNORECASE)
    tower_match = re.search(r"(\d+\s*号杆塔)", path.stem)
    normalized_fields = {key.lower(): value for key, value in fields.items()}
    sample_rate_raw = normalized_fields.get("samplefrequency") or normalized_fields.get(
        "smaplefrequency"
    )
    sample_rate_hz = _to_float(sample_rate_raw, "行波采样率") if _has_value(sample_rate_raw) else None
    return {
        "path": str(path.resolve()),
        "file_name": path.name,
        "encoding": used_encoding,
        "phase": phase_match.group(1).upper() if phase_match else None,
        "device_tower": tower_match.group(1).replace(" ", "") if tower_match else None,
        "sample_rate_hz": sample_rate_hz,
        "head_time": normalized_fields.get("headtime"),
        "voltage_level": normalized_fields.get("volevel"),
        "left_distance_ohl_m": _clean_ledger_value(normalized_fields.get("leftdistohl")),
        "right_distance_ohl_m": _clean_ledger_value(normalized_fields.get("rightdistohl")),
        "samples": samples,
    }


def load_wave_model_result(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    fields: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value):
            fields[key.strip()] = float(value)
        else:
            fields[key.strip()] = value
    return fields


def _phase_letters(value: Any) -> list[str]:
    """按出现顺序提取并去重 A/B/C 相别。"""
    phases: list[str] = []
    for phase in re.findall(r"[ABC]", str(value or "").upper()):
        if phase not in phases:
            phases.append(phase)
    return phases


def _correction_status_label(value: Any) -> str:
    text = str(value or "")
    labels = {
        "Corrected": "已修正",
        "ConfirmedWithSupplement": "复核确认",
        "ConflictUnresolved": "冲突未解决",
        "InsufficientThreePhaseData": "三相数据不足",
        "InvalidSupplement": "补充信息无效",
        "MissingFaultPhase": "缺少故障相",
        "NotRequested": "未请求复核",
        "ReturnedInformationConfirmed": "回传信息复核一致",
        "ReturnedInformationCorrected": "已根据回传信息修正",
        "DistortedWaveformNeedsReview": "波形畸变，需人工复核",
        "SubtypeUnresolved": "故障类型不能唯一确定",
        "SubtypeBoundaryNeedsReview": "普通绕击与雷击避雷线和导线型绕击边界待复核",
        "ModelOnly": "仅模型初判",
    }
    return labels.get(text, text or "未提供")


def _wave_subtype_label(value: Any) -> str:
    """将行波绕击亚型转成面向用户的明确表述。"""
    subtype = str(value or "").strip()
    labels = {
        "SF": "普通绕击（SF）",
        "FSF": "FSF型绕击（雷击多相导线）",
        "FBF": "FBF型绕击（雷击避雷线与导线）",
        "SF_FBF_REVIEW": "普通绕击与雷击避雷线和导线型绕击边界待复核（倾向后者）",
        "NotApplicable": "不适用",
        "NotEvaluated": "故障类型尚未确定",
        "Unresolved": "故障类型不能唯一确定",
        "SubtypeUnresolved": "故障类型不能唯一确定",
    }
    return labels.get(subtype, subtype or "故障类型尚未确定")


def build_ground_fault_user_summary(
    fault: Mapping[str, Any], decision: GroundDecision | Mapping[str, Any]
) -> dict[str, Any]:
    """生成面向用户的故障类型结论，不展示内部输入判据。"""
    phase = "".join(_phase_letters(fault.get("fault_phase"))) or "未知"
    if isinstance(decision, Mapping):
        fault_kind = str(decision.get("fault_kind", "无法判定"))
        is_ground_fault = decision.get("is_ground_fault")
    else:
        fault_kind = decision.fault_kind
        is_ground_fault = decision.is_ground_fault
    zero_sequence_change = (
        "显著增大"
        if is_ground_fault is True
        else "无明显变化"
        if is_ground_fault is False
        else "需进一步复核"
    )
    conclusion = f"{phase}相{fault_kind}" if phase != "未知" else fault_kind
    return {
        "fault_phase": phase,
        "fault_kind": fault_kind,
        "conclusion": conclusion,
        "observations": [
            f"{phase}相电流突增",
            f"{phase}相电压明显跌落",
            f"零序电流及零序电压{zero_sequence_change}",
        ],
    }


def evaluate_wave_review_trigger(
    fault: Mapping[str, Any],
    lightning_cause: Mapping[str, Any],
    initial_model_result: Mapping[str, Any],
) -> dict[str, Any]:
    """比较录波相别、行波相别和雷电流阈值结论，决定是否做已知相复核。"""
    recording_phases = _phase_letters(fault.get("fault_phase"))
    main_phases = _phase_letters(initial_model_result.get("MainPhase"))
    active_phases = _phase_letters(initial_model_result.get("ActivePhases")) or main_phases
    initial_label = str(initial_model_result.get("FinalLabel", "")).strip().upper()

    phase_comparable = bool(recording_phases and active_phases)
    phase_matches = set(recording_phases) == set(active_phases) if phase_comparable else None

    mechanism = str(lightning_cause.get("mechanism", ""))
    expected_label_map = {
        "反击候选": "F",
        "绕击候选": "R",
        "未达到耐雷阈值": "N",
    }
    expected_label = expected_label_map.get(mechanism)
    amplitude_comparable = bool(expected_label and initial_label in {"F", "R", "N"})
    amplitude_matches = initial_label == expected_label if amplitude_comparable else None

    reasons: list[str] = []
    if phase_matches is False:
        reasons.append(
            f"录波故障相 {''.join(recording_phases)} 与首次行波候补故障相 "
            f"{''.join(active_phases)} 不一致"
        )
    if amplitude_matches is False:
        current = lightning_cause.get("lightning_current_ka")
        current_text = f"（|I|={float(current):.3f} kA）" if _has_value(current) else ""
        reasons.append(
            f"雷电流耐雷阈值初判对应标签 {expected_label}{current_text}，"
            f"与首次行波标签 {initial_label} 不一致"
        )

    review_triggered = bool(recording_phases and reasons)
    return {
        "recording_fault_phase": "".join(recording_phases) or None,
        "initial_wave_main_phase": "".join(main_phases) or None,
        "initial_wave_active_phases": active_phases,
        "initial_wave_label": initial_label or None,
        "phase_comparable": phase_comparable,
        "phase_matches": phase_matches,
        "lightning_current_ka": lightning_cause.get("lightning_current_ka"),
        "lightning_amplitude_mechanism": mechanism or None,
        "amplitude_expected_wave_label": expected_label,
        "amplitude_comparable": amplitude_comparable,
        "amplitude_matches": amplitude_matches,
        "review_triggered": review_triggered,
        "supplied_fault_phase": "".join(recording_phases) if review_triggered else None,
        "trigger_reasons": reasons,
        "rule": (
            "录波故障相与首次行波候补故障相不一致，或雷电流耐雷阈值对应的F/R/N标签"
            "与首次行波标签不一致时，将录波故障相送入MATLAB做已知相复核"
        ),
    }


def _linear_detrend(values: Sequence[float]) -> list[float]:
    count = len(values)
    if count < 2:
        return [float(value) for value in values]
    x_mean = (count - 1) / 2.0
    y_mean = sum(values) / count
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    slope = (
        sum((index - x_mean) * (float(value) - y_mean) for index, value in enumerate(values))
        / denominator
        if denominator
        else 0.0
    )
    return [float(value) - (y_mean + slope * (index - x_mean)) for index, value in enumerate(values)]


def _spectral_band_ratios(
    values: Sequence[float],
    sample_rate_hz: float,
    *,
    low_upper_hz: float,
    high_lower_hz: float,
) -> dict[str, float]:
    """对短窗做直接DFT，避免额外依赖，并返回低/中/高频能量占比。"""
    detrended = _linear_detrend(values)
    count = len(detrended)
    if count < 8:
        return {"low": 0.0, "mid": 0.0, "high": 0.0}
    windowed = [
        value * (0.5 - 0.5 * math.cos(2.0 * math.pi * index / (count - 1)))
        for index, value in enumerate(detrended)
    ]
    energies = {"low": 0.0, "mid": 0.0, "high": 0.0}
    for bin_index in range(1, count // 2 + 1):
        real = 0.0
        imag = 0.0
        for sample_index, value in enumerate(windowed):
            angle = 2.0 * math.pi * bin_index * sample_index / count
            real += value * math.cos(angle)
            imag -= value * math.sin(angle)
        energy = real * real + imag * imag
        frequency = bin_index * sample_rate_hz / count
        band = "low" if frequency < low_upper_hz else "high" if frequency >= high_lower_hz else "mid"
        energies[band] += energy
    total = sum(energies.values())
    if total <= 0:
        return {"low": 0.0, "mid": 0.0, "high": 0.0}
    return {key: round(value / total, 6) for key, value in energies.items()}


def _analyze_wave_phase(
    record: Mapping[str, Any],
    *,
    default_sample_rate_hz: float,
    onset_ratio: float,
    tail_ratio: float,
    tail_limit_us: float,
    spectral_window_samples: int,
    low_upper_hz: float,
    high_lower_hz: float,
    reverse_window_us: float,
) -> dict[str, Any]:
    samples = [float(value) for value in record.get("samples", [])]
    sample_rate_hz = float(record.get("sample_rate_hz") or default_sample_rate_hz)
    baseline_count = max(20, len(samples) // 5)
    baseline_samples = samples[:baseline_count]
    baseline = statistics.median(baseline_samples)
    centered = [value - baseline for value in samples]
    noise_mad = statistics.median(abs(value) for value in centered[:baseline_count])
    peak_amplitude = max(abs(value) for value in centered)
    onset_threshold = max(peak_amplitude * onset_ratio, noise_mad * 8.0, 1e-12)
    onset_index = next(
        (index for index, value in enumerate(centered) if abs(value) >= onset_threshold), 0
    )
    peak_index = max(range(onset_index, len(centered)), key=lambda index: abs(centered[index]))
    peak_value = centered[peak_index]

    envelope: list[float] = []
    envelope_half_window = 2
    for index in range(len(centered)):
        start = max(0, index - envelope_half_window)
        stop = min(len(centered), index + envelope_half_window + 1)
        envelope.append(sum(abs(value) for value in centered[start:stop]) / (stop - start))
    tail_threshold = peak_amplitude * tail_ratio
    last_above = max(
        (index for index in range(peak_index, len(envelope)) if envelope[index] >= tail_threshold),
        default=peak_index,
    )
    tail_time_us = (last_above - peak_index) * 1_000_000.0 / sample_rate_hz
    tail_censored = last_above >= len(samples) - 3

    minimum_peak_spacing = max(3, int(round(sample_rate_hz * 5e-6)))
    peak_indices: list[int] = []
    local_threshold = peak_amplitude * 0.25
    absolute = [abs(value) for value in centered]
    for index in range(max(1, onset_index), len(absolute) - 1):
        if (
            absolute[index] >= local_threshold
            and absolute[index] >= absolute[index - 1]
            and absolute[index] > absolute[index + 1]
            and (not peak_indices or index - peak_indices[-1] >= minimum_peak_spacing)
        ):
            peak_indices.append(index)
    if tail_time_us >= tail_limit_us and len(peak_indices) >= 3:
        waveform_structure = "拖尾增强"
    elif len(peak_indices) <= 1:
        waveform_structure = "单峰"
    else:
        waveform_structure = "多峰"

    spectral_start = max(0, onset_index - 5)
    spectral_stop = min(len(centered), spectral_start + spectral_window_samples)
    spectral = _spectral_band_ratios(
        centered[spectral_start:spectral_stop],
        sample_rate_hz,
        low_upper_hz=low_upper_hz,
        high_lower_hz=high_lower_hz,
    )
    if spectral["high"] >= 0.35:
        frequency_character = "高频为主"
    elif spectral["mid"] + spectral["high"] >= 0.30:
        frequency_character = "中高频为主"
    else:
        frequency_character = "低频为主"

    primary_stop = min(len(centered), onset_index + max(3, int(sample_rate_hz * 20e-6)))
    primary_index = max(
        range(onset_index, primary_stop), key=lambda index: abs(centered[index])
    )
    primary_value = centered[primary_index]
    reverse_stop = min(
        len(centered), primary_index + max(3, int(sample_rate_hz * reverse_window_us * 1e-6))
    )
    opposite_peak = max(
        (
            abs(centered[index])
            for index in range(primary_index + 1, reverse_stop)
            if centered[index] * primary_value < 0
        ),
        default=0.0,
    )
    reverse_polarity = opposite_peak >= abs(primary_value) * 0.25

    return {
        "file_name": record.get("file_name"),
        "phase": record.get("phase"),
        "device_tower": record.get("device_tower"),
        "sample_count": len(samples),
        "sample_rate_hz": sample_rate_hz,
        "sample_rate_source": "文件头" if record.get("sample_rate_hz") else "默认假设",
        "head_time": record.get("head_time"),
        "baseline": round(baseline, 6),
        "noise_mad": round(noise_mad, 6),
        "peak_value": round(peak_value, 6),
        "peak_absolute": round(peak_amplitude, 6),
        "onset_index": onset_index,
        "onset_time_us": round(onset_index * 1_000_000.0 / sample_rate_hz, 6),
        "peak_index": peak_index,
        "tail_time_us": round(tail_time_us, 6),
        "tail_time_censored_by_record_end": tail_censored,
        "peak_count": len(peak_indices),
        "waveform_structure": waveform_structure,
        "spectral_energy_ratio": spectral,
        "frequency_character": frequency_character,
        "reverse_polarity_pulse": reverse_polarity,
        "reverse_polarity_text": "存在反极性脉冲" if reverse_polarity else "无反极性脉冲",
    }


def analyze_traveling_waves(
    records: Sequence[Mapping[str, Any]],
    fault: Mapping[str, Any],
    *,
    settings: Mapping[str, Any] | None = None,
    model_result: Mapping[str, Any] | None = None,
    review_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """提取三相行波特征，并按Word模板输出雷击/非雷击及绕击/反击候选。"""
    settings = settings or {}
    default_sample_rate_hz = float(settings.get("traveling_wave_sample_rate_hz", 1_000_000.0))
    tail_limit_us = float(settings.get("traveling_wave_tail_limit_us", 20.0))
    phase_results = [
        _analyze_wave_phase(
            record,
            default_sample_rate_hz=default_sample_rate_hz,
            onset_ratio=float(settings.get("traveling_wave_onset_ratio", 0.10)),
            tail_ratio=float(settings.get("traveling_wave_tail_ratio", 0.10)),
            tail_limit_us=tail_limit_us,
            spectral_window_samples=int(settings.get("traveling_wave_spectral_window_samples", 128)),
            low_upper_hz=float(settings.get("traveling_wave_low_upper_hz", 50_000.0)),
            high_lower_hz=float(settings.get("traveling_wave_high_lower_hz", 200_000.0)),
            reverse_window_us=float(settings.get("traveling_wave_reverse_window_us", 80.0)),
        )
        for record in records
    ]
    if not phase_results:
        return {
            "status": "unavailable",
            "classification": "未提供行波数据",
            "mechanism": "无法判定",
            "confidence": 0.0,
            "phase_analyses": [],
            "warnings": ["inputs中未发现包含CurrentDataInput的行波TXT"],
            "provisional": False,
        }

    maximum_peak = max(item["peak_absolute"] for item in phase_results)
    multi_phase_ratio = float(settings.get("traveling_wave_multi_phase_ratio", 0.80))
    active = [
        item for item in phase_results if item["peak_absolute"] >= maximum_peak * multi_phase_ratio
    ]
    long_tail_count = sum(item["tail_time_us"] >= tail_limit_us for item in active)
    low_frequency_count = sum(item["frequency_character"] == "低频为主" for item in active)
    impulsive_frequency_count = len(active) - low_frequency_count
    reverse_count = sum(bool(item["reverse_polarity_pulse"]) for item in active)
    onset_spread_us = (
        max(item["onset_time_us"] for item in active) - min(item["onset_time_us"] for item in active)
        if active
        else None
    )
    majority = max(1, (len(active) + 1) // 2)
    evidence: list[str] = [
        f"{len(active)}相出现显著行波脉冲",
        f"{long_tail_count}/{len(active)}相波尾时间≥{tail_limit_us:.1f} μs",
        f"{low_frequency_count}/{len(active)}相以低频为主",
    ]
    if onset_spread_us is not None:
        evidence.append(f"有效相首波检测时刻最大差值为 {onset_spread_us:.3f} μs")

    if long_tail_count >= majority and low_frequency_count >= majority:
        classification = "非雷击故障候选"
        mechanism = "非雷击"
        confidence = min(0.85, 0.65 + 0.05 * (long_tail_count / len(active)) + 0.10 * (low_frequency_count / len(active)))
    elif long_tail_count < majority and impulsive_frequency_count >= majority:
        classification = "雷击故障候选"
        if reverse_count >= majority:
            mechanism = "反击候选"
            evidence.append("多数显著相在主波前后出现反极性脉冲，偏向反击")
        else:
            mechanism = "绕击候选"
            evidence.append("多数显著相无反极性脉冲且中高频成分显著，偏向绕击")
        confidence = 0.75
    else:
        classification = "雷击属性不确定"
        mechanism = "无法判定"
        confidence = 0.45
        evidence.append("波尾与频谱特征未形成一致判据")

    heuristic_classification = classification
    heuristic_mechanism = mechanism
    heuristic_confidence = confidence
    heuristic_evidence = list(evidence)
    model_summary: dict[str, Any] = {}
    model_result = model_result or {}
    module_mode = bool(model_result.get("ModuleFinalLabel"))
    final_label = str(
        model_result.get("ModuleFinalLabel") or model_result.get("FinalLabel", "")
    ).upper()
    initial_label = str(
        model_result.get("ModuleInitialLabel")
        or model_result.get("InitialFinalLabel")
        or final_label
    ).upper()
    model_active_phases = model_result.get("ModuleInitialActivePhases") or model_result.get("ActivePhases")
    model_final_phase = model_result.get("ModuleFinalFaultPhase") or model_result.get("CorrectedFaultPhase")
    model_final_subtype = str(
        model_result.get("ModuleFinalSubtype") or model_result.get("FinalSubtype", "")
    )
    correction_status = str(
        model_result.get("ModuleCorrectionStatus") or model_result.get("CorrectionStatus", "")
    )
    review_confirmed = (
        module_mode
        and correction_status == "ReturnedInformationConfirmed"
        and final_label == initial_label
    )
    review_basis = (
        "相别与幅值" if bool(model_result.get("ModuleHasAmplitudeInformation", 0)) else "相别"
    )
    correction_applied = (
        correction_status == "ReturnedInformationCorrected"
        or (not module_mode and bool(model_result.get("CorrectionApplied", 0)))
        or (module_mode and final_label != initial_label)
    )
    label_map = {
        "N": ("非雷击故障", "非雷击"),
        "F": ("雷击反击故障", "反击候选"),
        "R": ("雷击绕击故障", "绕击候选"),
    }
    if final_label in label_map:
        # MATLAB模型可用时，面向用户的“行波判据”只展示模型与复核证据。
        # 内置长拖尾/频谱阈值仅作备用诊断，保留在 heuristic_result 中。
        evidence = []
        classification, mechanism = label_map[final_label]
        ln_lightning = float(model_result.get("LNLightningScore", 0.0) or 0.0)
        ln_non_lightning = float(model_result.get("LNNonLightningScore", 0.0) or 0.0)
        fr_probabilities = _normalize_binary_scores(
            model_result.get("FRFScore"), model_result.get("FRRScore")
        )
        if module_mode and review_confirmed:
            confidence = ln_non_lightning if initial_label == "N" else ln_lightning
            confidence_available = True
            confidence_kind = "initial_model_score_confirmed_by_review"
            confidence_explanation = (
                f"初判与录波{review_basis}复核一致，最终保留初判；"
                "数值取初始雷击/非雷击模型得分，不代表绕击亚型的概率"
            )
        elif correction_applied or (module_mode and correction_status not in {"", "ModelOnly"}):
            confidence = None
            confidence_available = False
            confidence_kind = "fixed_rule_no_probability"
            confidence_explanation = (
                "最终R/FBF/FSF由录波故障相条件下的固定判据修正得到；固定判据没有经过概率校准，"
                "因此不计算修正置信度"
            )
        else:
            if final_label == "N":
                confidence = ln_non_lightning
            elif final_label == "F":
                confidence = ln_lightning * fr_probabilities[0] if fr_probabilities else None
            else:
                confidence = ln_lightning * fr_probabilities[1] if fr_probabilities else None
            confidence_available = confidence is not None
            confidence_kind = "engineering_normalized_probability_not_calibrated"
            confidence_explanation = (
                "雷击/非雷击使用逻辑回归概率；反击/绕击使用支持向量机判别值的Softmax归一化结果。"
                "该数值用于工程展示，未经过独立概率校准，不作为统计置信度使用"
            )
        model_summary = {
            "final_label": final_label,
            "initial_final_label": initial_label,
            "meaning": model_result.get("Meaning") or label_map[final_label][0],
            "main_phase": model_result.get("MainPhase"),
            "active_phases": model_active_phases,
            "is_multi_phase": model_result.get("IsMultiPhase"),
            "ln_prediction": model_result.get("LNPrediction"),
            "ln_lightning_score": ln_lightning,
            "ln_non_lightning_score": ln_non_lightning,
            "fr_prediction": model_result.get("FRPrediction"),
            "fr_backflash_score": model_result.get("FRFScore"),
            "fr_shielding_score": model_result.get("FRRScore"),
            "fr_backflash_probability": fr_probabilities[0] if fr_probabilities else None,
            "fr_shielding_probability": fr_probabilities[1] if fr_probabilities else None,
            "correction_requested": bool(model_result.get("CorrectionRequested", 0)) or module_mode,
            "correction_status": correction_status,
            "correction_applied": correction_applied,
            "supplied_fault_phase": model_result.get("ModuleSupplementalFaultPhase") or model_result.get("SuppliedFaultPhase"),
            "corrected_fault_phase": model_final_phase,
            "final_subtype": model_final_subtype,
            "final_subtype_description": _wave_subtype_label(model_final_subtype),
            "correction_reason": model_result.get("ModuleCorrectionReason") or model_result.get("CorrectionReason"),
            "review_confirmed": review_confirmed,
            "amplitude_information_used": bool(model_result.get("ModuleHasAmplitudeInformation", 0)),
            "amplitude_band": model_result.get("ModuleAmplitudeBand"),
            "phase_consistency": model_result.get("ModulePhaseConsistency"),
            "waveform_phase_trusted": bool(model_result.get("ModuleWaveformPhaseTrusted", 0)),
            "candidate_types": model_result.get("ModuleCandidateTypes"),
            "waveform_hypothesis": model_result.get("ModuleWaveformHypothesis"),
            "hypothesis_source": model_result.get("ModuleHypothesisSource"),
            "subtype_source": model_result.get("ModuleSubtypeSource"),
        }
        correction_requested = bool(model_result.get("CorrectionRequested", 0)) or module_mode
        if review_confirmed:
            evidence.append(
                f"MATLAB初判 {initial_label} 与录波{review_basis}复核一致，"
                f"最终采用初判 {initial_label}"
            )
        elif correction_applied:
            evidence.append(
                f"MATLAB首次模型输出 {initial_label}，经录波故障相固定判据复核后修正为 "
                f"{final_label}/{model_final_subtype}，作为最终行波结论"
            )
        elif correction_requested:
            evidence.append(
                f"MATLAB首次模型输出 {initial_label}；录波故障相复核状态为"
                f"{_correction_status_label(correction_status)}，"
                f"未形成修正，暂保留 {final_label} 并建议人工复核"
            )
        else:
            evidence.append(
                f"MATLAB训练模型输出 {final_label}（{model_result.get('Meaning', '')}），作为行波主结论"
            )
    else:
        confidence = None
        confidence_available = False
        confidence_kind = "fixed_rule_no_probability"
        confidence_explanation = "内置行波工程阈值只形成候选结论，没有概率校准，故不计算置信度"

    initial_text = label_map.get(initial_label, ("无法判定", "无法判定"))[0]
    recording_phase = "".join(_phase_letters(fault.get("fault_phase"))) or "未知"
    active_phase = str(model_active_phases or "未知")
    corrected_phase = str(model_final_phase or fault.get("fault_phase") or "")
    final_subtype = model_final_subtype
    subtype_description = _wave_subtype_label(final_subtype)
    correction_requested = bool(model_result.get("CorrectionRequested", 0)) or module_mode
    if review_confirmed:
        subtype_text = (
            f"/{final_subtype}"
            if final_subtype and final_subtype not in {"NotEvaluated", "NotApplicable"}
            else ""
        )
        if final_label == "R" and final_subtype == "FSF":
            final_detail = f"{subtype_description}，可能是雷电绕击{corrected_phase}两相导线故障"
        elif final_label == "R":
            final_detail = subtype_description
        else:
            final_detail = label_map.get(final_label, (classification, mechanism))[0]
        score_text = f"{confidence:.2%}" if confidence is not None else "未提供"
        report_conclusion = (
            f"录波故障相{recording_phase}；行波初判为{initial_text}（{initial_label}{subtype_text}），"
            f"{review_basis}复核一致，最终采用初判；"
            f"雷击/非雷击层级模型置信度{score_text}"
        )
    elif correction_applied and final_label == "R" and final_subtype == "FSF":
        final_detail = f"{subtype_description}，可能是雷电绕击{corrected_phase}两相导线故障"
        report_conclusion = (
            f"首次判别为{initial_text}（{initial_label}）；回传录波{corrected_phase}相复核后"
            f"修正为绕击（R/FSF），可能是雷电绕击{corrected_phase}两相导线故障"
        )
    elif correction_applied:
        subtype_text = (
            f"/{final_subtype}"
            if final_subtype and final_subtype not in {"NotEvaluated", "NotApplicable"}
            else ""
        )
        final_detail = subtype_description if final_label == "R" else label_map.get(final_label, (classification, mechanism))[0]
        report_conclusion = (
            f"首次判别为{initial_text}（{initial_label}）；录波相别复核后修正为"
            f"{final_detail}（{final_label}{subtype_text}）"
        )
    elif correction_status == "SubtypeBoundaryNeedsReview" and final_label == "R":
        final_detail = "普通绕击与雷击避雷线和导线型绕击边界待复核，行波特征倾向后者"
        report_conclusion = (
            f"录波故障相{recording_phase}；行波初判为雷击绕击故障，"
            "三相行波第二强相与主相幅值比处于普通绕击和雷击避雷线与导线型绕击的边界区间，"
            "且主峰后存在多峰活动，特征倾向雷击避雷线与导线型绕击，建议人工复核"
        )
    elif correction_status == "SubtypeUnresolved" and final_label == "R":
        final_detail = "现有行波特征未能形成唯一判据，故障类型不能唯一确定"
        report_conclusion = (
            f"录波故障相{recording_phase}；行波初判为雷击绕击故障（R），"
            "复核后仍支持雷电绕击，但相间幅值比例、极性关系、高频能量和波尾特征"
            "未能满足某一故障类型的唯一判据，建议人工复核"
        )
    elif correction_status == "DistortedWaveformNeedsReview":
        final_detail = f"{mechanism}候选；行波波形畸变，故障类型暂不确定"
        report_conclusion = (
            f"录波故障相{recording_phase}；行波初判为{initial_text}（{initial_label}），"
            "但波形畸变，最终结论需人工复核"
        )
    elif correction_requested and correction_status not in {"", "NotRequested", "ConfirmedWithSupplement"}:
        subtype_text = subtype_description if final_label == "R" else mechanism
        final_detail = f"{subtype_text}；录波故障相{recording_phase}与行波候补故障相{active_phase}尚未一致，需复核"
        report_conclusion = (
            f"录波故障相{recording_phase}；首次行波判别为{initial_text}（{initial_label}），"
            f"行波候补故障相为{active_phase}；回传{recording_phase}相复核后未形成修正，"
            f"暂保留{classification}（{final_label}），建议人工复核相别"
        )
    else:
        final_detail = (
            f"{subtype_description}（故障相{recording_phase}）"
            if final_label == "R"
            else f"{classification}（故障相{recording_phase}）"
        )
        report_conclusion = (
            f"故障相{recording_phase}；行波判别为{classification}（{final_label}），"
            f"行波候补故障相为{active_phase}"
            if final_label
            else f"故障相{recording_phase}；{classification}"
        )

    warnings: list[str] = [
        "行波阈值为可配置的工程初值，需结合本线路历史样本进一步标定"
    ]
    provisional = False
    missing_rates = [item["file_name"] for item in phase_results if item["sample_rate_source"] == "默认假设"]
    if missing_rates:
        warnings.append(f"{len(missing_rates)}个文件缺少SampleFrequency，暂按{default_sample_rate_hz:g} Hz计算")
    if not any(item.get("head_time") for item in phase_results):
        provisional = True
        warnings.append("行波文件缺少HeadTime，无法核对其是否对应本次录波故障时刻")
    phases = {item.get("phase") for item in phase_results if item.get("phase")}
    if phases != {"A", "B", "C"}:
        provisional = True
        warnings.append(f"三相文件不完整，当前识别相别：{sorted(phases)}")
    review_context = review_context or {}
    if review_context.get("review_triggered"):
        review_status = correction_status
        if not review_context.get("review_succeeded"):
            provisional = True
            warnings.append("已触发行波已知相复核，但MATLAB二次复核未成功完成")
        elif review_status in {
            "ConflictUnresolved",
            "InvalidSupplement",
            "MissingFaultPhase",
            "InsufficientThreePhaseData",
            "DistortedWaveformNeedsReview",
            "SubtypeUnresolved",
        }:
            provisional = True
            warnings.append(
                f"已回传录波故障相，但MATLAB复核状态为"
                f"{_correction_status_label(review_status)}，需人工复核"
            )

    return {
        "status": "needs_review" if provisional else "analyzed",
        "classification": classification,
        "mechanism": mechanism,
        "initial_classification": initial_text,
        "recording_fault_phase": recording_phase,
        "wave_active_phases": active_phase,
        "final_detail": final_detail,
        "report_conclusion": report_conclusion,
        "confidence": round(confidence, 6) if confidence is not None else None,
        "confidence_available": confidence_available,
        "confidence_kind": confidence_kind,
        "confidence_explanation": confidence_explanation,
        "analysis_method": (
            "MATLAB新版行波模块+录波故障相+雷电流幅值复核+可解释特征"
            if module_mode
            else "MATLAB首次模型+录波故障相固定判据复核+可解释特征"
            if model_summary.get("correction_applied")
            else "MATLAB训练模型+可解释特征"
            if model_summary
            else "可解释工程阈值"
        ),
        "model_result": model_summary,
        "fault_phase_review": _json_safe(review_context),
        "heuristic_result": {
            "classification": heuristic_classification,
            "mechanism": heuristic_mechanism,
            "confidence": round(heuristic_confidence, 6),
            "evidence": heuristic_evidence,
        },
        "active_phases": [item.get("phase") for item in active],
        "three_phase_character": "多相脉冲" if len(active) >= 2 else "单相脉冲",
        "onset_spread_us": round(onset_spread_us, 6) if onset_spread_us is not None else None,
        "phase_analyses": phase_results,
        "evidence": evidence,
        "warnings": warnings,
        "provisional": provisional,
        "settings": {
            "default_sample_rate_hz": default_sample_rate_hz,
            "tail_time_threshold_us": tail_limit_us,
            "low_frequency_upper_hz": float(settings.get("traveling_wave_low_upper_hz", 50_000.0)),
            "high_frequency_lower_hz": float(settings.get("traveling_wave_high_lower_hz", 200_000.0)),
            "active_phase_peak_ratio": multi_phase_ratio,
        },
    }


def fuse_cause_analyses(
    ledger_analysis: Mapping[str, Any],
    wave_analysis: Mapping[str, Any],
    optical: Mapping[str, Any],
    *,
    conflict_discount: float = 0.80,
) -> dict[str, Any]:
    """按光学>行波>台账的优先级融合结论；固定判据不伪造概率。"""
    if not 0.0 <= conflict_discount <= 1.0:
        raise InputError("cause_fusion_conflict_discount 必须在0到1之间")
    sources: list[dict[str, Any]] = []
    ledger_mechanism = str(ledger_analysis.get("mechanism", ""))
    if ledger_mechanism in {"绕击候选", "反击候选"}:
        sources.append(
            {
                "source": "线路台账耐雷水平",
                "mechanism": ledger_mechanism.replace("候选", ""),
                "confidence": None,
                "evidence_type": "固定阈值判据",
                "quantitative_basis": ledger_analysis.get("conclusion"),
                "confidence_explanation": "雷电流达到耐雷阈值不等同于具有某一概率",
                "priority": 1,
            }
        )
    wave_mechanism = str(wave_analysis.get("mechanism", ""))
    if wave_mechanism not in {"", "无法判定"}:
        sources.append(
            {
                "source": "分布式行波",
                "mechanism": wave_mechanism.replace("候选", ""),
                "confidence": None,
                "evidence_type": (
                    "固定相别复核判据"
                    if wave_analysis.get("model_result", {}).get("correction_applied")
                    else "模型判别结果"
                ),
                "quantitative_basis": wave_analysis.get("report_conclusion"),
                "confidence_explanation": wave_analysis.get("confidence_explanation"),
                "priority": 2,
            }
        )
    optical_mechanism = optical.get("mechanism") or optical.get("result") or optical.get("conclusion")
    if _has_value(optical_mechanism):
        optical_text = str(optical_mechanism)
        # “无明显落雷记录/未监测到”等描述只表示光学设备没有形成明确证据，
        # 不能作为一种故障机制，更不能覆盖已一致的行波与耐雷水平结论。
        normalized_optical = next(
            (label for label in ("绕击", "反击", "非雷击") if label in optical_text),
            None,
        )
        if normalized_optical:
            sources.append(
                {
                    "source": "光学监测",
                    "mechanism": normalized_optical,
                    "confidence": float(optical["confidence"]) if _has_value(optical.get("confidence")) else None,
                    "evidence_type": "光学监测明确结论",
                    "quantitative_basis": optical_text,
                    "confidence_explanation": (
                        "采用光学监测输入中明确提供的置信度"
                        if _has_value(optical.get("confidence"))
                        else "光学输入未提供可验证的概率"
                    ),
                    "priority": 3,
                }
            )
    if not sources:
        return {
            "status": "unavailable",
            "final_mechanism": "无法判定",
            "final_detail": "无法判定",
            "confidence": None,
            "confidence_available": False,
            "consistency": "无可用原因来源",
            "sources": [],
            "warnings": [],
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        groups.setdefault(source["mechanism"], []).append(source)
    if len(sources) == 1:
        final_mechanism = sources[0]["mechanism"]
        consistency = "仅有一个可用来源，无法交叉验证"
        status = "needs_review"
        warnings = ["当前只有一个可用原因来源，融合结论仅作候选"]
    elif len(groups) == 1:
        final_mechanism = next(iter(groups))
        consistency = "可用来源结论一致"
        status = "fused"
        warnings: list[str] = []
    else:
        selected = max(sources, key=lambda source: source["priority"])
        final_mechanism = selected["mechanism"]
        consistency = "来源结论冲突"
        status = "needs_review"
        warnings = [
            f"原因来源存在冲突，按光学监测>行波分析>台账的优先级暂选“{final_mechanism}”"
        ]
    wave_model = wave_analysis.get("model_result", {})
    if wave_model.get("correction_status") == "SubtypeBoundaryNeedsReview" and final_mechanism == "绕击":
        phase = wave_model.get("corrected_fault_phase") or wave_model.get("supplied_fault_phase") or ""
        conductor = f"{phase}相导线" if phase else "相关导线"
        final_detail = (
            f"可能是雷电绕击{conductor}故障；故障类型处于普通绕击与雷击避雷线和导线型绕击边界，"
            "行波特征倾向后者，建议人工复核"
        )
        status = "needs_review"
        warnings.append("普通绕击与雷击避雷线和导线型绕击的边界判别尚需人工复核")
    elif wave_model.get("correction_status") == "SubtypeUnresolved" and final_mechanism == "绕击":
        final_detail = "现有行波特征未能形成唯一判据，故障类型不能唯一确定，建议人工复核"
    elif wave_model.get("correction_status") in {"ConflictUnresolved", "DistortedWaveformNeedsReview"}:
        recording_phase = wave_analysis.get("recording_fault_phase") or "未知"
        active_phase = wave_model.get("active_phases") or "未知"
        mechanism_detail = (
            _wave_subtype_label(wave_model.get("final_subtype"))
            if final_mechanism == "绕击"
            else f"{final_mechanism}候选"
        )
        final_detail = (
            f"{mechanism_detail}；录波故障相{recording_phase}与行波候补故障相{active_phase}尚未形成一致结论，"
            "建议人工复核"
        )
    elif final_mechanism == "绕击" and wave_model.get("final_subtype") == "FSF":
        phase = wave_model.get("corrected_fault_phase") or wave_model.get("supplied_fault_phase") or ""
        final_detail = f"{_wave_subtype_label('FSF')}，可能是雷电绕击{phase}两相导线故障"
    elif final_mechanism == "绕击":
        final_detail = _wave_subtype_label(wave_model.get("final_subtype"))
    else:
        final_detail = final_mechanism
    confidence = None
    confidence_calculation = {
        "method": "not_calculated",
        "formula": None,
        "result": None,
        "explanation": (
            "本次融合包含耐雷阈值或录波相别固定判据；这些判据未经概率校准，"
            "不能用固定权重合成为统计置信度，因此不输出百分比"
        ),
    }
    if any(bool(item.get("provisional")) for item in (ledger_analysis, wave_analysis)):
        status = "needs_review"
        warnings.append("至少一个来源缺少事件关联信息，融合结论仅作候选")
    return {
        "status": status,
        "final_mechanism": final_mechanism,
        "final_detail": final_detail,
        "confidence": confidence,
        "confidence_available": False,
        "consistency": consistency,
        "sources": sources,
        "confidence_calculation": confidence_calculation,
        "warnings": warnings,
    }


def build_overall_recommendation(
    validation: Mapping[str, Any],
    ledger_result: Mapping[str, Any],
    location_analysis: Mapping[str, Any],
    lightning_cause: Mapping[str, Any],
    wave_analysis: Mapping[str, Any],
    cause_fusion: Mapping[str, Any],
    ground_decision: GroundDecision,
    resistance: ResistanceResult,
) -> dict[str, Any]:
    """汇总自动判别是否可直接通过，并给出简洁的后续意见。"""
    reasons: list[str] = []

    def add_reason(text: Any) -> None:
        value = str(text or "").strip()
        if value and value not in reasons:
            reasons.append(value)

    for issue in validation.get("issues", []):
        if issue.get("severity") in {"error", "warning"}:
            add_reason(issue.get("message"))

    if not ledger_result.get("matched"):
        add_reason(ledger_result.get("diagnostic") or ledger_result.get("reason") or "线路台账未匹配")

    model_result = wave_analysis.get("model_result", {})
    if model_result.get("correction_status") in {
        "ConflictUnresolved",
        "SubtypeUnresolved",
        "SubtypeBoundaryNeedsReview",
        "DistortedWaveformNeedsReview",
        "InvalidSupplement",
        "MissingFaultPhase",
        "InsufficientThreePhaseData",
    }:
        recording_phase = wave_analysis.get("fault_phase_review", {}).get("recording_fault_phase")
        active_phase = model_result.get("active_phases")
        add_reason(
            f"录波故障相{recording_phase or '未知'}与行波候补故障相{active_phase or '未知'}尚未形成一致结论"
        )
    for warning in wave_analysis.get("warnings", []):
        if "HeadTime" in str(warning) or "三相文件不完整" in str(warning):
            add_reason(warning)

    if (
        ground_decision.is_ground_fault is True
        and ground_decision.fault_kind.startswith("单相")
        and resistance.status != "ok"
    ):
        add_reason("接地故障的过渡电阻计算信息不足")
    if location_analysis.get("status") == "unavailable":
        add_reason("综合故障位置无法确定")
    if lightning_cause.get("status") == "unavailable" and ledger_result.get("matched"):
        add_reason(lightning_cause.get("conclusion"))
    if cause_fusion.get("status") == "needs_review" and not reasons:
        add_reason("多源故障原因结论仍需人工确认")

    can_auto_pass = not reasons
    return {
        "decision": "建议通过" if can_auto_pass else "建议人工复核",
        "can_auto_pass": can_auto_pass,
        "summary": (
            "关键输入和多源结论一致，可进入后续报告流程"
            if can_auto_pass
            else "存在输入不一致、台账缺失或相别复核未决项，暂不建议直接通过"
        ),
        "reasons": reasons,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(v) for v in value]
    return value


def _parse_datetime_value(value: Any) -> datetime | None:
    if not _has_value(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip().replace("/", "-")
    text = re.sub(r"(?<=\d):(\d{3,6})$", r".\1", text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def validate_input_consistency(
    fault: Mapping[str, Any],
    lightning: Mapping[str, Any],
    optical: Mapping[str, Any],
    *,
    time_tolerance_seconds: float = 30.0,
) -> dict[str, Any]:
    """检查三类输入能否安全视为同一故障事件。"""
    issues: list[dict[str, str]] = []
    metrics: dict[str, Any] = {"time_tolerance_seconds": time_tolerance_seconds}

    station = str(fault.get("station", "")).strip()
    if not station or station.lower() in {"default station", "unknown", "未知"}:
        issues.append(
            {
                "severity": "warning",
                "code": "fault_station_placeholder",
                "message": "录波记录厂站为空或仍为占位值",
            }
        )
    if not _has_value(fault.get("line_name")):
        issues.append(
            {
                "severity": "warning",
                "code": "fault_line_missing",
                "message": "录波表缺少故障线路名称；台账查询暂用雷电定位表中的线路名称",
            }
        )
    fault_line = fault.get("line_name")
    lightning_line = lightning.get("line_name")
    if (
        _has_value(fault_line)
        and _has_value(lightning_line)
        and _normalize_line_name(fault_line) != _normalize_line_name(lightning_line)
    ):
        issues.append(
            {
                "severity": "error",
                "code": "line_name_mismatch",
                "message": (
                    f"录波线路“{fault_line}”与雷电定位线路“{lightning_line}”不一致，"
                    "不能自动视为同一线路事件"
                ),
            }
        )
        metrics["fault_line_name"] = str(fault_line)
        metrics["lightning_line_name"] = str(lightning_line)

    fault_time = _parse_datetime_value(fault.get("fault_time"))
    lightning_fault_time = _parse_datetime_value(lightning.get("fault_time"))
    if fault_time and lightning_fault_time:
        delta_seconds = abs((fault_time - lightning_fault_time).total_seconds())
        metrics["fault_vs_lightning_time_difference_seconds"] = delta_seconds
        if delta_seconds > time_tolerance_seconds:
            issues.append(
                {
                    "severity": "error",
                    "code": "event_time_mismatch",
                    "message": (
                        f"录波故障时刻 {fault_time.isoformat(sep=' ')} 与雷电定位表故障时刻 "
                        f"{lightning_fault_time.isoformat(sep=' ')} 相差 {delta_seconds:.3f} 秒，"
                        "不能自动视为同一事件"
                    ),
                }
            )

    query_result = str(lightning.get("query_result", "")).strip()
    if query_result in {"是", "有", "存在", "Y", "YES", "True", "true"}:
        for key, label in (
            ("location_time", "雷电定位时刻"),
            ("current_ka", "雷电流幅值"),
            ("nearest_tower", "雷电定位最近杆塔"),
        ):
            if not _has_value(lightning.get(key)):
                issues.append(
                    {
                        "severity": "error",
                        "code": f"lightning_{key}_missing",
                        "message": f"存在落雷记录，但缺少{label}",
                    }
                )

    if not optical:
        issues.append(
            {
                "severity": "info",
                "code": "optical_input_missing",
                "message": "本次 inputs 未提供光学监测结果；不影响当前计算，但雷击原因融合尚缺光学来源",
            }
        )

    if any(item["severity"] == "error" for item in issues):
        status = "needs_review"
    elif any(item["severity"] == "warning" for item in issues):
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "issues": issues, "metrics": metrics}


def build_diagnosis(
    fault_raw: Mapping[str, Any],
    manual: Mapping[str, Any],
    ledger_rows: Sequence[Mapping[str, Any]],
    *,
    lightning_raw: Mapping[str, Any] | None = None,
    traveling_wave_records: Sequence[Mapping[str, Any]] | None = None,
    wave_model_result: Mapping[str, Any] | None = None,
    wave_review_context: Mapping[str, Any] | None = None,
    source_paths: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fault = canonicalize_fault_fields(fault_raw)
    overrides = manual.get("fault_overrides", {})
    if isinstance(overrides, Mapping):
        fault.update(canonicalize_fault_fields(overrides))

    settings = manual.get("calculation", {})
    if not isinstance(settings, Mapping):
        raise InputError("calculation 必须是 JSON 对象")
    default_voltage_unit = str(settings.get("default_voltage_unit", "kV"))
    default_current_unit = str(settings.get("default_current_unit", "kA"))
    zero_representation = str(settings.get("zero_sequence_representation", "3I0"))

    decision = decide_ground_fault(
        fault,
        default_current_unit=default_current_unit,
        zero_sequence_ratio_threshold=float(settings.get("ground_zero_sequence_ratio_threshold", 0.10)),
        zero_sequence_absolute_threshold_a=float(
            settings.get("ground_zero_sequence_absolute_threshold_a", 100.0)
        ),
    )
    resistance = calculate_transition_resistance(
        fault,
        decision,
        default_voltage_unit=default_voltage_unit,
        default_current_unit=default_current_unit,
        zero_sequence_representation=zero_representation,
    )

    # 保留旧 JSON 字段的兼容性，但雷电定位 Excel 是当前主输入，且优先级更高。
    lightning = manual.get("lightning", {})
    optical = manual.get("optical", {})
    location = manual.get("location", {})
    if not isinstance(lightning, Mapping) or not isinstance(optical, Mapping) or not isinstance(location, Mapping):
        raise InputError("lightning、optical、location 必须是 JSON 对象")
    lightning = dict(lightning)
    if lightning_raw:
        lightning.update(canonicalize_lightning_fields(lightning_raw))
    location = dict(location)
    for key in (
        "line_side_distances_km",
        "recording_distance_km",
        "recording_nearest_tower",
        "traveling_wave_distance_km",
        "traveling_wave_nearest_tower",
    ):
        if _has_value(lightning.get(key)):
            location[key] = lightning[key]

    validation = validate_input_consistency(fault, lightning, optical)
    location_analysis = fuse_fault_location(lightning, validation=validation)
    tower_for_ledger = (
        manual.get("ledger_tower")
        or location_analysis.get("query_tower")
        or lightning.get("nearest_tower")
        or location.get("nearest_tower")
        or optical.get("device_tower")
    )
    ledger_result = lookup_ledger(
        ledger_rows,
        fault.get("line_name") or lightning.get("line_name"),
        tower_for_ledger,
    )
    if (
        not ledger_result.get("matched")
        and _has_value(fault.get("line_name"))
        and _has_value(lightning.get("line_name"))
        and _normalize_line_name(fault.get("line_name"))
        != _normalize_line_name(lightning.get("line_name"))
    ):
        alternative = lookup_ledger(ledger_rows, lightning.get("line_name"), tower_for_ledger)
        if alternative.get("matched"):
            ledger_result["diagnostic"] = (
                f"台账内容可匹配雷电定位线路“{lightning.get('line_name')}”，"
                f"但不能匹配录波线路“{fault.get('line_name')}”；为避免跨线路误用，未采用该台账记录"
            )
            ledger_result["alternative_line_name"] = lightning.get("line_name")
    lightning_cause = analyze_lightning_withstand(
        lightning,
        ledger_result,
        validation=validation,
    )
    wave_analysis = analyze_traveling_waves(
        traveling_wave_records or [],
        fault,
        settings=settings,
        model_result=wave_model_result,
        review_context=wave_review_context,
    )
    cause_fusion = fuse_cause_analyses(
        lightning_cause,
        wave_analysis,
        optical,
        conflict_discount=float(settings.get("cause_fusion_conflict_discount", 0.80)),
    )
    ground_summary = build_ground_fault_user_summary(fault, decision)
    overall_recommendation = build_overall_recommendation(
        validation,
        ledger_result,
        location_analysis,
        lightning_cause,
        wave_analysis,
        cause_fusion,
        decision,
        resistance,
    )

    return {
        "schema_version": "0.9.0",
        "scope": "输入归一化、接地故障判别、过渡电阻计算、综合定位、耐雷水平与行波融合分析",
        "source_paths": _json_safe(source_paths or {}),
        "inputs": {
            "fault_record": _json_safe(fault),
            "lightning": _json_safe(lightning),
            "line_ledger": ledger_result,
            "location": _json_safe(location),
            "optical": _json_safe(optical),
            "traveling_wave_files": [
                {
                    key: _json_safe(value)
                    for key, value in record.items()
                    if key != "samples"
                }
                for record in (traveling_wave_records or [])
            ],
            "unit_assumptions": {
                "unitless_phase_voltage": default_voltage_unit,
                "unitless_current": default_current_unit,
                "zero_sequence_representation": zero_representation.upper(),
            },
        },
        "ground_fault_decision": asdict(decision),
        "ground_fault_summary": ground_summary,
        "transition_resistance": asdict(resistance),
        "fault_location": location_analysis,
        "lightning_cause_analysis": lightning_cause,
        "traveling_wave_analysis": wave_analysis,
        "cause_fusion": cause_fusion,
        "input_validation": validation,
        "overall_recommendation": overall_recommendation,
    }


def render_markdown_summary(result: Mapping[str, Any]) -> str:
    """从结构化结果自动生成步骤1-5的人读摘要。"""
    inputs = result.get("inputs", {})
    fault = inputs.get("fault_record", {})
    lightning = inputs.get("lightning", {})
    ledger = inputs.get("line_ledger", {})
    decision = result.get("ground_fault_decision", {})
    ground_summary = result.get("ground_fault_summary", {})
    resistance = result.get("transition_resistance", {})
    fault_location = result.get("fault_location", {})
    lightning_cause = result.get("lightning_cause_analysis", {})
    wave_analysis = result.get("traveling_wave_analysis", {})
    cause_fusion = result.get("cause_fusion", {})
    validation = result.get("input_validation", {})
    recommendation = result.get("overall_recommendation", {})

    def display(value: Any, empty: str = "未提供") -> str:
        return empty if not _has_value(value) else str(value)

    status_labels = {
        "ok": "通过",
        "warning": "需关注",
        "needs_review": "需复核",
        "analyzed": "已完成",
        "located": "已定位",
        "fused": "已融合",
        "unavailable": "不可用",
    }

    def status_text(value: Any) -> str:
        return status_labels.get(str(value), display(value))

    fault_phase = display(ground_summary.get("fault_phase"), display(fault.get("fault_phase")))
    ground_conclusion = display(
        ground_summary.get("conclusion"),
        f"{fault_phase}相{display(decision.get('fault_kind'))}",
    )
    resistance_text = (
        "不适用（当前仅对单相接地故障计算）"
        if resistance.get("status") == "not_applicable"
        else "无法计算"
        if resistance.get("status") == "unavailable"
        else f"{display(resistance.get('transition_resistance_ohm'))} Ω"
    )

    lines = [
        "# 步骤1-5自动判别摘要",
        "",
        "## 总体状态",
        "",
        f"- 输入一致性：**{status_text(validation.get('status'))}**",
        f"- 接地判别：**{ground_conclusion}**",
        f"- 过渡电阻：{resistance_text}",
        f"- 综合故障位置：**{display(fault_location.get('result_text'))}**",
        f"- 雷击原因初判：**{display(lightning_cause.get('report_text'), display(lightning_cause.get('mechanism')))}**",
        f"- 行波分析：**{display(wave_analysis.get('report_conclusion'), display(wave_analysis.get('classification')))}**",
        f"- 原因融合：**{display(cause_fusion.get('final_detail'), display(cause_fusion.get('final_mechanism')))}**（固定判据不计算概率）",
        f"- 后续意见：**{display(recommendation.get('decision'), '建议人工复核')}**",
        "",
    ]
    if recommendation:
        lines.extend(["### 后续意见", "", display(recommendation.get("summary")), ""])
        lines.extend(f"- {item}" for item in recommendation.get("reasons", []))
        lines.append("")
    issues = validation.get("issues", [])
    if issues:
        severity_labels = {"error": "错误", "warning": "提醒", "info": "说明"}
        lines.extend(["### 输入校验", ""])
        for item in issues:
            lines.append(
                f"- 【{severity_labels.get(item.get('severity', 'info'), '说明')}】{item.get('message', '')}"
            )
        lines.append("")

    lines.extend(
        [
            "## 步骤1：输入信息",
            "",
            "### 录波故障信息",
            "",
            "| 字段 | 值 |",
            "|---|---|",
        ]
    )
    fault_labels = [
        ("station", "录波记录厂站"),
        ("fault_time", "故障时刻"),
        ("line_name", "故障线路名称"),
        ("fault_phase", "故障相"),
        ("duration_ms", "故障持续时间(ms)"),
        ("reclosing", "重合闸情况"),
        ("phase_voltage", "故障相电压"),
        ("phase_current", "故障相电流"),
        ("zero_sequence_current", "提取的零序电流（已定义为3I0）"),
        ("zero_sequence_compensation_k", "零序补偿系数K"),
        ("line_length_km", "线路总长度L(km)"),
        ("sensitive_angle_deg", "线路正序灵敏角(°)"),
        ("positive_sequence_impedance_ohm", "线路正序阻抗定值(Ω)"),
    ]
    lines.extend(f"| {label} | {display(fault.get(key))} |" for key, label in fault_labels)

    lines.extend(["", "### 雷电流及定位信息", "", "| 字段 | 值 |", "|---|---|"])
    lightning_labels = [
        ("event_id", "事件编号"),
        ("line_name", "线路名称"),
        ("fault_time", "表内故障时刻"),
        ("query_result", "是否存在落雷记录"),
        ("location_time", "雷电定位时刻"),
        ("current_ka", "雷电流幅值(kA)"),
        ("nearest_tower", "雷电定位最近杆塔/区段"),
        ("distance_to_line_km", "雷击点距线路距离(km)"),
        ("line_side_distances_km", "线路两侧距离(km)"),
        ("recording_distance_km", "录波测距(km)"),
        ("recording_nearest_tower", "录波测距最近杆塔"),
        ("traveling_wave_distance_km", "行波测距(km)"),
        ("traveling_wave_nearest_tower", "行波测距最近杆塔"),
    ]
    lines.extend(f"| {label} | {display(lightning.get(key))} |" for key, label in lightning_labels)

    records = ledger.get("records", []) if isinstance(ledger, Mapping) else []
    if records:
        lines.extend(
            [
                "",
                "### 线路台账匹配结果",
                "",
                "| 杆塔 | 地形 | 海拔(m) | 地闪密度 | 杆塔模型 | 塔形 | 绝缘子串(m) | 接地电阻(Ω) | 反击耐雷(kA) | 绕击耐雷(kA) | 风险等级 |",
                "|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for record in records:
            lines.append(
                "| {tower} | {terrain} | {elevation} | {density} | {model} | {shape} | {insulator} | {ground} | {back} | {shield} | {risk} |".format(
                    tower=display(record.get("tower_no")),
                    terrain=display(record.get("terrain")),
                    elevation=display(record.get("elevation_m")),
                    density=display(record.get("ground_flash_density")),
                    model=display(record.get("tower_model")),
                    shape=display(record.get("tower_shape")),
                    insulator=display(record.get("insulator_length_m")),
                    ground=display(record.get("ground_resistance_ohm")),
                    back=display(record.get("backflashover_withstand_ka")),
                    shield=display(record.get("shielding_failure_withstand_ka")),
                    risk=display(record.get("lightning_risk_level")),
                )
            )
    else:
        available_lines = "、".join(str(item) for item in ledger.get("available_line_names", []))
        lines.extend(
            [
                "",
                "### 线路台账匹配结果",
                "",
                "状态：**未匹配，建议复核输入文件**。",
                "",
                f"- 查询线路：{display(ledger.get('requested_line_name'), display(fault.get('line_name')))}",
                f"- 台账文件实际线路：{available_lines or '未识别'}",
                f"- 匹配说明：{display(ledger.get('diagnostic'), display(ledger.get('reason')))}",
            ]
        )

    lines.extend(
        [
            "",
            "## 步骤2：接地故障判断",
            "",
            f"结论：**{ground_conclusion}**。",
            "",
        ]
    )
    observations = ground_summary.get("observations", [])
    lines.extend(f"- {item}；" for item in observations[:-1])
    if observations:
        lines.append(f"- {observations[-1]}。")

    lines.extend(["", "## 步骤3：过渡电阻计算", ""])
    if resistance.get("status") == "not_applicable":
        lines.extend(
            [
                f"结论：本次为**{ground_conclusion}**。当前过渡电阻公式仅用于单相接地故障，"
                "本工况不计算过渡电阻。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"主结果采用：**输入值按 {display(resistance.get('selected_zero_sequence_representation'))} 解释**。",
                f"选择依据：{display(resistance.get('selection_reason'))}",
                "",
                "| 输入零序电流解释 | 3I0代入值(A) | Zm(Ω) | Rf(Ω) | 状态 | 分类 | 主结果 |",
                "|---|---:|---:|---:|---|---|---|",
            ]
        )
        for candidate in resistance.get("zero_sequence_comparison", {}).values():
            lines.append(
                "| {assumption} | {three_i0} | {zm} | {rf} | {status} | {category} | {selected} |".format(
                    assumption=display(candidate.get("assumption")),
                    three_i0=display(candidate.get("three_i0_a_used")),
                    zm=display(candidate.get("zm_ohm")),
                    rf=display(candidate.get("transition_resistance_ohm")),
                    status=status_text(candidate.get("status")),
                    category=display(candidate.get("category")),
                    selected="是" if candidate.get("selected") else "否",
                )
            )
        lines.extend(["", "> 两套结果用于核对字段语义；主结果依据数据定义选择，不能只凭正负号反推零序电流含义。", ""])
    lines.extend(
        [
            "## 步骤4：综合故障定位与雷击原因初判",
            "",
            "### 4.1 三源故障定位",
            "",
            f"综合结论：**{display(fault_location.get('result_text'))}**；判定状态：**{status_text(fault_location.get('status'))}**；"
            f"共有 {display(fault_location.get('supporting_source_count'), 0)} 个来源共同支持。",
            "",
            "| 信息来源 | 最近杆塔/区段 | 测距(km) | 是否参与 |",
            "|---|---|---:|---|",
        ]
    )
    for source in fault_location.get("sources", []):
        lines.append(
            f"| {display(source.get('label'))} | {display(source.get('tower'))} | "
            f"{display(source.get('distance_km'))} | {'是' if source.get('available') else '否'} |"
        )
    if fault_location.get("evidence"):
        lines.extend(["", "定位依据：", ""])
        lines.extend(f"- {item}" for item in fault_location.get("evidence", []))
    if fault_location.get("warnings"):
        lines.extend(["", "定位复核项：", ""])
        lines.extend(f"- {item}" for item in fault_location.get("warnings", []))

    lines.extend(
        [
            "",
            "### 4.2 耐雷水平分析",
            "",
            f"结论：**{display(lightning_cause.get('conclusion'))}**",
            f"概率说明：{display(lightning_cause.get('confidence_explanation'), '固定阈值比较不计算概率')}。",
            "",
            "| 杆塔 | 雷电流(kA) | 反击耐雷(kA) | 绕击耐雷(kA) | I/反击阈值 | I/绕击阈值 | 初判 |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in lightning_cause.get("tower_analyses", []):
        lines.append(
            "| {tower} | {current} | {back} | {shielding} | {back_ratio} | {shielding_ratio} | {mechanism} |".format(
                tower=display(item.get("tower_no")),
                current=display(item.get("lightning_current_ka")),
                back=display(item.get("backflashover_withstand_ka")),
                shielding=display(item.get("shielding_failure_withstand_ka")),
                back_ratio=display(item.get("current_to_backflash_ratio")),
                shielding_ratio=display(item.get("current_to_shielding_ratio")),
                mechanism=display(item.get("report_text"), display(item.get("mechanism"))),
            )
        )
        lines.append(f"  - {display(item.get('tower_no'))}：{display(item.get('basis'))}")
    if lightning_cause.get("warnings"):
        lines.extend(["", "原因分析说明：", ""])
        lines.extend(f"- {item}" for item in lightning_cause.get("warnings", []))
    lines.extend(
        [
            "",
            "## 步骤5：分布式行波分析与原因融合",
            "",
            f"行波判别过程：**{display(wave_analysis.get('report_conclusion'), display(wave_analysis.get('classification')))}**。",
            f"最终机制描述：**{display(wave_analysis.get('final_detail'), display(wave_analysis.get('mechanism')))}**。",
            f"量化说明：{display(wave_analysis.get('confidence_explanation'), '未计算概率')}。",
            f"分析方法：{display(wave_analysis.get('analysis_method'))}。",
            "",
            "| 相别 | 文件 | 采样点 | 采样率(Hz) | 首波时刻(μs) | 波尾(μs) | 频谱特征 | 波形结构 | 反极性脉冲 |",
            "|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for item in wave_analysis.get("phase_analyses", []):
        lines.append(
            "| {phase} | {file} | {count} | {rate} | {onset} | {tail} | {frequency} | {structure} | {reverse} |".format(
                phase=display(item.get("phase")),
                file=display(item.get("file_name")),
                count=display(item.get("sample_count")),
                rate=display(item.get("sample_rate_hz")),
                onset=display(item.get("onset_time_us")),
                tail=display(item.get("tail_time_us")),
                frequency=display(item.get("frequency_character")),
                structure=display(item.get("waveform_structure")),
                reverse=display(item.get("reverse_polarity_text")),
            )
        )
    model_result = wave_analysis.get("model_result", {})
    phase_review = wave_analysis.get("fault_phase_review", {})
    if phase_review:
        phase_matches = phase_review.get("phase_matches")
        if phase_matches is None and model_result.get("phase_consistency"):
            phase_matches = str(model_result.get("phase_consistency")) == "Consistent"
        amplitude_matches = phase_review.get("amplitude_matches")
        review_main_phase = phase_review.get("initial_wave_main_phase") or model_result.get("main_phase")
        review_active_phases = phase_review.get("initial_wave_active_phases")
        if not review_active_phases:
            review_active_phases = _phase_letters(model_result.get("active_phases"))
        amplitude_review_text = (
            f"已参与复核（{display(phase_review.get('amplitude_band'), '已输入')}）"
            if phase_review.get("amplitude_information_supplied")
            else "未参与（未匹配到幅值或反击耐雷水平）"
        )
        lines.extend(
            [
                "",
                "### 5.1 录波故障相回传复核",
                "",
                f"- 录波故障相：`{display(phase_review.get('recording_fault_phase'))}`",
                f"- 首次行波判别故障相/候补故障相：`{display(review_main_phase)}` / "
                f"`{'/'.join(review_active_phases) or '未提供'}`",
                f"- 相别核对：**{'一致' if phase_matches is True else '不一致' if phase_matches is False else '不可比较'}**",
                f"- 雷电流幅值核对：**{amplitude_review_text if amplitude_matches is None else '一致' if amplitude_matches is True else '不一致'}**",
                f"- 雷电流阈值标签/首次行波标签：`{display(phase_review.get('amplitude_expected_wave_label'))}` / "
                f"`{display(phase_review.get('initial_wave_label'))}`",
                f"- 是否触发已知相复核：**{'是' if phase_review.get('review_triggered') else '否'}**",
            ]
        )
        if phase_review.get("trigger_reasons"):
            lines.extend(["", "触发依据：", ""])
            lines.extend(f"- {item}" for item in phase_review.get("trigger_reasons", []))
    if model_result:
        lines.extend(
            [
                "",
                "MATLAB模型与相别复核结果：",
                "",
                f"- 首次标签：`{display(model_result.get('initial_final_label'), display(phase_review.get('initial_wave_label')))}`",
                f"- 最终标签：`{display(model_result.get('final_label'))}`（{display(model_result.get('meaning'))}）",
                f"- 行波判别故障相/候补故障相：`{display(model_result.get('main_phase'))}` / `{display(model_result.get('active_phases'))}`",
                f"- 首次模型雷击得分：`{float(model_result.get('ln_lightning_score', 0)):.2%}`",
                f"- 首次模型非雷击得分：`{float(model_result.get('ln_non_lightning_score', 0)):.2%}`",
                "- 得分性质：模型输出分数，不自动视为经过校准的真实概率。",
            ]
        )
        if model_result.get("correction_requested"):
            correction_status = display(model_result.get("correction_status"))
            correction_status_cn = _correction_status_label(correction_status)
            subtype = display(model_result.get("final_subtype"))
            subtype_cn = _wave_subtype_label(subtype)
            lines.extend(
                [
                    f"- 复核状态：**{correction_status_cn}**（`{correction_status}`）；"
                    f"是否修正：`{'是' if model_result.get('correction_applied') else '否'}`",
                    f"- 回传/修正故障相：`{display(model_result.get('supplied_fault_phase'))}` / "
                    f"`{display(model_result.get('corrected_fault_phase'))}`",
                    f"- 最终子类型：`{subtype_cn}`",
                    f"- 复核依据：{display(model_result.get('correction_reason'))}",
                ]
            )
    if wave_analysis.get("evidence"):
        lines.extend(["", "行波判据：", ""])
        lines.extend(f"- {item}" for item in wave_analysis.get("evidence", []))
    if wave_analysis.get("warnings"):
        lines.extend(["", "行波复核项：", ""])
        lines.extend(f"- {item}" for item in wave_analysis.get("warnings", []))

    lines.extend(
        [
            "",
            "### 原因融合",
            "",
            f"融合结论：**{display(cause_fusion.get('final_detail'), display(cause_fusion.get('final_mechanism')))}**；一致性：**{display(cause_fusion.get('consistency'))}**。",
            "概率说明：本次不输出融合置信度；固定阈值和相别复核规则只能说明判据是否满足，不能直接生成概率。",
            "",
            "| 来源 | 结论 | 证据性质 | 量化信息 |",
            "|---|---|---|---|",
        ]
    )
    for source in cause_fusion.get("sources", []):
        source_value = (
            f"输入值 {float(source['confidence']):.0%}"
            if source.get("confidence") is not None
            else "不计算概率"
        )
        lines.append(
            f"| {display(source.get('source'))} | {display(source.get('mechanism'))} | "
            f"{display(source.get('evidence_type'))} | {source_value} |"
        )
    confidence_calculation = cause_fusion.get("confidence_calculation", {})
    if confidence_calculation:
        lines.extend(
            [
                "",
                "置信度处理：",
                "",
                f"- 方法：`{display(confidence_calculation.get('method'))}`",
                f"- 说明：{display(confidence_calculation.get('explanation'))}",
            ]
        )
    if cause_fusion.get("warnings"):
        lines.extend(["", "融合复核项：", ""])
        lines.extend(f"- {item}" for item in cause_fusion.get("warnings", []))
    lines.append("")
    return "\n".join(lines)


def _default_summary_path(output_path: Path) -> Path:
    stem = output_path.stem.replace("结果", "摘要") if "结果" in output_path.stem else f"{output_path.stem}_摘要"
    return output_path.with_name(f"{stem}.md")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="多源故障综合判别：步骤1-5")
    parser.add_argument("--fault", required=True, type=Path, help="录波输入：PDF/JSON/CSV/XLSX")
    parser.add_argument("--lightning", required=True, type=Path, help="人工填写的雷电流及定位数据 XLSX")
    parser.add_argument("--ledger", required=True, type=Path, help="线路台账 CSV")
    parser.add_argument("--wave", action="append", type=Path, default=[], help="分布式行波TXT/JSON，可重复提供")
    parser.add_argument("--wave-model-result", type=Path, help="MATLAB行波模型prediction.txt（可选）")
    parser.add_argument("--wave-review-context", type=Path, help="首次行波与录波相别/雷电流核对记录JSON（可选）")
    parser.add_argument("--manual", type=Path, help="光学监测、字段修正及计算设置 JSON（可选）")
    parser.add_argument("-o", "--output", required=True, type=Path, help="输出判别结果 JSON")
    parser.add_argument("--summary", type=Path, help="输出 Markdown 摘要；省略时自动生成")
    parser.add_argument("--extractor", type=Path, help="录波 PDF 提取器 extract_fault_report.py")
    parser.add_argument("--ocr-engine", choices=["auto", "paddle", "tesseract", "text"], default="auto")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    for path, label in (
        (args.fault, "录波输入"),
        (args.lightning, "雷电定位输入"),
        (args.ledger, "线路台账"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label}不存在: {path}")
    if args.manual and not args.manual.exists():
        raise FileNotFoundError(f"人工输入不存在: {args.manual}")
    for path in args.wave:
        if not path.exists():
            raise FileNotFoundError(f"行波输入不存在: {path}")
    if args.wave_model_result and not args.wave_model_result.exists():
        raise FileNotFoundError(f"行波模型结果不存在: {args.wave_model_result}")
    if args.wave_review_context and not args.wave_review_context.exists():
        raise FileNotFoundError(f"行波复核记录不存在: {args.wave_review_context}")

    fault_raw = load_fault_source(args.fault, extractor_path=args.extractor, ocr_engine=args.ocr_engine)
    lightning_raw = load_lightning_source(args.lightning)
    manual = load_manual_input(args.manual)
    ledger_rows = load_ledger_rows(args.ledger)
    traveling_wave_records = [load_traveling_wave_file(path) for path in args.wave]
    wave_model_result = load_wave_model_result(args.wave_model_result)
    wave_review_context = (
        json.loads(args.wave_review_context.read_text(encoding="utf-8-sig"))
        if args.wave_review_context
        else {}
    )
    result = build_diagnosis(
        fault_raw,
        manual,
        ledger_rows,
        lightning_raw=lightning_raw,
        traveling_wave_records=traveling_wave_records,
        wave_model_result=wave_model_result,
        wave_review_context=wave_review_context,
        source_paths={
            "fault": args.fault.resolve(),
            "lightning": args.lightning.resolve(),
            "ledger": args.ledger.resolve(),
            "manual": args.manual.resolve() if args.manual else None,
            "traveling_waves": [path.resolve() for path in args.wave],
            "wave_model_result": args.wave_model_result.resolve() if args.wave_model_result else None,
            "wave_review_context": args.wave_review_context.resolve() if args.wave_review_context else None,
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = args.summary or _default_summary_path(args.output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(render_markdown_summary(result), encoding="utf-8")

    decision = result["ground_fault_decision"]
    resistance = result["transition_resistance"]
    print(f"接地判别: {decision['fault_kind']}")
    if resistance["transition_resistance_ohm"] is not None:
        print(
            f"过渡电阻: {resistance['transition_resistance_ohm']:.6f} Ω，"
            f"{resistance['category']}"
        )
    else:
        print(f"过渡电阻: 未计算 ({'; '.join(resistance['warnings'])})")
    location_result = result["fault_location"]
    cause_result = result["lightning_cause_analysis"]
    print(f"综合定位: {location_result['result_text']} ({location_result['status']})")
    print(
        f"雷击原因初判: {cause_result.get('report_text') or cause_result['mechanism']} "
        f"({cause_result['status']})"
    )
    wave_result = result["traveling_wave_analysis"]
    fusion_result = result["cause_fusion"]
    print(f"行波分析: {wave_result['classification']} ({wave_result['status']})")
    print(f"行波判别过程: {wave_result.get('report_conclusion', wave_result['classification'])}")
    print(
        f"原因融合: {fusion_result.get('final_detail', fusion_result['final_mechanism'])} "
        f"(固定判据不计算概率, {fusion_result['status']})"
    )
    print(f"结果已写出: {args.output}")
    print(f"摘要已写出: {summary_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(2)
