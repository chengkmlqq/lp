from __future__ import annotations

import json
import shutil
import logging
import subprocess
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
from .minio_storage import (
    FAULT_ANALYSIS_PREFIX,
    build_fault_analysis_matlab_output_key,
    build_fault_analysis_output_key,
    download_object_to_file,
    put_object,
)

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


def _upload_file_ref(value: Any) -> str | None:
    if isinstance(value, Mapping):
        raw = value.get("key") or value.get("path")
        return str(raw) if raw else None
    if isinstance(value, str):
        return value
    return None


def _is_fault_analysis_object_key(value: Any) -> bool:
    ref = _upload_file_ref(value)
    return bool(ref and ref.startswith(FAULT_ANALYSIS_PREFIX))


def _object_filename(key: str) -> str:
    return Path(key).name or "input.bin"


def _resolve_upload_ref(upload_value: Any) -> str | None:
    if isinstance(upload_value, Mapping):
        candidate = upload_value.get("key") or upload_value.get("path")
        return str(candidate) if candidate else None
    if upload_value is None:
        return None
    return str(upload_value)


def _materialize_upload_value(value: Any, field: str, input_dir: Path) -> Any:
    if _is_fault_analysis_object_key(value):
        key = _upload_file_ref(value)
        assert key is not None
        target = input_dir / field / _object_filename(key)
        return download_object_to_file(key, target).as_posix()
    if isinstance(value, list):
        return [_materialize_upload_value(item, field, input_dir) for item in value]
    if isinstance(value, Mapping):
        ref = _upload_file_ref(value)
        return ref if ref is not None else value
    return value


def _materialize_upload_files(upload_files: Mapping[str, Any], input_dir: Path) -> dict[str, Any]:
    return {
        field: _materialize_upload_value(value, field, input_dir)
        for field, value in upload_files.items()
    }


def _legacy_or_local_path(value: Any) -> Path | None:
    ref = _resolve_upload_ref(value)
    if not ref:
        return None
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = Path(get_settings().file_vfs_root) / ref
    return candidate.resolve() if candidate.is_file() else None


def _archive_file(analysis_id: str, path: Path, *, matlab: bool = False, content_type: str | None = None) -> str:
    key = (
        build_fault_analysis_matlab_output_key(analysis_id, path.name)
        if matlab
        else build_fault_analysis_output_key(analysis_id, path.name)
    )
    return put_object(key, path.read_bytes(), content_type=content_type or "application/octet-stream")


