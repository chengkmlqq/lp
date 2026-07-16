from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.fl_analysis import FlAnalysisJob, FlAnalysisTowerSnapshot
from .wine_probe import probe_wine_binary


settings = get_settings()
ENCODING_CANDIDATES = ("utf-8-sig", "gb18030", "gbk", "utf-8")
FEATURE_LINE_SPLIT = re.compile(r"[,\t|]")
LOG_MAX_CHARS = 200_000
DEFAULT_JSON_MARKERS = ("FL_ANALYSIS_RESULT_BEGIN", "FL_ANALYSIS_RESULT_END")
CALCULATION_MODE_ALIASES = {
    "counterstrike": "fanji",
    "fanji": "fanji",
    "normal": "fanji",
    "raoji": "raoji1",
    "shielding": "raoji1",
    "raoji1": "raoji1",
    "raoji2": "raoji2",
    "tongtiao": "raoji3",
    "raoji3": "raoji3",
}
DEFAULT_EGM_RESULT_KEY_MAP = {
    "绕击跳闸率": "shielding_trip_rate",
    "shielding_trip_rate": "shielding_trip_rate",
    "trip_rate": "shielding_trip_rate",
}
LEGACY_RESULT_KEY_MAP = {
    "反击耐雷水平": "counterstrike_withstand_ka",
    "反击跳闸率": "counterstrike_trip_rate",
    "绕击耐雷水平": "shielding_withstand_ka",
    "绕击跳闸率": "shielding_trip_rate",
    "雷击风险等级": "risk_grade",
    "风险等级": "risk_grade",
    "单相闪络相": "flashover_phase",
    "闪络相": "flashover_phase",
    "主导相组": "dominant_phase_set",
    "同跳跳闸率": "counterstrike_trip_rate",
}
NUMERIC_RESULT_KEYS = {
    "counterstrike_withstand_ka",
    "counterstrike_trip_rate",
    "shielding_withstand_ka",
    "shielding_trip_rate",
    "score",
    "risk_grade",
}


@dataclass(slots=True)
class LegacyFeatureBinding:
    name: str
    path: str
    offset: int
    length: int
    file: str | None = None
    format_spec: str | None = None
    default: Any = None
    required: bool = True
    align: str = "right"


@dataclass(slots=True)
class ResolvedLegacyAtpJob:
    adapter: str
    engine_mode: str
    timeout_seconds: int
    legacy_root: Path
    template_root: Path
    template_dir: Path
    run_root: Path
    calculation_mode: str
    template_identifier: str
    use_egm: bool
    model_file: str | None
    feature_bindings: list[LegacyFeatureBinding]
    result_file: str | None
    egm_result_file: str | None
    egm_subdir: str
    engine_args: list[str]
    egm_args: list[str]
    egm_input_file: str | None
    resolved_tpbig: str | None
    resolved_rjtzl: str | None
    minimum_model_size_bytes: int
    model_required_keywords: list[str]
    contract: dict[str, Any]


@dataclass(slots=True)
class LegacyAtpExecutionResult:
    result_json: dict[str, Any]
    engine_command: str
    working_dir: str
    stdout_text: str | None
    stderr_text: str | None


