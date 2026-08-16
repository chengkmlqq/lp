from __future__ import annotations

import shutil
import logging
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.fault_analysis import FaultAnalysis
from .fault_analysis_service import assemble_ledger_rows, get_analysis_by_id
from .fault_diagnosis_core import (
    InputError,
    build_diagnosis,
    load_fault_source,
    load_ledger_rows,
    load_lightning_source,
    load_traveling_wave_file,
    load_wave_model_result,
    render_markdown_summary,
)
from .fault_input_discovery import normalize_input_files

logger = logging.getLogger(__name__)

# 判别系统人工输入默认值（与交付版 config/manual_input.json 一致）
DEFAULT_MANUAL: dict[str, Any] = {
    "optical": {
        "result": "无明显落雷记录",
        "strike_position": "无",
        "device_tower": "N65",
    },
    "calculation": {
        "default_voltage_unit": "kV",
        "default_current_unit": "kA",
        "zero_sequence_representation": "3I0",
        "ground_zero_sequence_ratio_threshold": 0.1,
        "ground_zero_sequence_absolute_threshold_a": 100,
    },
}

RISK_LEVEL_LABELS: dict[str, str] = {
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
    "critical": "极高风险",
}


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "None", "nan", "NaN"}


def build_fault_raw(item: FaultAnalysis) -> dict[str, Any]:
    """把 LP 故障分析记录的表单标量字段组织成判别系统 fault_raw 输入。"""
    raw: dict[str, Any] = {}
    mapping: dict[str, str] = {
        "station": "station",
        "fault_time": "fault_time",
        "line_name": "line_name",
        "fault_phase": "fault_phase",
        "fault_duration_ms": "duration_ms",
        "reclosure_status": "reclosing",
        "fault_voltage_v": "phase_voltage",
        "fault_current_a": "phase_current",
        "max_zero_current_a": "zero_sequence_current",
        "zero_compensation": "zero_sequence_compensation_k",
        "line_length_km": "line_length_km",
        "line_angle_deg": "sensitive_angle_deg",
        "line_impedance_ohm": "positive_sequence_impedance_ohm",
    }
    for lp_field, diag_field in mapping.items():
        value = getattr(item, lp_field, None)
        if _has_value(value):
            raw[diag_field] = value
    if item.reclosure_status:
        reclosing_labels = {
            "success": "成功",
            "failed": "失败",
            "not_applicable": "不适用",
        }
        raw["reclosing"] = reclosing_labels.get(item.reclosure_status, item.reclosure_status)
    return raw


def build_lightning_raw(item: FaultAnalysis) -> dict[str, Any]:
    """把 LP 雷电字段组织成判别系统 lightning_raw 输入。"""
    raw: dict[str, Any] = {}
    if _has_value(item.line_name):
        raw["line_name"] = item.line_name
    if _has_value(item.fault_time):
        raw["fault_time"] = item.fault_time
    if item.lightning_current_ka is not None:
        raw["current_ka"] = item.lightning_current_ka
        raw["query_result"] = "是"
    else:
        raw["query_result"] = "否"
    if item.wave_distance_km is not None:
        raw["recording_distance_km"] = item.wave_distance_km
    if item.traveling_wave_distance_km is not None:
        raw["traveling_wave_distance_km"] = item.traveling_wave_distance_km
    if _has_value(item.optical_device_location):
        raw["nearest_tower"] = item.optical_device_location
    return raw


def build_manual_input(item: FaultAnalysis) -> dict[str, Any]:
    """生成判别系统 manual 输入：默认值 + LP 光学字段。"""
    manual = {key: dict(value) for key, value in DEFAULT_MANUAL.items()}
    optical = dict(manual["optical"])
    if _has_value(item.optical_device_location):
        optical["device_tower"] = item.optical_device_location
    if _has_value(item.optical_position):
        optical["strike_position"] = item.optical_position
    manual["optical"] = optical
    return manual