def _archive_matlab_run_directory(analysis_id: str, run_output_dir: Path) -> list[str]:
    """递归归档 MATLAB 引擎单次运行的全量产物目录到 Output/matlab/<run_id>/。

    保持产物目录内的原始相对路径结构（含嵌套子目录），返回全部对象 key 清单；
    目录不存在或为空时返回空列表。
    """
    keys: list[str] = []
    if not run_output_dir.is_dir():
        return keys
    run_id = run_output_dir.name
    for path in sorted(run_output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(run_output_dir)
        sub_dir = run_id if rel.parent.as_posix() == "." else f"{run_id}/{rel.parent.as_posix()}"
        key = build_fault_analysis_matlab_output_key(analysis_id, path.name, sub_dir=sub_dir)
        keys.append(put_object(key, path.read_bytes()))
    return keys


def _archive_debug_inputs(
    analysis_id: str,
    *,
    fault_raw: Mapping[str, Any],
    lightning_raw: Mapping[str, Any],
    ledger_rows: Sequence[Mapping[str, Any]],
    traveling_wave_records: Sequence[Mapping[str, Any]],
) -> list[str]:
    """把判别中间输入各自物化一份 JSON 归档到 Output/debug/，便于复现与排查。

    返回全部对象 key 清单；任一输入为空序列/空字典时仍落一份空结构，保证清单可对齐。
    """
    keys: list[str] = []
    payloads: list[tuple[str, Any]] = [
        ("fault_raw", fault_raw),
        ("lightning_raw", lightning_raw),
        ("ledger_rows", ledger_rows),
        ("traveling_wave_records", traveling_wave_records),
    ]
    for name, value in payloads:
        key = build_fault_analysis_output_key(analysis_id, f"{name}.json", sub_dir="debug")
        data = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        keys.append(put_object(key, data, content_type="application/json"))
    return keys


def _finalize_artifacts(
    result_json: dict[str, Any],
    *,
    analysis_id: str,
    wave_model_path: Path | None,
    matlab_output_dir: Path | None,
    debug_inputs: tuple[
        Mapping[str, Any], Mapping[str, Any], Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]
    ]
    | None = None,
) -> dict[str, Any]:
    """构建最终 result_json：补全 artifacts 产物清单（result.json + MATLAB 全量 + debug）。

    所有归档必须在该函数内完成，保证 run_fault_diagnosis 与
    run_fault_diagnosis_with_progress 两条执行路径的归档逻辑完全一致。
    """
    artifacts = dict(result_json.get("artifacts") or {})
    result_key = build_fault_analysis_output_key(analysis_id, "result.json")
    artifacts["result_json"] = result_key
    if matlab_output_dir is not None:
        matlab_keys = _archive_matlab_run_directory(analysis_id, matlab_output_dir)
        if matlab_keys:
            artifacts["matlab_outputs"] = matlab_keys
            # prediction 已含在全量归档内，直接以 run_id 作用域的 key 引用（与评审清单结构一致），
            # 避免顶层额外上传一份重复的 wave_module_prediction.txt。
            if wave_model_path is not None and wave_model_path.is_file():
                prediction_rel = wave_model_path.relative_to(matlab_output_dir)
                prediction_sub = (
                    matlab_output_dir.name
                    if prediction_rel.parent.as_posix() == "."
                    else f"{matlab_output_dir.name}/{prediction_rel.parent.as_posix()}"
                )
                artifacts["matlab_wave_prediction"] = build_fault_analysis_matlab_output_key(
                    analysis_id, wave_model_path.name, sub_dir=prediction_sub
                )
    elif wave_model_path is not None and wave_model_path.is_file():
        # 防御分支：全量目录缺失但 prediction 文件仍存在时，保持单文件归档。
        artifacts["matlab_wave_prediction"] = _archive_file(
            analysis_id,
            wave_model_path,
            matlab=True,
            content_type="text/plain",
        )
    if debug_inputs is not None:
        fault_raw, lightning_raw, ledger_rows, traveling_wave_records = debug_inputs
        debug_keys = _archive_debug_inputs(
            analysis_id,
            fault_raw=fault_raw,
            lightning_raw=lightning_raw,
            ledger_rows=ledger_rows,
            traveling_wave_records=traveling_wave_records,
        )
        if debug_keys:
            artifacts["debug_outputs"] = debug_keys
    result_json["artifacts"] = artifacts
    return result_json


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
    return _legacy_or_local_path(upload_files.get(field))