def resolve_legacy_atp_job(
    *,
    adapter_config_json: dict[str, Any],
    execution_options: dict[str, Any] | None = None,
) -> ResolvedLegacyAtpJob:
    config = dict(adapter_config_json or {})
    normalized_execution_options = dict(execution_options or {})

    engine_mode = _resolve_engine_mode()
    timeout_seconds = _resolve_timeout(_coerce_positive_int(config.get("timeout_seconds")))
    legacy_root = _resolve_path_under_allowed_root(
        str(config.get("legacy_root") or config.get("model_root") or settings.atp_legacy_root),
        field_name="legacy_root",
        must_exist=True,
    )
    template_root = _resolve_path_under_allowed_root(
        str(config.get("template_root") or settings.atp_template_root or legacy_root),
        field_name="template_root",
        must_exist=True,
    )
    run_root = _resolve_path_under_allowed_root(
        str(config.get("run_root") or settings.atp_run_root),
        field_name="run_root",
        must_exist=False,
    )
    calculation_mode = _resolve_calculation_mode(config, normalized_execution_options)
    template_identifier = _resolve_template_identifier(config, normalized_execution_options, calculation_mode)
    template_dir = _resolve_template_directory(
        template_root=template_root,
        template_identifier=template_identifier,
    )
    use_egm = _coerce_bool(
        config.get("use_egm"),
        default=_infer_use_egm(config=config, execution_options=normalized_execution_options),
    )
    model_file = _discover_model_file(template_dir, raw_path=config.get("model_file") or config.get("entry_file"))
    result_file = _normalize_optional_path(config.get("result_file"))
    egm_result_file = _normalize_optional_path(config.get("egm_result_file")) or result_file
    egm_subdir = str(config.get("egm_subdir") or settings.atp_egm_subdir).strip() or settings.atp_egm_subdir
    egm_input_file = _normalize_optional_path(config.get("egm_input_file"))

    feature_bindings = _load_feature_bindings(
        template_dir=template_dir,
        raw_bindings=config.get("feature_bindings") or config.get("parameter_bindings"),
        raw_setting_file=config.get("feature_setting_file") or config.get("feature_file"),
    )
    minimum_model_size_bytes = _coerce_positive_int(config.get("minimum_model_size_bytes")) or 1024
    model_required_keywords = [
        str(item).strip()
        for item in list(config.get("model_required_keywords") or config.get("required_keywords") or [])
        if str(item).strip()
    ]

    resolved_tpbig = _resolve_runtime_executable(
        raw_path=str(config.get("tpbig_exe") or settings.atp_tpbig_executable),
        field_name="tpbig_exe",
        must_exist=not use_egm,
    )
    resolved_rjtzl = _resolve_runtime_executable(
        raw_path=str(config.get("rjtzl_exe") or settings.atp_rjtzl_executable),
        field_name="rjtzl_exe",
        must_exist=use_egm,
    )

    if use_egm:
        egm_dir = (template_dir / egm_subdir).resolve(strict=False)
        if not egm_dir.is_relative_to(template_dir.resolve(strict=False)) or not egm_dir.is_dir():
            raise RuntimeError(f"EGM子目录不存在: {egm_subdir}")
        if not resolved_rjtzl:
            raise RuntimeError("rjtzl.exe不存在")
    else:
        if not resolved_tpbig:
            raise RuntimeError("tpbig.exe不存在")
        if model_file is None:
            raise RuntimeError("ATP模型文件不存在")

    contract = {
        key: value
        for key, value in config.items()
        if key
        in {
            "result_format",
            "result_labels",
            "result_json_pointer",
            "result_key_map",
            "stdout_json_markers",
        }
    }
    result_key_map = _read_object(contract.get("result_key_map"))
    if use_egm:
        contract["result_key_map"] = {**DEFAULT_EGM_RESULT_KEY_MAP, **result_key_map}
        if "result_format" not in contract:
            contract["result_format"] = "key_value"

    return ResolvedLegacyAtpJob(
        adapter="legacy_atp",
        engine_mode=engine_mode,
        timeout_seconds=timeout_seconds,
        legacy_root=legacy_root,
        template_root=template_root,
        template_dir=template_dir,
        run_root=run_root,
        calculation_mode=calculation_mode,
        template_identifier=template_identifier,
        use_egm=use_egm,
        model_file=model_file,
        feature_bindings=feature_bindings,
        result_file=result_file,
        egm_result_file=egm_result_file,
        egm_subdir=egm_subdir,
        engine_args=_normalize_args(config.get("engine_args") or config.get("extra_args")),
        egm_args=_normalize_args(config.get("egm_args")),
        egm_input_file=egm_input_file,
        resolved_tpbig=resolved_tpbig,
        resolved_rjtzl=resolved_rjtzl,
        minimum_model_size_bytes=minimum_model_size_bytes,
        model_required_keywords=model_required_keywords,
        contract=contract,
    )