def _resolve_upload_file(upload_files: Mapping[str, Any], field: str) -> Path | None:
    relative = upload_files.get(field)
    if not relative:
        return None
    candidate = Path(str(relative))
    if not candidate.is_absolute():
        candidate = Path(get_settings().file_vfs_root) / str(relative)
    return candidate.resolve() if candidate.is_file() else None


def _resolve_upload_files(upload_files: Mapping[str, Any], field: str) -> list[Path]:
    """解析字段路径；行波允许单个相对路径或相对路径列表。"""
    relative = upload_files.get(field)
    if not relative:
        return []
    if isinstance(relative, str):
        candidates = [relative]
    elif isinstance(relative, list):
        candidates = [str(item) for item in relative if item]
    else:
        candidates = [str(relative)]
    resolved: list[Path] = []
    for item in candidates:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = Path(get_settings().file_vfs_root) / item
        candidate = candidate.resolve()
        if candidate.is_file():
            resolved.append(candidate)
    return resolved


def _collect_inputs(
    item: FaultAnalysis,
    *,
    db: Session | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], list[dict[str, Any]], list[str]]:
    """把记录标量字段 + 上传文件组装成判别输入；单个文件解析失败时降级不抛异常。"""
    upload_files = item.upload_files or {}
    warnings: list[str] = []

    fault_raw = build_fault_raw(item)
    lightning_raw = build_lightning_raw(item)
    ledger_rows: list[dict[str, str]] = []
    traveling_wave_records: list[dict[str, Any]] = []

    # 录波输入：优先上传文件（PDF/JSON/CSV/XLSX），无法解析时退化为表单标量字段。
    fault_file = _resolve_upload_file(upload_files, "wave_data_file")
    if fault_file is not None:
        try:
            loaded = load_fault_source(fault_file)
            merged = dict(fault_raw)
            merged.update({key: value for key, value in loaded.items() if _has_value(value)})
            fault_raw = merged
        except Exception as exc:
            warnings.append(f"录波文件解析失败，改用表单标量字段：{exc}")

    # 雷电定位输入：优先上传文件（XLSX/XLSM/CSV），无法解析时退化为表单字段。
    lightning_file = _resolve_upload_file(upload_files, "lightning_data_file")
    if lightning_file is not None:
        try:
            loaded = load_lightning_source(lightning_file)
            merged = dict(lightning_raw)
            merged.update({key: value for key, value in loaded.items() if _has_value(value)})
            lightning_raw = merged
        except Exception as exc:
            warnings.append(f"雷电定位文件解析失败，改用表单标量字段：{exc}")

    # 台账输入：优先上传 CSV；未上传时使用配置的默认台账。
    ledger_file = _resolve_upload_file(upload_files, "ledger_data_file")
    if ledger_file is None:
        configured = (get_settings().fault_diag_ledger_csv or "").strip()
        if configured:
            configured_path = Path(configured)
            if configured_path.is_file():
                ledger_file = configured_path
    if ledger_file is not None:
        try:
            ledger_rows = load_ledger_rows(ledger_file)
            if not ledger_rows:
                warnings.append("台账文件无有效行（需包含线路名称与塔号字段）")
        except Exception as exc:
            warnings.append(f"台账文件解析失败：{exc}")

    # 台账自动组装（LP-378）：无上传台账且无默认配置时，按所选线路实时从系统数据组装，
    # 保证纯 JSON POST（无文件）创建路径同样吃到自动台账；线路无杆塔数据时给出提示。
    if ledger_file is None and db is not None and _has_value(item.line_id):
        try:
            ledger_rows = assemble_ledger_rows(db, item.line_id)
            if not ledger_rows:
                warnings.append(
                    f"线路「{item.line_name or item.line_id}」无杆塔数据，无法自动组装判别台账"
                )
        except Exception as exc:
            warnings.append(f"台账自动组装失败：{exc}")

    # 行波输入：支持 TXT/JSON（含 CurrentDataInput 或采样数组），允许多文件，失败则跳过该文件。
    for wave_file in _resolve_upload_files(upload_files, "traveling_wave_file"):
        try:
            traveling_wave_records.append(load_traveling_wave_file(wave_file))
        except Exception as exc:
            warnings.append(f"行波文件解析失败，跳过：{exc}")

    # 光学输入文件（图片/视频）不做内容解析，光学字段以表单为准。
    return fault_raw, lightning_raw, ledger_rows, traveling_wave_records, warnings