def _resolve_upload_files(upload_files: Mapping[str, Any], field: str) -> list[Path]:
    """解析字段路径；行波允许单个相对路径或相对路径列表。"""
    relative = upload_files.get(field)
    if not relative:
        return []
    if isinstance(relative, str):
        candidates = [relative]
    elif isinstance(relative, list):
        candidates = [_resolve_upload_ref(item) or str(item) for item in relative if item]
    else:
        candidates = [_resolve_upload_ref(relative) or str(relative)]
    resolved: list[Path] = []
    for item in candidates:
        candidate = _legacy_or_local_path(item)
        if candidate is not None:
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
) -> tuple[Path | None, Path | None]:
    """可插拔行波增强：优先调用 MATLAB Runtime 编译产物，不可用时返回 (None, None)。

    编译产物约定（与判别系统交付版 RunWaveAnalysisModule 输入/输出一致）：
    - 位置：settings.fault_diag_matlab_compiled_dir（环境变量 FAULT_DIAG_MATLAB_COMPILED_DIR）
    - 可执行入口：目录下 RunWaveAnalysisModule（Linux 上由 mcc 编译，内嵌 MATLAB Runtime）
    - 输入：暂存目录（行波数据文件 + 录波故障相X.txt + 幅值XkA_耐雷水平YkA.txt）
    - 输出：输出根目录/最新结果路径.txt -> 本次输出目录/wave_module_prediction.txt
    - 返回值：成功时返回 (prediction_path, output_dir_path)，其中 output_dir_path 即本次
      运行的全部引擎产物目录（module_runs/<run_id>），供调用方整体归档到 MinIO。

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
        # 流式读取 MATLAB stdout/stderr 并逐行转发到任务监控日志：TaskLogCapture 会实时写入
        # Redis Stream（前端 SSE 可见），任务结束后全量上传 MinIO logs/{task_id}.log。
        proc = subprocess.Popen(
            [*command, str(staged_input.resolve()), str(output_root.resolve())],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并两流，统一逐行转发
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        try:
            for line in proc.stdout:  # 逐行实时
                logger.info("[MATLAB] %s", line.rstrip())
            returncode = proc.wait(timeout=600)  # 保留原超时语义
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.error("Fault diagnosis MATLAB timed out after 600s for %s", analysis_id)
            return None, None
    except Exception:
        logger.exception("Fault diagnosis MATLAB process failed for %s", analysis_id)
        return None, None

    latest_file = output_root / "最新结果路径.txt"
    if returncode != 0 or not latest_file.is_file():
        logger.warning(
            "Fault diagnosis MATLAB returned no result for %s: returncode=%s latest_file=%s",
            analysis_id,
            returncode,
            latest_file.is_file(),
        )
        return None, None
    latest_output = Path(latest_file.read_text(encoding="utf-8-sig").strip())
    prediction = latest_output / "wave_module_prediction.txt"
    if not prediction.is_file():
        logger.warning("Fault diagnosis MATLAB prediction file missing for %s: %s", analysis_id, prediction)
        return None, None
    logger.info("Fault diagnosis MATLAB completed for %s: prediction=%s", analysis_id, prediction)
    return prediction, latest_output


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


# ---------------------------------------------------------------------------
# 章节（sections）富结构：页面渲染与 docx 生成共用同一份数据。
# 新增 type:"table" 内容项，用于输出页面详情页与下载 docx 的 8 张结构化表。
# 该逻辑与 fault_diagnosis_report.py 的拼表逻辑保持字段一致，避免长期漂移。


def _lazy_report_helpers() -> dict[str, Any]:
    """惰加载 fault_diagnosis_report 的纯函数，避免在服务导入时强制加载 python-docx。"""
    from . import fault_diagnosis_report as _report

    return {
        "display": _report.display,
        "format_number": _report.format_number,
        "value_with_unit": _report.value_with_unit,
        "has_value": _report.has_value,
        "safe_get": _report.safe_get,
        "usable_text": _report.usable_text,
        "normalize_phase": _report.normalize_phase,
        "normalize_fault_phase_code": _report.normalize_fault_phase_code,
        "report_identifier": _report.report_identifier,
        "wave_fault_conclusion": _report.wave_fault_conclusion,
        "fused_fault_conclusion": _report.fused_fault_conclusion,
        "effective_review_decision": _report.effective_review_decision,
        "recording_phase_sentence": _report.recording_phase_sentence,
        "lightning_location_conclusion": _report.lightning_location_conclusion,
        "wave_initial_type_detail": _report.wave_initial_type_detail,
        "wave_review_summary_sentence": _report.wave_review_summary_sentence,
        "status_display": _report.status_display,
        "resistance_sentence": _report.resistance_sentence,
        "actual_sources": _report.actual_sources,
        "wave_process_summary_sentence": _report.wave_process_summary_sentence,
        "wave_initial_review_sentence": _report.wave_initial_review_sentence,
    }


def _kv_table(title: str, rows: Sequence[Sequence[Any]], key_head: str = "项目", value_head: str = "内容") -> dict[str, Any]:
    """构建 2×N 键值对布局的表格内容项（对应 docx 的 4 列「项目/内容/项目/内容」布局）。"""
    columns = [key_head, value_head, key_head, value_head]
    return {
        "type": "table",
        "layout": "key_value",
        "title": title,
        "columns": columns,
        "rows": [[str(cell) for cell in row] for row in rows],
    }


def _grid_table(title: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """构建多列表格内容项。"""
    return {
        "type": "table",
        "layout": "grid",
        "title": title,
        "columns": list(columns),
        "rows": [[str(cell) for cell in row] for row in rows],
    }


def _table1_overview(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表1 故障分析总览（2×2 键值对布局）。"""
    display = report["display"]
    report_identifier = report["report_identifier"]
    normalize_phase = report["normalize_phase"]
    wave_fault_conclusion = report["wave_fault_conclusion"]
    fused_fault_conclusion = report["fused_fault_conclusion"]
    effective_review_decision = report["effective_review_decision"]

    inputs = diag.get("inputs", {})
    fault = inputs.get("fault_record", {})
    lightning = inputs.get("lightning", {})
    ground = diag.get("ground_fault_summary", {})
    resistance = diag.get("transition_resistance", {})
    location = diag.get("fault_location", {})
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line_name = fault.get("line_name") or lightning.get("line_name")
    station = fault.get("station") if report["usable_text"](fault.get("station")) else "未提供"
    phase = normalize_phase(fault.get("fault_phase")) or "未提供"
    resistance_category = (
        "不适用"
        if resistance.get("status") == "not_applicable"
        else display(resistance.get("category_report_text"), "无法计算")
    )
    conclusion = display(ground.get("conclusion"), "待复核")
    rows = [
        ["报告编号", report_identifier(diag), "生成时间", generated_at],
        ["故障线路", display(line_name), "故障时刻", display(fault.get("fault_time"))],
        ["录波站", station, "故障相", phase],
        ["故障性质", conclusion, "接地类型", resistance_category],
        ["综合定位", display(location.get("result_text")), "雷击原因", fused_fault_conclusion(diag)],
        ["行波结论", wave_fault_conclusion(diag), "总体状态", str(effective_review_decision(diag))],
    ]
    return _kv_table("表1 故障分析总览", rows)