def execute_legacy_atp_tower_analysis(
    resolved_job: ResolvedLegacyAtpJob,
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> LegacyAtpExecutionResult:
    context = _build_template_context(
        job=job,
        snapshot=snapshot,
        execution_options=execution_options,
        baseline_result=baseline_result,
    )
    run_dir = _prepare_run_directory(resolved_job=resolved_job, job=job, snapshot=snapshot)
    shutil.copytree(resolved_job.template_dir, run_dir, dirs_exist_ok=True)

    if resolved_job.feature_bindings:
        if resolved_job.model_file is None:
            raise RuntimeError("ATP模型文件不存在")
        apply_feature_bindings(
            run_dir=run_dir,
            model_file=resolved_job.model_file,
            bindings=resolved_job.feature_bindings,
            context=context,
            minimum_model_size_bytes=resolved_job.minimum_model_size_bytes,
            required_keywords=resolved_job.model_required_keywords,
        )

    if not resolved_job.use_egm:
        if resolved_job.model_file is None or not resolved_job.resolved_tpbig:
            raise RuntimeError("tpbig.exe不存在或ATP模型文件不存在")
        input_path = _resolve_run_relative_path(run_dir, resolved_job.model_file, field_name="model_file", must_exist=True)
        command = _build_runtime_command(
            engine_mode=resolved_job.engine_mode,
            executable=resolved_job.resolved_tpbig,
            input_path=input_path,
            extra_args=resolved_job.engine_args,
        )
        working_dir = run_dir
        failure_prefix = "tpbig.exe运行失败"
        result_file = resolved_job.result_file
    else:
        if not resolved_job.resolved_rjtzl:
            raise RuntimeError("rjtzl.exe不存在")
        working_dir = _resolve_run_relative_path(run_dir, resolved_job.egm_subdir, field_name="egm_subdir", must_exist=True)
        if not working_dir.is_dir():
            raise RuntimeError(f"EGM子目录不存在: {resolved_job.egm_subdir}")
        egm_input_path = None
        if resolved_job.egm_input_file:
            egm_input_path = _resolve_run_relative_path(
                working_dir,
                resolved_job.egm_input_file,
                field_name="egm_input_file",
                must_exist=True,
            )
        command = _build_runtime_command(
            engine_mode=resolved_job.engine_mode,
            executable=resolved_job.resolved_rjtzl,
            input_path=egm_input_path,
            extra_args=resolved_job.egm_args,
        )
        failure_prefix = "rjtzl.exe运行失败，所得绕击跳闸率无效"
        result_file = resolved_job.egm_result_file

    completed = _run_runtime_command(
        command=command,
        working_dir=working_dir,
        timeout_seconds=resolved_job.timeout_seconds,
        failure_prefix=failure_prefix,
    )
    stdout_text = _truncate_output(completed.stdout)
    stderr_text = _truncate_output(completed.stderr)

    contract = dict(resolved_job.contract)
    payload_source_text = completed.stdout
    if result_file:
        result_path = _resolve_run_relative_path(
            working_dir,
            result_file,
            field_name="result_file" if not resolved_job.use_egm else "egm_result_file",
            must_exist=True,
        )
        payload_source_text, _encoding = _read_text_with_fallback(result_path)
    payload = _read_external_result_payload(
        contract={key: value for key, value in contract.items() if key != "result_file"},
        stdout_text=payload_source_text,
        run_dir=working_dir,
    )
    if resolved_job.use_egm:
        payload = _ensure_egm_result_payload(payload=payload, stdout_text=completed.stdout)

    merged = _merge_external_result(
        baseline_result=baseline_result,
        external_payload=payload,
        resolved_job=_LegacyMergeBridge(resolved_job=resolved_job),
        engine_command=" ".join(command),
        working_dir=str(working_dir),
    )
    merged["external_execution"]["template_dir"] = str(resolved_job.template_dir)
    merged["external_execution"]["calculation_mode"] = resolved_job.calculation_mode
    merged["external_execution"]["use_egm"] = resolved_job.use_egm
    merged["external_execution"]["template_identifier"] = resolved_job.template_identifier

    return LegacyAtpExecutionResult(
        result_json=merged,
        engine_command=" ".join(command),
        working_dir=str(working_dir),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )


def apply_feature_bindings(
    *,
    run_dir: Path,
    model_file: str,
    bindings: list[LegacyFeatureBinding],
    context: dict[str, Any],
    minimum_model_size_bytes: int,
    required_keywords: list[str],
) -> None:
    grouped: dict[str, list[LegacyFeatureBinding]] = {}
    default_target = model_file
    for item in bindings:
        grouped.setdefault(item.file or default_target, []).append(item)

    for relative_target, target_bindings in grouped.items():
        target_path = _resolve_run_relative_path(run_dir, relative_target, field_name="feature_file", must_exist=True)
        text, encoding = _read_text_with_fallback(target_path)
        chars = list(text)
        for binding in target_bindings:
            rendered = _render_feature_binding(binding=binding, context=context)
            if len(rendered) > binding.length:
                raise RuntimeError(f"ATP特征字段超出长度限制: {binding.name}")
            replacement = rendered.rjust(binding.length) if binding.align != "left" else rendered.ljust(binding.length)
            if binding.offset < 0 or binding.offset + binding.length > len(chars):
                raise RuntimeError(f"ATP特征字段越界: {binding.name}")
            chars[binding.offset : binding.offset + binding.length] = list(replacement[: binding.length])
        updated = "".join(chars)
        if len(updated.encode(encoding, errors="ignore")) < minimum_model_size_bytes:
            raise RuntimeError("atp模型文件长度过小")
        for keyword in required_keywords:
            if keyword not in updated:
                raise RuntimeError(f"ATP模型缺少关键段落: {keyword}")
        target_path.write_text(updated, encoding=encoding)


def load_feature_bindings_from_setting_file(setting_path: Path) -> list[LegacyFeatureBinding]:
    text, _encoding = _read_text_with_fallback(setting_path)
    bindings: list[LegacyFeatureBinding] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//") or stripped.startswith(";"):
            continue
        bindings.append(_parse_feature_binding_line(stripped))
    return bindings


def build_legacy_atp_status_checks() -> dict[str, dict[str, Any]]:
    allowed_root = _allowed_root()
    checks: dict[str, dict[str, Any]] = {}
    wine_binary = _resolve_binary(settings.wine_binary_path)
    if wine_binary:
        probe = probe_wine_binary(wine_binary)
        checks["wine"] = {
            "available": probe.available,
            "configured_path": settings.wine_binary_path,
            "resolved_path": wine_binary,
            "error": probe.error,
        }
    else:
        checks["wine"] = {
            "available": False,
            "configured_path": settings.wine_binary_path,
            "resolved_path": None,
            "error": "Wine binary not found",
        }

    for key, raw_path in {
        "legacy_root": settings.atp_legacy_root,
        "template_root": settings.atp_template_root,
        "run_root": settings.atp_run_root,
        "tpbig_executable": settings.atp_tpbig_executable,
        "rjtzl_executable": settings.atp_rjtzl_executable,
    }.items():
        checks[key] = _build_path_status_entry(
            allowed_root=allowed_root,
            raw_path=raw_path,
            key=key,
            must_exist=key != "run_root",
        )

    template_root_entry = checks["template_root"]
    template_root_path = template_root_entry.get("resolved_path")
    egm_subdir = str(settings.atp_egm_subdir).strip() or "EGM"
    if isinstance(template_root_path, str):
        candidate = (Path(template_root_path) / egm_subdir).resolve(strict=False)
        checks["egm_subdir"] = {
            "available": candidate.is_dir(),
            "configured_path": egm_subdir,
            "resolved_path": str(candidate),
            "error": None if candidate.is_dir() else f"EGM子目录不存在: {candidate}",
        }
    else:
        checks["egm_subdir"] = {
            "available": False,
            "configured_path": egm_subdir,
            "resolved_path": None,
            "error": "模板目录不可用，无法检查EGM子目录",
        }
    return checks


def _build_template_context(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "job": {
            "id": job.id,
            "job_name": job.job_name,
            "job_type": job.job_type,
            "external_adapter": job.external_adapter,
        },
        "snapshot": {
            "id": snapshot.id,
            "seq_no": snapshot.seq_no,
            "tower_no": snapshot.tower_no,
            "tower_model": snapshot.tower_model,
            "tower_type": snapshot.tower_type,
            "longitude": snapshot.longitude,
            "latitude": snapshot.latitude,
            "altitude_m": snapshot.altitude_m,
            "terrain": snapshot.terrain,
        },
        "base_tower": snapshot.base_tower_json or {},
        "profile": snapshot.profile_json or {},
        "execution_options": execution_options,
        "workflow": baseline_result.get("workflow") or {},
        "baseline_result": baseline_result,
    }


def _read_external_result_payload(
    *,
    contract: dict[str, Any],
    stdout_text: str,
    run_dir: Path,
) -> dict[str, Any]:
    del run_dir
    payload = _parse_external_payload(stdout_text, contract)
    pointer = str(contract.get("result_json_pointer") or "").strip()
    if pointer:
        pointed = _read_path({"payload": payload}, f"payload.{pointer}")
        if not isinstance(pointed, dict):
            raise RuntimeError(f"外部结果指针无效: {pointer}")
        payload = pointed
    if not isinstance(payload, dict):
        raise RuntimeError("外部 ATP/Wine 结果不是 JSON 对象")
    return _normalize_external_result_payload(payload, _read_object(contract.get("result_key_map")))


def _parse_external_payload(source_text: str, contract: dict[str, Any]) -> dict[str, Any]:
    labels = [str(item).strip() for item in list(contract.get("result_labels") or []) if str(item).strip()]
    if labels:
        values = [item.strip() for item in re.split(r"[|\r\n]+", source_text) if item.strip()]
        return {
            label: _coerce_scalar(values[index]) if index < len(values) else None
            for index, label in enumerate(labels)
        }

    result_format = str(contract.get("result_format") or "").strip().lower()
    if result_format in {"key_value", "kv", "text"}:
        return _parse_key_value_text(source_text)

    markers = contract.get("stdout_json_markers")
    if isinstance(markers, list) and len(markers) == 2:
        candidate = _extract_marked_json(source_text, str(markers[0]), str(markers[1]))
        if candidate is not None:
            return json.loads(candidate)

    candidate = source_text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return json.loads(candidate)

    marked_json = _extract_marked_json(source_text, *DEFAULT_JSON_MARKERS)
    if marked_json is not None:
        return json.loads(marked_json)

    raise RuntimeError("外部 ATP/Wine 结果无法解析为 JSON")


def _parse_key_value_text(source_text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in source_text.splitlines():
        text = line.strip()
        if not text:
            continue
        if "=" in text:
            key, value = text.split("=", 1)
        elif ":" in text:
            key, value = text.split(":", 1)
        else:
            continue
        result[key.strip()] = _coerce_scalar(value.strip())
    return result


def _extract_marked_json(source_text: str, start_marker: str, end_marker: str) -> str | None:
    start_index = source_text.find(start_marker)
    if start_index < 0:
        return None
    start_index += len(start_marker)
    end_index = source_text.find(end_marker, start_index)
    if end_index < 0:
        return None
    return source_text[start_index:end_index].strip()


def _normalize_external_result_payload(
    payload: dict[str, Any],
    result_key_map: dict[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = str(result_key_map.get(raw_key) or raw_key).strip()
        key = LEGACY_RESULT_KEY_MAP.get(key, key)
        value = raw_value
        if key in NUMERIC_RESULT_KEYS:
            value = _coerce_scalar(raw_value)
        normalized[key] = value

    risk_level = normalized.get("risk_level")
    if isinstance(risk_level, (int, float)) and "risk_grade" not in normalized:
        normalized["risk_grade"] = int(risk_level)
        normalized["risk_level"] = _risk_level_from_grade(int(risk_level))
    if "risk_level" not in normalized and "risk_grade" in normalized:
        grade = _coerce_positive_int(normalized.get("risk_grade")) or 1
        normalized["risk_grade"] = grade
        normalized["risk_level"] = _risk_level_from_grade(grade)
    return normalized


def _merge_external_result(
    *,
    baseline_result: dict[str, Any],
    external_payload: dict[str, Any],
    resolved_job: Any,
    engine_command: str,
    working_dir: str,
) -> dict[str, Any]:
    merged = dict(baseline_result)
    workflow = {
        **_read_object(baseline_result.get("workflow")),
        **_read_object(external_payload.get("workflow")),
    }
    if workflow:
        merged["workflow"] = workflow
    for key, value in external_payload.items():
        if key == "workflow" and isinstance(value, dict):
            continue
        merged[key] = value

    if merged.get("selected_case") is None and baseline_result.get("selected_case") is not None:
        merged["selected_case"] = baseline_result.get("selected_case")
    if merged.get("summary_text") is None and baseline_result.get("summary_text") is not None:
        merged["summary_text"] = baseline_result.get("summary_text")
    if merged.get("cause_analysis") is None and baseline_result.get("cause_analysis") is not None:
        merged["cause_analysis"] = baseline_result.get("cause_analysis")
    if merged.get("mitigation_recommendation") is None and baseline_result.get("mitigation_recommendation") is not None:
        merged["mitigation_recommendation"] = baseline_result.get("mitigation_recommendation")

    external_execution = {
        "adapter_status": "executed",
        "adapter": resolved_job.adapter,
        "model_id": resolved_job.model.id,
        "model_code": resolved_job.model.code,
        "model_name": resolved_job.model.name,
        "version_id": resolved_job.version.id,
        "version_no": resolved_job.version.version_no,
        "engine_command": engine_command,
        "working_dir": working_dir,
        "executed_at": utcnow().isoformat(),
    }
    merged["external_execution"] = external_execution
    merged["external_result_json"] = external_payload
    return merged


def _read_path(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for segment in [item for item in path.split(".") if item]:
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return None
    return current


def _read_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_scalar(value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value).strip()
    if not text:
        return text
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if any(char in text for char in {".", "e", "E"}):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _format_value(value: Any, format_spec: str) -> str:
    numeric_value = float(value)
    normalized_spec = format_spec.strip()
    if normalized_spec.startswith("F"):
        precision = abs(int(normalized_spec[1:] or "0"))
        text = f"{numeric_value:.{precision}f}"
        if precision > 0:
            text = text.rstrip("0").rstrip(".")
        elif "." not in text:
            text = f"{text}."
        return text
    if normalized_spec.startswith("E"):
        precision = abs(int(normalized_spec[1:] or "0"))
        return f"{numeric_value:.{precision}E}"
    return format(value, normalized_spec)


def _risk_level_from_grade(grade: int) -> str:
    if grade >= 3:
        return "high"
    if grade == 2:
        return "medium"
    return "low"


def _build_path_status_entry(*, allowed_root: Path, raw_path: str, key: str, must_exist: bool) -> dict[str, Any]:
    configured = str(raw_path).strip()
    if not configured:
        return {
            "available": False,
            "configured_path": raw_path,
            "resolved_path": None,
            "error": f"{key}未配置",
        }
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = allowed_root / candidate
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(allowed_root):
        return {
            "available": False,
            "configured_path": configured,
            "resolved_path": str(resolved),
            "error": f"{key}必须位于{allowed_root}下",
        }
    available = resolved.exists() if must_exist else True
    return {
        "available": available,
        "configured_path": configured,
        "resolved_path": str(resolved),
        "error": None if available else f"{key}不存在: {resolved}",
    }


def _prepare_run_directory(
    *,
    resolved_job: ResolvedLegacyAtpJob,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
) -> Path:
    run_dir = resolved_job.run_root / job.id / snapshot.id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _run_runtime_command(
    *,
    command: list[str],
    working_dir: Path,
    timeout_seconds: int,
    failure_prefix: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{failure_prefix}，执行超时（{timeout_seconds}s）") from exc
    except OSError as exc:
        raise RuntimeError(f"{failure_prefix}: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"{failure_prefix}，退出码 {result.returncode}")
    return result


def _ensure_egm_result_payload(*, payload: dict[str, Any], stdout_text: str) -> dict[str, Any]:
    normalized = dict(payload)
    if normalized.get("shielding_trip_rate") is None:
        fallback = _extract_first_numeric_value(stdout_text)
        if fallback is not None:
            normalized["shielding_trip_rate"] = fallback
    if normalized.get("risk_level") is None:
        normalized["risk_level"] = "medium"
    if normalized.get("summary_text") is None:
        normalized["summary_text"] = "EGM执行完成"
    if normalized.get("shielding_trip_rate") is None:
        raise RuntimeError("rjtzl.exe运行失败，所得绕击跳闸率无效")
    return normalized


def _extract_first_numeric_value(source_text: str) -> float | int | None:
    matches = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", source_text or "")
    if not matches:
        return None
    return _coerce_scalar(matches[0])


def _build_runtime_command(
    *,
    engine_mode: str,
    executable: str,
    input_path: Path | None,
    extra_args: list[str],
) -> list[str]:
    if engine_mode == "native":
        command = [executable]
    else:
        wine_binary = _resolve_binary(settings.wine_binary_path)
        if not wine_binary:
            raise RuntimeError("Wine binary not found")
        command = [wine_binary, executable]
    if input_path is not None:
        command.append(str(input_path))
    command.extend(extra_args)
    return command


def _resolve_runtime_executable(*, raw_path: str, field_name: str, must_exist: bool) -> str | None:
    configured = str(raw_path or "").strip()
    if not configured:
        return None
    if _resolve_engine_mode() == "native":
        resolved = _resolve_binary(configured)
        if resolved or not must_exist:
            return resolved
        raise RuntimeError(f"{field_name}不存在: {configured}")
    resolved = _resolve_path_under_allowed_root(configured, field_name=field_name, must_exist=must_exist)
    if resolved.exists() and not resolved.is_file():
        raise RuntimeError(f"{field_name}不是文件: {resolved}")
    return str(resolved) if (resolved.exists() or not must_exist) else None


def _resolve_calculation_mode(config: dict[str, Any], execution_options: dict[str, Any]) -> str:
    configured = str(config.get("calculation_mode") or config.get("mode") or "").strip().lower()
    if configured:
        return CALCULATION_MODE_ALIASES.get(configured, configured)
    stroke_mode = str(config.get("stroke_mode") or execution_options.get("stroke_mode") or "").strip()
    if stroke_mode in {"反击", "counterstrike"}:
        return "fanji"
    return "raoji1" if _coerce_bool(config.get("use_egm"), default=False) else "fanji"


def _resolve_template_identifier(
    config: dict[str, Any],
    execution_options: dict[str, Any],
    calculation_mode: str,
) -> str:
    for field_name in ("template_subdir", "template_id"):
        candidate = str(config.get(field_name) or "").strip()
        if candidate:
            return candidate

    voltage_level = _coerce_positive_int(config.get("voltage_level") or execution_options.get("voltage_level"))
    subdir_map = _read_object(config.get("subdir_map"))
    if subdir_map:
        matched = subdir_map.get(calculation_mode)
        if isinstance(matched, dict):
            voltage_key = str(voltage_level) if voltage_level is not None else "default"
            selected = matched.get(voltage_key) or matched.get("default")
            if selected:
                return str(selected).strip()
        elif matched:
            return str(matched).strip()

    voltage_level_paths = _read_object(config.get("voltage_level_paths"))
    if voltage_level_paths and voltage_level is not None:
        matched = voltage_level_paths.get(str(voltage_level))
        if isinstance(matched, dict):
            selected = matched.get(calculation_mode) or matched.get("default")
            if selected:
                return str(selected).strip()
        elif matched:
            return str(matched).strip()
    return calculation_mode


def _resolve_template_directory(*, template_root: Path, template_identifier: str) -> Path:
    candidate = (template_root / template_identifier).resolve(strict=False)
    if not candidate.is_relative_to(template_root.resolve(strict=False)):
        raise RuntimeError(f"模型目录越界: {template_identifier}")
    if candidate.is_dir():
        return candidate
    if template_root.is_dir() and template_identifier in {"", ".", "./"}:
        return template_root
    raise RuntimeError(f"模型目录不存在: {candidate}")


def _discover_model_file(template_dir: Path, raw_path: Any) -> str | None:
    configured = _normalize_optional_path(raw_path)
    if configured:
        candidate = (template_dir / configured).resolve(strict=False)
        if not candidate.is_relative_to(template_dir.resolve(strict=False)) or not candidate.is_file():
            raise RuntimeError(f"ATP模型文件不存在: {configured}")
        return str(candidate.relative_to(template_dir))

    candidates = sorted(template_dir.rglob("*.atp"))
    if not candidates:
        return None
    return str(candidates[0].relative_to(template_dir))


def _load_feature_bindings(
    *,
    template_dir: Path,
    raw_bindings: Any,
    raw_setting_file: Any,
) -> list[LegacyFeatureBinding]:
    bindings: list[LegacyFeatureBinding] = []
    if raw_setting_file:
        setting_path = _resolve_optional_template_path(template_dir, raw_setting_file, field_name="feature_setting_file")
        bindings.extend(load_feature_bindings_from_setting_file(setting_path))

    if not raw_bindings:
        return bindings

    if isinstance(raw_bindings, dict):
        if _looks_like_feature_binding(raw_bindings):
            bindings.append(_build_feature_binding(raw_bindings))
        else:
            for name, value in raw_bindings.items():
                bindings.append(_build_feature_binding(value, default_name=str(name)))
        return bindings

    if isinstance(raw_bindings, list):
        for value in raw_bindings:
            bindings.append(_build_feature_binding(value))
        return bindings

    if isinstance(raw_bindings, str):
        setting_path = _resolve_optional_template_path(template_dir, raw_bindings, field_name="feature_bindings")
        bindings.extend(load_feature_bindings_from_setting_file(setting_path))
        return bindings

    raise RuntimeError("feature_bindings配置格式无效")


def _looks_like_feature_binding(value: dict[str, Any]) -> bool:
    keys = set(value.keys())
    return bool({"offset", "length"} & keys) and bool({"path", "source"} & keys)


def _build_feature_binding(raw_value: Any, default_name: str | None = None) -> LegacyFeatureBinding:
    if isinstance(raw_value, LegacyFeatureBinding):
        return raw_value
    mapping = _read_object(raw_value)
    if not mapping:
        raise RuntimeError("feature_binding配置格式无效")
    name = str(mapping.get("name") or default_name or "").strip()
    path = str(mapping.get("path") or mapping.get("source") or "").strip()
    offset = mapping.get("offset")
    length = mapping.get("length")
    if not name or not path:
        raise RuntimeError("feature_binding缺少name/path")
    parsed_offset = int(offset) if offset is not None else None
    parsed_length = _coerce_positive_int(length)
    if parsed_offset is None or parsed_length is None:
        raise RuntimeError(f"feature_binding偏移或长度无效: {name}")
    align = str(mapping.get("align") or "right").strip().lower()
    if align not in {"left", "right"}:
        align = "right"
    return LegacyFeatureBinding(
        name=name,
        path=path,
        offset=parsed_offset,
        length=parsed_length,
        file=_normalize_optional_path(mapping.get("file") or mapping.get("target_file") or mapping.get("entry_file")),
        format_spec=str(mapping.get("format") or "").strip() or None,
        default=mapping.get("default"),
        required=_coerce_bool(mapping.get("required"), default="default" not in mapping),
        align=align,
    )


def _parse_feature_binding_line(line: str) -> LegacyFeatureBinding:
    if line.startswith("{") and line.endswith("}"):
        return _build_feature_binding(_read_object(json.loads(line)))

    if "=" in line and any(token in line for token in ("offset=", "length=", "path=", "source=")):
        mapping: dict[str, Any] = {}
        for item in re.split(r"[;,|]", line):
            key, sep, value = item.partition("=")
            if not sep:
                continue
            mapping[key.strip()] = value.strip()
        return _build_feature_binding(mapping)

    parts = [item.strip() for item in FEATURE_LINE_SPLIT.split(line)]
    if len(parts) < 5:
        raise RuntimeError(f"无法解析ATP特征配置: {line}")
    mapping: dict[str, Any] = {
        "name": parts[0],
        "offset": parts[1],
        "length": parts[2],
        "format": parts[3],
        "path": parts[4],
    }
    if len(parts) > 5:
        mapping["file"] = parts[5]
    if len(parts) > 6:
        mapping["default"] = parts[6]
    if len(parts) > 7:
        mapping["required"] = parts[7]
    if len(parts) > 8:
        mapping["align"] = parts[8]
    return _build_feature_binding(mapping)


def _render_feature_binding(*, binding: LegacyFeatureBinding, context: dict[str, Any]) -> str:
    value = _read_path(context, binding.path)
    if value is None:
        if binding.required:
            raise RuntimeError(f"ATP特征字段缺少取值: {binding.name}")
        value = binding.default
    if value is None:
        return ""
    if binding.format_spec:
        return _format_value(value, binding.format_spec)
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _resolve_optional_template_path(template_dir: Path, raw_path: Any, *, field_name: str) -> Path:
    candidate = str(raw_path or "").strip()
    if not candidate:
        raise RuntimeError(f"{field_name}不能为空")
    path = (template_dir / candidate).resolve(strict=False)
    if not path.is_relative_to(template_dir.resolve(strict=False)) or not path.is_file():
        raise RuntimeError(f"{field_name}不存在: {candidate}")
    return path


def _resolve_path_under_allowed_root(raw_path: str, *, field_name: str, must_exist: bool) -> Path:
    allowed_root = _allowed_root()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        direct_resolved = candidate.resolve(strict=False)
        if direct_resolved.is_relative_to(allowed_root):
            resolved = direct_resolved
        else:
            resolved = (allowed_root / candidate).resolve(strict=False)
    else:
        resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(allowed_root):
        raise RuntimeError(f"{field_name}必须位于{allowed_root}下")
    if must_exist and not resolved.exists():
        raise RuntimeError(f"{field_name}不存在: {resolved}")
    return resolved


def _resolve_run_relative_path(run_dir: Path, raw_path: str, *, field_name: str, must_exist: bool) -> Path:
    candidate = (run_dir / raw_path).resolve(strict=False)
    if not candidate.is_relative_to(run_dir.resolve(strict=False)):
        raise RuntimeError(f"{field_name}越界: {raw_path}")
    if must_exist and not candidate.exists():
        raise RuntimeError(f"{field_name}不存在: {candidate}")
    return candidate


def _allowed_root() -> Path:
    return Path(settings.wine_allowed_root).expanduser().resolve(strict=False)


def _resolve_binary(raw_path: str) -> str | None:
    configured = str(raw_path or "").strip()
    if not configured:
        return None
    resolved = shutil.which(configured)
    if resolved:
        return resolved
    candidate = Path(configured).expanduser()
    if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def _resolve_timeout(payload_timeout: int | None) -> int:
    timeout_seconds = payload_timeout or settings.atp_engine_default_timeout_seconds
    if timeout_seconds > settings.atp_engine_max_timeout_seconds:
        raise RuntimeError(f"timeout_seconds不能超过{settings.atp_engine_max_timeout_seconds}")
    return timeout_seconds


def _resolve_engine_mode() -> str:
    return "native" if str(settings.atp_engine_mode or "").strip().lower() == "native" else "wine"


def _normalize_args(raw_args: Any) -> list[str]:
    return [str(item).strip() for item in list(raw_args or []) if str(item).strip()]


def _normalize_optional_path(raw_path: Any) -> str | None:
    value = str(raw_path or "").strip()
    return value or None


def _infer_use_egm(*, config: dict[str, Any], execution_options: dict[str, Any]) -> bool:
    for candidate in (
        config.get("shielding_trip_rate_method"),
        config.get("raoji_tzl_method"),
        config.get("algorithm"),
        execution_options.get("shielding_trip_rate_method"),
        execution_options.get("raoji_tzl_method"),
        execution_options.get("algorithm"),
    ):
        text = str(candidate or "").strip().upper()
        if text == "EGM":
            return True
    return False


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _read_text_with_fallback(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    last_error: Exception | None = None
    for encoding in ENCODING_CANDIDATES:
        try:
            if encoding == "utf-8-sig":
                if raw.startswith(b"\xef\xbb\xbf"):
                    return raw.decode("utf-8-sig"), "utf-8-sig"
                return raw.decode("utf-8"), "utf-8"
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"无法解析文件编码: {path}") from last_error


def _truncate_output(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= LOG_MAX_CHARS:
        return value
    return f"{value[:LOG_MAX_CHARS]}\n...[truncated]"


class _LegacyMergeBridge:
    def __init__(self, *, resolved_job: ResolvedLegacyAtpJob) -> None:
        self.adapter = "legacy_atp"
        self.model = _BridgeModel(resolved_job=resolved_job)
        self.version = _BridgeVersion(resolved_job=resolved_job)


class _BridgeModel:
    def __init__(self, *, resolved_job: ResolvedLegacyAtpJob) -> None:
        self.id = resolved_job.template_identifier
        self.code = resolved_job.calculation_mode
        self.name = resolved_job.template_dir.name


class _BridgeVersion:
    def __init__(self, *, resolved_job: ResolvedLegacyAtpJob) -> None:
        self.id = resolved_job.template_identifier
        self.version_no = 1