def _try_matlab_wave_enhancement(
    analysis_id: str,
    analysis_dir: Path,
    fault_raw: Mapping[str, Any],
    lightning_raw: Mapping[str, Any],
    ledger_rows: Sequence[Mapping[str, Any]],
    traveling_wave_records: Sequence[Mapping[str, Any]],
    manual: Mapping[str, Any],
) -> tuple[Path | None, dict[str, Any] | None]:
    """可插拔行波增强：优先调用 MATLAB Runtime 编译产物，不可用时返回 (None, None)。

    编译产物约定（与判别系统交付版 RunWaveAnalysisModule 输入/输出一致）：
    - 位置：settings.fault_diag_matlab_compiled_dir（环境变量 FAULT_DIAG_MATLAB_COMPILED_DIR）
    - 可执行入口：目录下 RunWaveAnalysisModule（Linux 上由 mcc 编译，内嵌 MATLAB Runtime）
    - 输入：暂存目录（行波数据文件 + 录波故障相X.txt + 幅值XkA_耐雷水平YkA.txt）
    - 输出：输出根目录/最新结果路径.txt -> 本次输出目录/wave_module_prediction.txt

    未配置产物、可执行文件缺失或调用失败时一律返回 (None, None)，由调用方降级到
    内置 Python 可解释特征规则（analyze_traveling_waves 启发式分支）。
    """
    compiled_dir = (get_settings().fault_diag_matlab_compiled_dir or "").strip()
    if not compiled_dir:
        logger.info("Fault diagnosis MATLAB skipped: compiled directory is not configured")
        return None, None
    if not traveling_wave_records:
        logger.info("Fault diagnosis MATLAB skipped: no traveling-wave records were loaded")
        return None, None
    # 判别系统产物：Windows mcc 编译的 .exe 经 Wine 调用；Linux mcc 编译的
    # RunWaveAnalysisModule（含完整判定模型）直接执行（fquiz-matlab-worker 镜像
    # 内置 Linux 版 MATLAB Runtime，无需 Wine）。
    exe_names = ("waveform_engine_v2.exe", "waveform_engine.exe", "RunWaveAnalysisModule")
    executable = next((Path(compiled_dir) / n for n in exe_names if (Path(compiled_dir) / n).is_file()), None)
    if executable is None:
        logger.warning("Fault diagnosis MATLAB skipped: no wave module executable in %s", compiled_dir)
        return None, None
    # Wine 二进制：仅 Windows 产物需要；Linux 产物直接执行。
    wine_binary = (get_settings().wine_binary_path or "wine").strip() or "wine"

    # 先用内置规则做一次初判，提取录波故障相与雷电流/耐雷水平（与交付版 run_latest_wave_module 相同）。
    try:
        preliminary = build_diagnosis(
            dict(fault_raw),
            dict(manual),
            list(ledger_rows),
            lightning_raw=dict(lightning_raw) or None,
            traveling_wave_records=list(traveling_wave_records),
        )
    except Exception:
        logger.exception("Fault diagnosis MATLAB preliminary analysis failed for %s", analysis_id)
        return None, None
    fault = preliminary["inputs"].get("fault_record", {})
    fault_phase = "".join(
        dict.fromkeys(letter for letter in str(fault.get("fault_phase") or "").upper() if letter in "ABC")
    )
    lightning_analysis = preliminary.get("lightning_cause_analysis", {})
    current_ka = lightning_analysis.get("lightning_current_ka")
    thresholds = [
        item.get("backflashover_withstand_ka")
        for item in lightning_analysis.get("tower_analyses", [])
        if item.get("backflashover_withstand_ka") is not None
    ]
    backflash_ka = min(float(value) for value in thresholds) if thresholds else None

    root = analysis_dir / "matlab_wave_analysis"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    staged_input = root / "module_inputs" / run_id
    output_root = root / "module_runs"
    try:
        staged_input.mkdir(parents=True, exist_ok=False)
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Fault diagnosis MATLAB staging directory creation failed for %s", analysis_id)
        return None, None
    for record in traveling_wave_records:
        source = Path(str(record.get("path") or ""))
        if source.is_file():
            try:
                shutil.copy2(source, staged_input / source.name)
            except OSError:
                pass
    if fault_phase:
        (staged_input / f"录波故障相{fault_phase}.txt").write_text(
            f"录波故障相={fault_phase}\n", encoding="utf-8"
        )
    if current_ka is not None and backflash_ka is not None:
        (staged_input / f"幅值{abs(float(current_ka)):g}kA_耐雷水平{backflash_ka:g}kA.txt").write_text(
            f"幅值={abs(float(current_ka)):g}kA\n耐雷水平={backflash_ka:g}kA\n",
            encoding="utf-8",
        )

    try:
        # Windows 产物走 Wine 无头环境（抑制 GUI 弹窗）；Linux 产物直接执行。
        env = {**__import__("os").environ}
        env.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d")
        env.setdefault("DISPLAY", "")
        if executable.suffix.lower() == ".exe":
            command = [wine_binary, str(executable)]
        else:
            command = [str(executable)]
        completed = subprocess.run(
            [*command, str(staged_input.resolve()), str(output_root.resolve())],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
    except Exception:
        logger.exception("Fault diagnosis MATLAB process failed for %s", analysis_id)
        return None, None

    latest_file = output_root / "最新结果路径.txt"
    if completed.returncode != 0 or not latest_file.is_file():
        logger.warning(
            "Fault diagnosis MATLAB returned no result for %s: returncode=%s latest_file=%s",
            analysis_id,
            completed.returncode,
            latest_file.is_file(),
        )
        return None, None
    latest_output = Path(latest_file.read_text(encoding="utf-8-sig").strip())
    prediction = latest_output / "wave_module_prediction.txt"
    if not prediction.is_file():
        logger.warning("Fault diagnosis MATLAB prediction file missing for %s: %s", analysis_id, prediction)
        return None, None
    logger.info("Fault diagnosis MATLAB completed for %s: prediction=%s", analysis_id, prediction)
    return prediction, None


def _derive_risk_level(diag: Mapping[str, Any]) -> tuple[str, list[str]]:
    """按判别系统结论派生 LP risk_level（low/medium/high），并记录依据。"""
    decision = diag.get("ground_fault_decision", {})
    validation = diag.get("input_validation", {})
    recommendation = diag.get("overall_recommendation", {})
    ledger = diag.get("inputs", {}).get("line_ledger", {})
    basis: list[str] = []

    # 仅将真正反映输入矛盾的错误（线路/事件时刻不一致）视为高风险；
    # 缺省雷电定位元数据（定位时刻/最近杆塔）只作为待复核项，不直接升高风险。
    fatal_codes = {"line_name_mismatch", "event_time_mismatch"}
    has_fatal_issue = any(
        item.get("severity") == "error" and item.get("code") in fatal_codes
        for item in validation.get("issues", [])
    )

    if decision.get("is_ground_fault") is None:
        risk = "high"
        basis.append("接地属性无法判定")
    elif has_fatal_issue:
        risk = "high"
        basis.append("存在输入不一致（线路或事件时刻冲突）")
    elif not recommendation.get("can_auto_pass"):
        risk = "medium"
        basis.append("存在待人工复核项")
    else:
        risk = "low"
        basis.append("关键输入与多源结论一致，建议通过")

    records = ledger.get("records", []) if isinstance(ledger, Mapping) else []
    risk_labels = [str(record.get("lightning_risk_level") or "") for record in records]
    if any("高" in label for label in risk_labels):
        risk = "high"
        basis.append("台账雷击风险等级为高")
    elif any("中" in label for label in risk_labels) and risk == "low":
        risk = "medium"
        basis.append("台账雷击风险等级为中")
    return risk, basis


def _build_sections(
    diag: Mapping[str, Any],
    *,
    risk_level: str,
    confidence: float | None,
    confidence_source: str,
) -> list[dict[str, Any]]:
    """从判别结果生成 LP 详情页可渲染的 sections（与 analysis-detail-view 约定一致）。"""
    decision = diag.get("ground_fault_decision", {})
    ground_summary = diag.get("ground_fault_summary", {})
    resistance = diag.get("transition_resistance", {})
    fault_location = diag.get("fault_location", {})
    lightning_cause = diag.get("lightning_cause_analysis", {})
    wave = diag.get("traveling_wave_analysis", {})
    cause_fusion = diag.get("cause_fusion", {})
    validation = diag.get("input_validation", {})
    recommendation = diag.get("overall_recommendation", {})
    inputs = diag.get("inputs", {})
    fault = inputs.get("fault_record", {}) if isinstance(inputs, Mapping) else {}

    sections: list[dict[str, Any]] = []

    def text(value: Any) -> dict[str, Any]:
        return {"type": "text", "text": str(value)}

    phase = str(ground_summary.get("fault_phase") or fault.get("fault_phase") or "未知")
    conclusion = str(
        ground_summary.get("conclusion")
        or f"{phase}相{decision.get('fault_kind', '无法判定')}"
    )
    confidence_text = f"{confidence:.2f}%" if confidence is not None else "未计算"
    content: list[dict[str, Any]] = [
        text(f"接地判别结论：{conclusion}"),
        text(f"故障类型：{decision.get('fault_kind', '无法判定')}"),
        text(f"故障相别：{phase}"),
        text(f"综合置信度：{confidence_text}（来源：{confidence_source}）"),
        text(f"风险等级：{RISK_LEVEL_LABELS.get(risk_level, risk_level)}"),
    ]
    recommendation_decision = str(recommendation.get("decision", "建议人工复核"))
    content.append(text(f"判别系统后续意见：{recommendation_decision}"))
    recommendation_reasons = recommendation.get("reasons", [])
    if recommendation_reasons:
        content.append({"type": "bullet", "items": [str(item) for item in recommendation_reasons]})
    sections.append({"title": "一、判别结论", "content": content})

    if resistance.get("status") == "ok":
        rf_value = resistance.get("transition_resistance_ohm")
        content = [
            text(f"过渡电阻 Rf：{rf_value} Ω（{resistance.get('category_report_text', '')}）"),
            text(f"计算公式：{resistance.get('formula_rf')}"),
            text(f"零序电流按 {resistance.get('selected_zero_sequence_representation')} 解释"),
        ]
        if resistance.get("zm_ohm") is not None:
            content.append(text(f"测量阻抗 Zm：{resistance.get('zm_ohm')} Ω"))
        warnings = resistance.get("warnings", [])
        if warnings:
            content.append({"type": "bullet", "items": [str(item) for item in warnings]})
        sections.append({"title": "二、过渡电阻计算", "content": content})
    else:
        sections.append(
            {
                "title": "二、过渡电阻计算",
                "content": [
                    text(f"过渡电阻：{'不适用（仅单相接地故障计算）' if resistance.get('status') == 'not_applicable' else '无法计算'}"),
                    *[{"type": "bullet", "items": [str(item) for item in resistance.get("warnings", [])]}],
                ],
            }
        )

    content = [text(f"综合故障位置：{fault_location.get('result_text', '无法定位')}")]
    for source in fault_location.get("sources", []):
        tower = source.get("tower")
        distance = source.get("distance_km")
        content.append(
            text(f"{source.get('label')}：{tower or '未提供'}{f'（测距 {distance} km）' if distance is not None else ''}")
        )
    if fault_location.get("evidence"):
        content.append({"type": "bullet", "items": [str(item) for item in fault_location.get("evidence", [])]})
    sections.append({"title": "三、综合故障定位", "content": content})

    lightning_conclusion = str(
        lightning_cause.get("conclusion")
        or lightning_cause.get("report_text")
        or lightning_cause.get("mechanism")
        or "无法判定"
    )
    content = [text(f"耐雷水平初判：{lightning_conclusion}")]
    if lightning_cause.get("lightning_current_ka") is not None:
        content.append(text(f"雷电流幅值：{lightning_cause.get('lightning_current_ka')} kA"))
    tower_analyses = lightning_cause.get("tower_analyses", [])
    if tower_analyses:
        items = [
            f"{item.get('tower_no')}: {item.get('report_text', item.get('mechanism', ''))}"
            for item in tower_analyses
        ]
        content.append({"type": "bullet", "items": items})
    sections.append({"title": "四、耐雷水平与雷击原因初判", "content": content})

    wave_conclusion = str(
        wave.get("report_conclusion")
        or wave.get("classification")
        or "未提供行波数据"
    )
    content = [
        text(f"行波判别：{wave_conclusion}"),
        text(f"最终机制：{wave.get('final_detail') or wave.get('mechanism') or '无法判定'}"),
    ]
    if wave.get("analysis_method"):
        content.append(text(f"分析方法：{wave.get('analysis_method')}"))
    if wave.get("evidence"):
        content.append({"type": "bullet", "items": [str(item) for item in wave.get("evidence", [])]})
    if wave.get("warnings"):
        content.append({"type": "bullet", "items": [str(item) for item in wave.get("warnings", [])]})
    sections.append({"title": "五、分布式行波分析", "content": content})

    content = [
        text(f"原因融合结论：{cause_fusion.get('final_detail') or cause_fusion.get('final_mechanism') or '无法判定'}"),
        text(f"来源一致性：{cause_fusion.get('consistency', '无可用原因来源')}"),
    ]
    fusion_sources = cause_fusion.get("sources", [])
    if fusion_sources:
        content.append(
            {
                "type": "bullet",
                "items": [
                    f"{item.get('source')}: {item.get('mechanism')}"
                    for item in fusion_sources
                ],
            }
        )
    content.append({"type": "card", "text": f"后续意见：{recommendation.get('summary', '')}"})
    sections.append({"title": "六、原因融合与建议", "content": content})

    validation_issues = validation.get("issues", [])
    if validation_issues:
        items = [f"【{item.get('severity', 'info')}】{item.get('message', '')}" for item in validation_issues]
        sections.append({"title": "七、输入校验", "content": [{"type": "bullet", "items": items}]})

    return sections


def build_result_json(
    diag: Mapping[str, Any],
    *,
    risk_level: str,
    risk_basis: list[str],
    confidence: float | None,
    confidence_source: str,
    input_warnings: list[str],
    upload_files: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """组装回填到 result_json 的完整结构（含前端 sections 与完整判别结果）。"""
    return {
        "schema_version": diag.get("schema_version"),
        "risk_level": risk_level,
        "risk_level_basis": risk_basis,
        "confidence": confidence,
        "confidence_source": confidence_source,
        "input_warnings": input_warnings,
        "upload_files": dict(upload_files or {}),
        "sections": _build_sections(
            diag,
            risk_level=risk_level,
            confidence=confidence,
            confidence_source=confidence_source,
        ),
        "diagnosis": diag,
        "summary_markdown": render_markdown_summary(diag),
    }


def map_result_to_record(
    diag: Mapping[str, Any],
    item: FaultAnalysis,
    *,
    input_warnings: list[str],
) -> dict[str, Any]:
    """把判别结果映射为 LP 记录字段回填值。"""
    decision = diag.get("ground_fault_decision", {})
    ground_summary = diag.get("ground_fault_summary", {})

    fault_type = ground_summary.get("conclusion") or decision.get("fault_kind") or None
    fault_phase = ground_summary.get("fault_phase") or None
    if fault_phase in {"未知", "", None}:
        fault_phase = None

    decision_confidence = decision.get("confidence")
    if decision_confidence is not None:
        confidence = round(float(decision_confidence) * 100, 2)
        confidence_source = "接地故障判别置信度"
    else:
        confidence = None
        confidence_source = "未计算（接地属性不确定）"

    risk_level, risk_basis = _derive_risk_level(diag)
    result_json = build_result_json(
        diag,
        risk_level=risk_level,
        risk_basis=risk_basis,
        confidence=confidence,
        confidence_source=confidence_source,
        input_warnings=input_warnings,
        upload_files=item.upload_files,
    )
    return {
        "result_json": result_json,
        "risk_level": risk_level,
        "fault_type": fault_type,
        "fault_phase": fault_phase,
        "confidence": confidence,
    }


def run_fault_diagnosis(db: Session, analysis_id: str) -> dict[str, Any]:
    """执行一次完整判别并回填记录字段。供 Celery 任务调用。"""
    item = get_analysis_by_id(db, analysis_id)
    if item is None:
        raise ValueError(f"故障分析记录不存在: {analysis_id}")

    now = utcnow()
    item.status = "processing"
    item.update_date = now
    item.update_user = "system"
    db.commit()

    try:
        fault_raw, lightning_raw, ledger_rows, traveling_wave_records, input_warnings = _collect_inputs(
            item, db=db
        )
        manual = build_manual_input(item)
        analysis_dir = Path(get_settings().file_vfs_root) / "fault_analysis" / analysis_id
        upload_files = item.upload_files or {}
        traveling_wave_paths = _resolve_upload_files(upload_files, "traveling_wave_file")
        logger.info(
            "Fault diagnosis inputs for %s: upload_fields=%s traveling_wave_file_count=%d",
            analysis_id,
            sorted(upload_files),
            len(traveling_wave_paths),
        )

        wave_model_path, wave_review_context = _try_matlab_wave_enhancement(
            analysis_id,
            analysis_dir,
            fault_raw,
            lightning_raw,
            ledger_rows,
            traveling_wave_records,
            manual,
        )
        wave_model_result = load_wave_model_result(wave_model_path) if wave_model_path is not None else None

        source_paths = {
            "fault": _resolve_upload_file(upload_files, "wave_data_file"),
            "lightning": _resolve_upload_file(upload_files, "lightning_data_file"),
            "ledger": _resolve_upload_file(upload_files, "ledger_data_file"),
            "manual": None,
            "traveling_waves": traveling_wave_paths,
            "wave_model_result": wave_model_path,
        }

        diag = build_diagnosis(
            fault_raw,
            manual,
            ledger_rows,
            lightning_raw=lightning_raw or None,
            traveling_wave_records=traveling_wave_records,
            wave_model_result=wave_model_result,
            wave_review_context=wave_review_context,
            source_paths=source_paths,
        )
        mapped = map_result_to_record(diag, item, input_warnings=input_warnings)

        item.status = "completed"
        item.risk_level = mapped["risk_level"]
        item.fault_type = mapped["fault_type"]
        item.fault_phase = mapped["fault_phase"]
        item.confidence = mapped["confidence"]
        item.result_json = mapped["result_json"]
        item.update_date = utcnow()
        item.update_user = "system"
        db.commit()
        return mapped["result_json"]
    except Exception as exc:
        item.status = "failed"
        item.result_json = dict(item.result_json or {})
        item.result_json["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        item.update_date = utcnow()
        item.update_user = "system"
        db.commit()
        raise


def create_diagnosis_job_from_inputs(
    db: Session,
    files: Mapping[str, Sequence[Path]],
    *,
    fault_raw: Mapping[str, Any] | None = None,
    lightning_raw: Mapping[str, Any] | None = None,
    manual: Mapping[str, Any] | None = None,
    ledger_rows: Sequence[Mapping[str, Any]] | None = None,
    input_warnings: list[str] | None = None,
) -> dict[str, Any]:
    """按发现/归一化后的输入文件就地执行一次完整判别，返回判别结果。

    与前端的「表单字段 + 显式类别文件」流程（run_fault_diagnosis + _collect_inputs）不同，
    此路径直接接收按类别划分的原始文件列表（自动发现/归类），逐类通过核心 loader 加载后
    走现有 build_diagnosis 管线。同类别多文件在此处校验并抛 InputError。
    """
    normalized = normalize_input_files({key: list(value) for key, value in files.items()})
    _fault_raw = dict(fault_raw or {})
    _lightning_raw = dict(lightning_raw or {})
    _ledger_rows = [dict(row) for row in (ledger_rows or [])] if ledger_rows is not None else []
    warnings = list(input_warnings or [])

    for path in normalized.get("wave", []) or []:
        try:
            loaded = load_fault_source(path)
            merged = dict(_fault_raw)
            merged.update({key: value for key, value in loaded.items() if _has_value(value)})
            _fault_raw = merged
        except Exception as exc:
            warnings.append(f"录波文件解析失败：{exc}")

    for path in normalized.get("lightning", []) or []:
        try:
            loaded = load_lightning_source(path)
            merged = dict(_lightning_raw)
            merged.update({key: value for key, value in loaded.items() if _has_value(value)})
            _lightning_raw = merged
        except Exception as exc:
            warnings.append(f"雷电定位文件解析失败：{exc}")

    for path in normalized.get("ledger", []) or []:
        try:
            rows = load_ledger_rows(path)
            if rows and not _ledger_rows:
                _ledger_rows = [dict(row) for row in rows]
            elif rows:
                _ledger_rows.extend(dict(row) for row in rows)
            if not rows:
                warnings.append("台账文件无有效行（需包含线路名称与塔号字段）")
        except Exception as exc:
            warnings.append(f"台账文件解析失败：{exc}")

    traveling_wave_records: list[dict[str, Any]] = []
    for path in normalized.get("traveling_wave", []) or []:
        try:
            traveling_wave_records.append(load_traveling_wave_file(path))
        except Exception as exc:
            warnings.append(f"行波文件解析失败：{exc}")

    _manual = dict(dict(manual) if manual is not None else DEFAULT_MANUAL)
    try:
        diag = build_diagnosis(
            dict(_fault_raw),
            dict(_manual),
            list(_ledger_rows),
            lightning_raw=dict(_lightning_raw) or None,
            traveling_wave_records=traveling_wave_records,
        )
    except Exception as exc:
        raise InputError(f"判别管线初始化失败：{exc}") from exc
    return build_result_json(
        diag,
        risk_level=_derive_risk_level(diag)[0],
        risk_basis=_derive_risk_level(diag)[1],
        confidence=_decision_confidence(diag),
        confidence_source=_confidence_source(diag),
        input_warnings=warnings,
        upload_files=None,
    )


def _decision_confidence(diag: Mapping[str, Any]) -> float | None:
    decision = diag.get("ground_fault_decision", {})
    raw = decision.get("confidence")
    if raw is None:
        return None
    return round(float(raw) * 100, 2)


def _confidence_source(diag: Mapping[str, Any]) -> str:
    decision = diag.get("ground_fault_decision", {})
    return "接地故障判别置信度" if decision.get("confidence") is not None else "未计算（接地属性不确定）"


def generate_report_docx(db: Session, analysis_id: str, template_path: Path | None = None) -> Path:
    """生成故障分析 Word 报告并保存到 VFS。"""
    item = get_analysis_by_id(db, analysis_id)
    if item is None:
        raise ValueError(f"故障分析记录不存在: {analysis_id}")
    if not item.result_json or not item.result_json.get("diagnosis"):
        raise ValueError(f"故障分析记录 {analysis_id} 无判别结果，请先执行判别")

    from .fault_diagnosis_report import generate_report

    settings = get_settings()
    vfs_root = Path(settings.file_vfs_root)
    analysis_dir = vfs_root / "fault_analysis" / analysis_id
    analysis_dir.mkdir(parents=True, exist_ok=True)
    output_path = analysis_dir / "report.docx"
    
    result = item.result_json.get("diagnosis", {})
    if template_path is None:
        # 默认模板路径：api/app/templates/综合判别报告模板.docx
        default_template = Path(__file__).resolve().parent.parent / "templates" / "综合判别报告模板.docx"
        template_path = default_template if default_template.exists() else None
    
    generate_report(result, output_path, template_path=template_path, front_only=False)
    return output_path