def _table2_location_sources(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
    """表2 定位信息来源（3 列：定位来源 / 定位结果 / 对应杆塔或区段）。"""
    display = report["display"]
    format_number = report["format_number"]
    location = diag.get("fault_location", {})
    rows = []
    for item in location.get("sources", []):
        if not item.get("available"):
            continue
        distance = item.get("distance_km")
        distance_text = (
            f"{format_number(distance)} km" if report["has_value"](distance) else "位置记录可用"
        )
        rows.append([display(item.get("label")), distance_text, display(item.get("tower"))])
    columns = ["定位来源", "定位结果", "对应杆塔/区段"]
    return _grid_table("表2 定位信息来源", columns, rows) if rows else None


def _table3_wave_process(
    diag: Mapping[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """表3 行波判别过程（2 列：项目 / 结果）。"""
    display = report["display"]
    format_number = report["format_number"]
    wave = diag.get("traveling_wave_analysis", {})
    model = wave.get("model_result", {})
    review = wave.get("fault_phase_review", {})
    active = review.get("initial_wave_active_phases") or model.get("active_phases")
    if isinstance(active, (list, tuple)) and not isinstance(active, str):
        active = "/".join(str(item) for item in active)
    initial_phase = model.get("main_phase") or review.get("initial_wave_main_phase")
    phase_display = (
        f"行波判别故障相{initial_phase}、候补故障相{display(active)}"
        if report["has_value"](initial_phase) or report["has_value"](active)
        else "行波模型未输出可用的判别故障相或候补故障相信息"
    )
    lightning_score = model.get("ln_lightning_score")
    non_lightning_score = model.get("ln_non_lightning_score")
    score_text = (
        f"模型判断雷击概率{format_number(float(lightning_score) * 100, 2)}%，"
        f"非雷击概率{format_number(float(non_lightning_score) * 100, 2)}%"
        if report["has_value"](lightning_score) and report["has_value"](non_lightning_score)
        else "雷击与非雷击概率未提供"
    )
    fr_probability_text = report["wave_fr_probability_sentence"](model)
    initial_basis = (
        report["wave_ln_basis_sentence"](wave, model).rstrip("。；")
        + report["wave_fr_basis_sentence"](wave, model).rstrip("。；")
    )
    candidate_text = report["wave_candidate_types_display"](model.get("candidate_types"))
    review_result = report["wave_review_result_sentence"](wave, model, review)
    rows = [
        ["初判结果", f"{display(wave.get('initial_classification'))}；{phase_display}；{score_text}；{fr_probability_text}"],
        ["初判依据", initial_basis],
        ["允许候选", candidate_text],
        ["修正/复核结果", review_result],
        ["最终采用结果", report["wave_fault_conclusion"](diag)],
    ]
    return _grid_table("表3 行波判别过程", ["项目", "结果"], rows)


def _table4_fusion(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表4 故障原因融合分析（2 列：信息来源 / 结论）。"""
    display = report["display"]
    wave = diag.get("traveling_wave_analysis", {})
    rows = [
        ["录波故障相", report["recording_phase_sentence"](diag)],
        ["雷电定位", report["lightning_location_conclusion"](diag)],
        [
            "分布式行波",
            f"行波初判为{display(wave.get('initial_classification'))}（{report['wave_initial_type_detail'](diag)}）",
        ],
        ["融合结论", report["wave_review_summary_sentence"](diag)],
    ]
    return _grid_table("表4 故障原因融合分析", ["信息来源", "结论"], rows)


def _table5_recording(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表A.1 录波故障信息（2×2 键值对布局）。"""
    display = report["display"]
    value_with_unit = report["value_with_unit"]
    inputs = diag.get("inputs", {})
    fault = inputs.get("fault_record", {})
    lightning = inputs.get("lightning", {})
    paths = diag.get("source_paths", {})
    line_name = fault.get("line_name") or lightning.get("line_name")
    zero_current = fault.get("zero_sequence_current")
    record_distance = fault.get("fault_distance_km") or lightning.get("recording_distance_km")
    rows = [
        ["故障时刻", display(fault.get("fault_time")), "故障线路", display(line_name)],
        [
            "故障相",
            report["normalize_fault_phase_code"](fault.get("fault_phase")) or "未提供",
            "故障持续时间",
            value_with_unit(fault.get("duration_ms"), "ms"),
        ],
        ["重合闸情况", display(fault.get("reclosing")), "故障相电压", display(fault.get("phase_voltage"))],
        [
            "故障相电流",
            display(fault.get("phase_current")),
            "提取零序电流",
            f"{display(zero_current)}（按3I₀/I₀双口径核对）",
        ],
        ["最大零序电流", display(zero_current), "零序补偿系数", display(fault.get("zero_sequence_compensation_k"))],
        ["故障测距", value_with_unit(record_distance, "km"), "原始文件", display(paths.get("fault"))],
    ]
    return _kv_table("表A.1 录波故障信息", rows)


def _table6_lightning(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表A.2 雷电流及定位信息（2×2 键值对布局）。"""
    display = report["display"]
    value_with_unit = report["value_with_unit"]
    inputs = diag.get("inputs", {})
    lightning = inputs.get("lightning", {})
    paths = diag.get("source_paths", {})
    rows = [
        ["雷电流幅值", value_with_unit(lightning.get("current_ka"), "kA"), "定位时间", display(lightning.get("location_time"))],
        [
            "最近杆塔",
            display(lightning.get("nearest_tower")),
            "录波测距",
            value_with_unit(lightning.get("recording_distance_km"), "km"),
        ],
        [
            "行波测距",
            value_with_unit(lightning.get("traveling_wave_distance_km"), "km"),
            "定位距离",
            value_with_unit(lightning.get("distance_to_line_km"), "km"),
        ],
        ["输入文件", display(paths.get("lightning")), "数据状态", "已提供" if lightning else "未提供"],
    ]
    return _kv_table("表A.2 雷电流及定位信息", rows)


def _table7_ledger(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表A.3 线路台账匹配信息（2×2 键值对布局）。"""
    display = report["display"]
    value_with_unit = report["value_with_unit"]
    inputs = diag.get("inputs", {})
    paths = diag.get("source_paths", {})
    ledger = inputs.get("line_ledger", {})
    record = ledger.get("record", {}) if ledger.get("matched") else {}
    rows = [
        [
            "匹配线路/杆塔",
            f"{display(record.get('line_name'))} / {display(record.get('tower_no'))}",
            "塔形",
            display(record.get("tower_shape")),
        ],
        ["地形", display(record.get("terrain")), "海拔", value_with_unit(record.get("elevation_m"), "m")],
        [
            "绝缘子串长",
            value_with_unit(record.get("insulator_length_m"), "m"),
            "接地电阻",
            value_with_unit(record.get("ground_resistance_ohm"), "Ω"),
        ],
        [
            "绕击耐雷水平",
            value_with_unit(record.get("shielding_failure_withstand_ka"), "kA"),
            "反击耐雷水平",
            value_with_unit(record.get("backflashover_withstand_ka"), "kA"),
        ],
        ["风险评估等级", display(record.get("lightning_risk_level")), "台账文件", display(paths.get("ledger"))],
        [
            "匹配状态",
            "已匹配" if ledger.get("matched") else "未匹配",
            "匹配说明",
            display(ledger.get("diagnostic") or ledger.get("reason") or "线路及杆塔匹配成功"),
        ],
    ]
    return _kv_table("表A.3 线路台账匹配信息", rows)


def _table8_wave_optical(diag: Mapping[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """表A.4 行波与光学监测信息（3 列：来源 / 主要输入 / 数据状态）。"""
    display = report["display"]
    safe_get = report["safe_get"]
    inputs = diag.get("inputs", {})
    wave = diag.get("traveling_wave_analysis", {})
    model = wave.get("model_result", {})
    wave_files = inputs.get("traveling_wave_files", [])
    wave_formats = "/".join(
        sorted(
            {
                Path(str(item.get("file_name") or "")).suffix.lstrip(".").upper()
                for item in wave_files
                if item.get("file_name")
            }
        )
    ) or "未提供"
    initial_phase = model.get("main_phase") or safe_get(wave, "fault_phase_review", "initial_wave_main_phase")
    wave_input = (
        f"初判：{display(wave.get('initial_classification'))}；"
        f"初判相：{display(initial_phase)}；"
        f"幅值信息：{report['translate_wave_text'](safe_get(wave, 'fault_phase_review', 'amplitude_band'))}；"
        f"格式：{wave_formats}"
    )
    optical = inputs.get("optical", {}) or {}
    optical_input = (
        f"位置：{display(optical.get('location') or optical.get('device_tower'))}；"
        f"现象/结论：{display(optical.get('result') or optical.get('conclusion'))}"
    ) if optical else "本次未提供光学监测数据"
    rows = [
        ["分布式行波", wave_input, "已提供" if wave_files else "未提供"],
        ["光学监测", optical_input, "已提供" if optical else "未提供"],
    ]
    return _grid_table("表A.4 行波与光学监测信息", ["来源", "主要输入", "数据状态"], rows)


def _build_tables(
    diag: Mapping[str, Any],
    *,
    risk_level: str,
    confidence: float | None,
    confidence_source: str,
) -> dict[str, Any]:
    """按 docx 8 张表的结构生成全部结构化表格内容项。"""
    from . import fault_diagnosis_report as _report

    extra_helpers = {
        "wave_fr_probability_sentence": _report.wave_fr_probability_sentence,
        "wave_candidate_types_display": _report.wave_candidate_types_display,
        "wave_review_result_sentence": _report.wave_review_result_sentence,
        "wave_ln_basis_sentence": _report.wave_ln_basis_sentence,
        "wave_fr_basis_sentence": _report.wave_fr_basis_sentence,
        "translate_wave_text": _report.translate_wave_text,
    }
    report = {**_lazy_report_helpers(), **extra_helpers}
    tables: dict[str, Any] = {}
    for name, builder in (
        ("table1", _table1_overview),
        ("table2", _table2_location_sources),
        ("table3", _table3_wave_process),
        ("table4", _table4_fusion),
        ("table5", _table5_recording),
        ("table6", _table6_lightning),
        ("table7", _table7_ledger),
        ("table8", _table8_wave_optical),
    ):
        item = builder(diag, report)
        if item is not None:
            tables[name] = item
    return tables


def _build_sections(
    diag: Mapping[str, Any],
    *,
    risk_level: str,
    confidence: float | None,
    confidence_source: str,
) -> list[dict[str, Any]]:
    """从判别结果生成 LP 详情页可渲染的 sections（与 docx 报告章节完全对齐）。

    章节标题约定（与 fault_diagnosis_report.generate_report 输出一致）：
      1 报告总览 | 2 接地故障及过渡电阻判别 | 3 故障定位 | 4 耐雷水平与雷击原因分析
      5 分布式行波分析与故障原因融合（5.1 / 5.2） | 6 总体状态与后续意见
      附表A 输入信息汇总（A.1~A.4）
    """
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

    tables = _build_tables(
        diag,
        risk_level=risk_level,
        confidence=confidence,
        confidence_source=confidence_source,
    )

    sections: list[dict[str, Any]] = []

    def text(value: Any) -> dict[str, Any]:
        return {"type": "text", "text": str(value)}

    # ---- 1 报告总览 ----
    phase = str(ground_summary.get("fault_phase") or fault.get("fault_phase") or "未知")
    conclusion = str(
        ground_summary.get("conclusion")
        or f"{phase}相{decision.get('fault_kind', '无法判定')}"
    )
    confidence_text = f"{confidence:.2f}%" if confidence is not None else "未计算"
    content: list[dict[str, Any]] = []
    if "table1" in tables:
        content.append(tables["table1"])
    content.extend(
        [
            text(f"接地判别结论：{conclusion}"),
            text(f"故障类型：{decision.get('fault_kind', '无法判定')}"),
            text(f"故障相别：{phase}"),
            text(f"综合置信度：{confidence_text}（来源：{confidence_source}）"),
            text(f"风险等级：{RISK_LEVEL_LABELS.get(risk_level, risk_level)}"),
        ]
    )
    recommendation_decision = str(recommendation.get("decision", "建议人工复核"))
    content.append(text(f"判别系统后续意见：{recommendation_decision}"))
    recommendation_reasons = recommendation.get("reasons", [])
    if recommendation_reasons:
        content.append({"type": "bullet", "items": [str(item) for item in recommendation_reasons]})
    sections.append({"title": "1 报告总览", "content": content})

    # ---- 2 接地故障及过渡电阻判别 ----
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
        sections.append({"title": "2 接地故障及过渡电阻判别", "content": content})
    else:
        sections.append(
            {
                "title": "2 接地故障及过渡电阻判别",
                "content": [
                    text(
                        f"过渡电阻：{'不适用（仅单相接地故障计算）' if resistance.get('status') == 'not_applicable' else '无法计算'}"
                    ),
                    *[{"type": "bullet", "items": [str(item) for item in resistance.get("warnings", [])]}],
                ],
            }
        )

    # ---- 3 故障定位 ----
    content = [text(f"综合故障位置：{fault_location.get('result_text', '无法定位')}")]
    for source in fault_location.get("sources", []):
        tower = source.get("tower")
        distance = source.get("distance_km")
        content.append(
            text(f"{source.get('label')}：{tower or '未提供'}{f'（测距 {distance} km）' if distance is not None else ''}")
        )
    if fault_location.get("evidence"):
        content.append({"type": "bullet", "items": [str(item) for item in fault_location.get("evidence", [])]})
    if "table2" in tables:
        content.append(tables["table2"])
    sections.append({"title": "3 故障定位", "content": content})

    # ---- 4 耐雷水平与雷击原因分析 ----
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
    sections.append({"title": "4 耐雷水平与雷击原因分析", "content": content})

    # ---- 5 分布式行波分析与故障原因融合（容器）----
    sections.append({"title": "5 分布式行波分析与故障原因融合", "content": []})

    # ---- 5.1 分布式行波分析 ----
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
    if "table3" in tables:
        content.append(tables["table3"])
    sections.append({"title": "5.1 分布式行波分析", "content": content})

    # ---- 5.2 故障原因融合 ----
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
    if "table4" in tables:
        content.append(tables["table4"])
    content.append({"type": "card", "text": f"后续意见：{recommendation.get('summary', '')}"})
    sections.append({"title": "5.2 故障原因融合", "content": content})

    # ---- 6 总体状态与后续意见 ----
    validation_issues = validation.get("issues", [])
    content = []
    if validation_issues:
        content.append(
            {
                "type": "bullet",
                "items": [f"【{item.get('severity', 'info')}】{item.get('message', '')}" for item in validation_issues],
            }
        )
    if not validation_issues:
        content.append(text("输入校验：无"))
    sections.append({"title": "6 总体状态与后续意见", "content": content})

    # ---- 附表A 输入信息汇总 ----
    sections.append({"title": "附表A 输入信息汇总", "content": []})

    # ---- A.1 录波故障信息 ----
    if "table5" in tables:
        sections.append({"title": "A.1 录波故障信息", "content": [tables["table5"]]})

    # ---- A.2 雷电流及定位信息 ----
    if "table6" in tables:
        sections.append({"title": "A.2 雷电流及定位信息", "content": [tables["table6"]]})

    # ---- A.3 线路台账匹配信息 ----
    if "table7" in tables:
        sections.append({"title": "A.3 线路台账匹配信息", "content": [tables["table7"]]})

    # ---- A.4 行波与光学监测信息 ----
    if "table8" in tables:
        sections.append({"title": "A.4 行波与光学监测信息", "content": [tables["table8"]]})

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

    run_dir = Path(tempfile.mkdtemp(prefix=f"fault-analysis-{analysis_id}-"))
    try:
        original_upload_files = item.upload_files or {}
        materialized_upload_files = _materialize_upload_files(original_upload_files, run_dir / "Input")
        item.upload_files = materialized_upload_files
        try:
            fault_raw, lightning_raw, ledger_rows, traveling_wave_records, input_warnings = _collect_inputs(
                item, db=db
            )
        finally:
            item.upload_files = original_upload_files
        manual = build_manual_input(item)
        analysis_dir = run_dir / "Output"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        upload_files = materialized_upload_files
        traveling_wave_paths = _resolve_upload_files(upload_files, "traveling_wave_file")
        logger.info(
            "Fault diagnosis inputs for %s: upload_fields=%s traveling_wave_file_count=%d",
            analysis_id,
            sorted(upload_files),
            len(traveling_wave_paths),
        )

        wave_model_path, matlab_output_dir = _try_matlab_wave_enhancement(
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
            source_paths=source_paths,
        )
        mapped = map_result_to_record(diag, item, input_warnings=input_warnings)
        result_json = dict(mapped["result_json"])
        result_json["upload_files"] = dict(original_upload_files)
        result_json = _finalize_artifacts(
            result_json,
            analysis_id=analysis_id,
            wave_model_path=wave_model_path,
            matlab_output_dir=matlab_output_dir,
            debug_inputs=(fault_raw, lightning_raw, ledger_rows, traveling_wave_records),
        )
        result_key = build_fault_analysis_output_key(analysis_id, "result.json")
        payload = json.dumps(result_json, ensure_ascii=False, default=str).encode("utf-8")
        put_object(result_key, payload, content_type="application/json")
        mapped["result_json"] = result_json

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
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def run_fault_diagnosis_with_progress(
    db: Session,
    analysis_id: str,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """执行一次完整判别，并在各阶段通过 progress_callback 上报进度。

    进度分段：
      10%  - 开始收集输入
      30%  - 输入收集完成
      50%  - 行波增强完成 / 跳过
      80%  - 综合判别完成
      85%  - 结果回填完成
    """
    item = get_analysis_by_id(db, analysis_id)
    if item is None:
        raise ValueError(f"故障分析记录不存在: {analysis_id}")

    now = utcnow()
    item.status = "processing"
    item.progress = 10
    item.update_date = now
    item.update_user = "system"
    db.commit()
    if progress_callback:
        progress_callback(10, "processing")

    run_dir = Path(tempfile.mkdtemp(prefix=f"fault-analysis-{analysis_id}-"))
    try:
        if progress_callback:
            progress_callback(15, "processing")
        original_upload_files = item.upload_files or {}
        materialized_upload_files = _materialize_upload_files(original_upload_files, run_dir / "Input")
        item.upload_files = materialized_upload_files
        try:
            fault_raw, lightning_raw, ledger_rows, traveling_wave_records, input_warnings = _collect_inputs(
                item, db=db
            )
        finally:
            item.upload_files = original_upload_files
        if progress_callback:
            progress_callback(30, "processing")

        manual = build_manual_input(item)
        analysis_dir = run_dir / "Output"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        upload_files = materialized_upload_files
        traveling_wave_paths = _resolve_upload_files(upload_files, "traveling_wave_file")
        logger.info(
            "Fault diagnosis inputs for %s: upload_fields=%s traveling_wave_file_count=%d",
            analysis_id,
            sorted(upload_files),
            len(traveling_wave_paths),
        )

        wave_model_path, matlab_output_dir = _try_matlab_wave_enhancement(
            analysis_id,
            analysis_dir,
            fault_raw,
            lightning_raw,
            ledger_rows,
            traveling_wave_records,
            manual,
        )
        wave_model_result = load_wave_model_result(wave_model_path) if wave_model_path is not None else None
        if progress_callback:
            progress_callback(50, "processing")

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
            source_paths=source_paths,
        )
        if progress_callback:
            progress_callback(80, "processing")

        mapped = map_result_to_record(diag, item, input_warnings=input_warnings)
        result_json = dict(mapped["result_json"])
        result_json["upload_files"] = dict(original_upload_files)
        result_json = _finalize_artifacts(
            result_json,
            analysis_id=analysis_id,
            wave_model_path=wave_model_path,
            matlab_output_dir=matlab_output_dir,
            debug_inputs=(fault_raw, lightning_raw, ledger_rows, traveling_wave_records),
        )
        result_key = build_fault_analysis_output_key(analysis_id, "result.json")
        payload = json.dumps(result_json, ensure_ascii=False, default=str).encode("utf-8")
        put_object(result_key, payload, content_type="application/json")
        mapped["result_json"] = result_json

        item.status = "completed"
        item.progress = 85
        item.risk_level = mapped["risk_level"]
        item.fault_type = mapped["fault_type"]
        item.fault_phase = mapped["fault_phase"]
        item.confidence = mapped["confidence"]
        item.result_json = mapped["result_json"]
        item.update_date = utcnow()
        item.update_user = "system"
        db.commit()
        if progress_callback:
            progress_callback(85, "processing")

        return mapped["result_json"]
    except Exception as exc:
        item.status = "failed"
        item.progress = 0
        item.result_json = dict(item.result_json or {})
        item.result_json["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        item.update_date = utcnow()
        item.update_user = "system"
        db.commit()
        if progress_callback:
            progress_callback(0, "failed")
        raise
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


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
    """生成故障分析 Word 报告并归档到 MinIO Output。"""
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

    if template_path is None:
        # 默认模板路径：api/app/templates/综合判别报告模板.docx
        default_template = Path(__file__).resolve().parent.parent / "templates" / "综合判别报告模板.docx"
        template_path = default_template if default_template.exists() else None

    # 传入完整 result_json（含 sections 富结构），使报告生成直接消费页面同源数据。
    generate_report(item.result_json, output_path, template_path=template_path, front_only=False)
    try:
        report_key = _archive_file(
            analysis_id,
            output_path,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        item.result_json = dict(item.result_json or {})
        artifacts = dict(item.result_json.get("artifacts") or {})
        artifacts["report_docx"] = report_key
        item.result_json["artifacts"] = artifacts
        item.update_date = utcnow()
        item.update_user = "system"
        db.commit()
        # 保持 MinIO 侧 result.json 与本地 result_json 一致，使 artifacts 清单（含 report_docx）
        # 在文件管理/清单查询时可见。
        result_key = build_fault_analysis_output_key(analysis_id, "result.json")
        payload = json.dumps(item.result_json, ensure_ascii=False, default=str).encode("utf-8")
        put_object(result_key, payload, content_type="application/json")
    except Exception:
        logger.exception("Fault diagnosis report archive failed for %s", analysis_id)
    return output_path
