from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.atp_asset import AtpAsset, AtpAssetRelease
from ..models.base import utcnow
from ..models.fl_analysis import FlAnalysisJob, FlAnalysisTowerSnapshot
from .atp_asset_service import (
    _resolve_engine_workdir,
    _resolve_native_engine_executable,
    _resolve_timeout,
    _resolve_wine_engine_executable,
    _truncate_output,
)

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")
DEFAULT_JSON_MARKERS = ("FL_ANALYSIS_RESULT_BEGIN", "FL_ANALYSIS_RESULT_END")
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


def get_asset_by_id(db: Session, asset_id: str) -> AtpAsset | None:
    """Get ATP asset by ID."""
    return db.execute(select(AtpAsset).where(AtpAsset.id == asset_id)).scalar_one_or_none()


def _resolve_target_release(
    db: Session,
    *,
    asset: AtpAsset,
    release_id: str | None = None,
    release_no: int | None = None,
) -> AtpAssetRelease:
    """Resolve target release from asset."""
    if release_id:
        matched = db.execute(
            select(AtpAssetRelease).where(
                AtpAssetRelease.asset_id == asset.id,
                AtpAssetRelease.id == release_id,
            )
        ).scalar_one_or_none()
        if not matched:
            raise RuntimeError(f"指定的 ATP 资产版本不存在: {release_id}")
        return matched

    if release_no is not None:
        matched = db.execute(
            select(AtpAssetRelease).where(
                AtpAssetRelease.asset_id == asset.id,
                AtpAssetRelease.release_no == release_no,
            )
        ).scalar_one_or_none()
        if not matched:
            raise RuntimeError(f"指定的 ATP 资产版本不存在: release_no={release_no}")
        return matched

    # Use active release
    if asset.active_release_no is not None:
        matched = db.execute(
            select(AtpAssetRelease).where(
                AtpAssetRelease.asset_id == asset.id,
                AtpAssetRelease.release_no == asset.active_release_no,
            )
        ).scalar_one_or_none()
        if matched:
            return matched

    # Fall back to latest release
    matched = db.execute(
        select(AtpAssetRelease)
        .where(AtpAssetRelease.asset_id == asset.id)
        .order_by(AtpAssetRelease.release_no.desc())
    ).first()
    if matched:
        return matched[0]

    raise RuntimeError(f"ATP 资产没有可用的版本: {asset.code}")


def _safe_entry_filename(raw_name: str | None, *, asset_code: str, release_no: int) -> str:
    """Generate safe entry filename."""
    import os
    import re
    from pathlib import Path

    FILENAME_SANITIZE_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    fallback = f"{asset_code}_v{release_no}.atp"
    if not raw_name:
        return fallback

    filename = Path(raw_name).name.strip()
    if not filename:
        return fallback

    cleaned = FILENAME_SANITIZE_PATTERN.sub("_", filename)
    cleaned = cleaned.strip("._")
    if not cleaned:
        return fallback

    if len(cleaned) > 220:
        stem, suffix = os.path.splitext(cleaned)
        cleaned = f"{stem[:200]}{suffix[:20]}"

    return cleaned


@dataclass(slots=True)
class ResolvedExternalWaveformJob:
    adapter: str
    asset: AtpAsset
    release: AtpAssetRelease
    timeout_seconds: int
    extra_args: list[str]
    environment: dict[str, str]
    contract: dict[str, Any]
    parameter_bindings: dict[str, Any]


@dataclass(slots=True)
class ExternalTowerExecutionResult:
    result_json: dict[str, Any]
    engine_command: str
    working_dir: str
    stdout_text: str | None
    stderr_text: str | None


def resolve_external_waveform_job(
    db: Session,
    *,
    external_adapter: str,
    adapter_config_json: dict[str, Any],
) -> ResolvedExternalWaveformJob:
    adapter = str(external_adapter or "").strip().lower()
    if adapter not in {"atp", "wine"}:
        raise RuntimeError(f"Unsupported external adapter: {external_adapter}")

    config = dict(adapter_config_json or {})
    asset_id = str(config.get("asset_id") or config.get("model_id") or "").strip()
    if not asset_id:
        raise RuntimeError("外部 ATP/Wine 任务缺少 adapter_config_json.asset_id")

    asset = get_asset_by_id(db, asset_id)
    if asset is None:
        raise RuntimeError(f"指定的 ATP 资产不存在: {asset_id}")

    release_id = str(config.get("release_id") or config.get("version_id") or "").strip() or None
    release_no = _coerce_positive_int(config.get("release_no") or config.get("version_no"))
    release = _resolve_target_release(
        db,
        asset=asset,
        release_id=release_id,
        release_no=release_no,
    )

    # For AtpAssetRelease, the template content might be in manifest_json
    # Check if there's an atp_text equivalent or entry_file content
    manifest = release.manifest_json or {}
    atp_text = manifest.get("atp_text", "")
    if not atp_text.strip():
        raise RuntimeError(f"ATP 资产版本缺少可执行模板: {asset.code} v{release.release_no}")

    manifest_contract = _read_object(manifest.get("fl_analysis"))
    adapter_contract = {
        key: value
        for key, value in config.items()
        if key
        in {
            "result_file",
            "result_format",
            "result_labels",
            "result_json_pointer",
            "result_key_map",
            "stdout_json_markers",
        }
    }
    parameter_bindings = {
        **_read_object(manifest_contract.get("parameter_bindings")),
        **_read_object(config.get("parameter_bindings")),
    }
    contract = {
        **manifest_contract,
        **adapter_contract,
    }
    contract["parameter_bindings"] = parameter_bindings

    timeout_seconds = _resolve_timeout(_coerce_positive_int(config.get("timeout_seconds")))
    extra_args = [str(item).strip() for item in list(config.get("extra_args") or []) if str(item).strip()]
    environment = {
        str(key): str(value)
        for key, value in _read_object(config.get("environment")).items()
        if str(key).strip()
    }
    return ResolvedExternalWaveformJob(
        adapter=adapter,
        asset=asset,
        release=release,
        timeout_seconds=timeout_seconds,
        extra_args=extra_args,
        environment=environment,
        contract=contract,
        parameter_bindings=parameter_bindings,
    )


def render_atp_template(
    template: str,
    *,
    context: dict[str, Any],
    parameter_bindings: dict[str, Any] | None = None,
) -> str:
    bindings = parameter_bindings or {}

    def replace_placeholder(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        return _render_placeholder(expression, context=context, parameter_bindings=bindings)

    return PLACEHOLDER_PATTERN.sub(replace_placeholder, template)


def execute_external_waveform_tower_analysis(
    resolved_job: ResolvedExternalWaveformJob,
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> ExternalTowerExecutionResult:
    context = _build_template_context(
        job=job,
        snapshot=snapshot,
        execution_options=execution_options,
        baseline_result=baseline_result,
    )
    # Get atp_text from manifest_json
    manifest = resolved_job.release.manifest_json or {}
    atp_text = manifest.get("atp_text", "")

    rendered_text = render_atp_template(
        atp_text,
        context=context,
        parameter_bindings=resolved_job.parameter_bindings,
    )

    run_dir = _prepare_run_directory(job=job, snapshot=snapshot, resolved_job=resolved_job)
    input_path = run_dir / _safe_entry_filename(
        resolved_job.release.entry_file,
        asset_code=resolved_job.asset.code,
        release_no=resolved_job.release.release_no,
    )
    input_path.write_text(rendered_text, encoding="utf-8")

    command = _build_command(
        adapter=resolved_job.adapter,
        input_path=input_path,
        extra_args=resolved_job.extra_args,
    )
    env = os.environ.copy()
    env.update(resolved_job.environment)

    try:
        result = subprocess.run(
            command,
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=resolved_job.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{snapshot.tower_no} 外部 ATP/Wine 执行超时（{resolved_job.timeout_seconds}s）"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"{snapshot.tower_no} 外部 ATP/Wine 启动失败: {exc}") from exc

    stdout_text = _truncate_output(result.stdout)
    stderr_text = _truncate_output(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"{snapshot.tower_no} 外部 ATP/Wine 执行失败，退出码 {result.returncode}"
        )

    parsed_payload = _read_external_result_payload(
        contract=resolved_job.contract,
        stdout_text=result.stdout,
        run_dir=run_dir,
    )
    merged_result = _merge_external_result(
        baseline_result=baseline_result,
        external_payload=parsed_payload,
        resolved_job=resolved_job,
        engine_command=" ".join(command),
        working_dir=str(run_dir),
    )
    return ExternalTowerExecutionResult(
        result_json=merged_result,
        engine_command=" ".join(command),
        working_dir=str(run_dir),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )


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


def _prepare_run_directory(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    resolved_job: ResolvedExternalWaveformJob,
) -> Path:
    base_dir = _resolve_engine_workdir() / "fl-analysis" / job.id / snapshot.id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _build_command(*, adapter: str, input_path: Path, extra_args: list[str]) -> list[str]:
    if adapter == "wine":
        wine_binary, engine_path, error = _resolve_wine_engine_executable()
        if error or not wine_binary or not engine_path:
            raise RuntimeError(error or "Wine ATP engine unavailable")
        return [wine_binary, engine_path, str(input_path), *extra_args]

    engine_path, error = _resolve_native_engine_executable()
    if error or not engine_path:
        raise RuntimeError(error or "Native ATP engine unavailable")
    return [engine_path, str(input_path), *extra_args]


def _render_placeholder(
    expression: str,
    *,
    context: dict[str, Any],
    parameter_bindings: dict[str, Any],
) -> str:
    if expression in parameter_bindings:
        return _render_bound_placeholder(parameter_bindings[expression], context=context, name=expression)

    path, spec, width, default, required = _parse_inline_expression(expression)
    value = _read_path(context, path)
    return _stringify_value(
        value,
        format_spec=spec,
        width=width,
        default=default,
        required=required,
        name=expression,
    )


def _render_bound_placeholder(binding: Any, *, context: dict[str, Any], name: str) -> str:
    if isinstance(binding, str):
        path, spec, width, default, required = _parse_inline_expression(binding)
        value = _read_path(context, path)
        return _stringify_value(
            value,
            format_spec=spec,
            width=width,
            default=default,
            required=required,
            name=name,
        )

    mapping = _read_object(binding)
    path = str(mapping.get("path") or mapping.get("source") or "").strip()
    if not path:
        raise RuntimeError(f"ATP 模板绑定缺少 path/source: {name}")
    value = _read_path(context, path)
    return _stringify_value(
        value,
        format_spec=str(mapping.get("format") or "").strip() or None,
        width=_coerce_positive_int(mapping.get("width")),
        default=mapping.get("default"),
        required=bool(mapping.get("required", "default" not in mapping)),
        name=name,
    )


def _parse_inline_expression(expression: str) -> tuple[str, str | None, int | None, Any, bool]:
    parts = [part.strip() for part in expression.split("|")]
    path = parts[0]
    spec = parts[1] if len(parts) > 1 and parts[1] else None
    width = _coerce_positive_int(parts[2]) if len(parts) > 2 and parts[2] else None
    if len(parts) > 3:
        return path, spec, width, parts[3], False
    return path, spec, width, None, True


def _stringify_value(
    value: Any,
    *,
    format_spec: str | None,
    width: int | None,
    default: Any,
    required: bool,
    name: str,
) -> str:
    if value is None:
        if required:
            raise RuntimeError(f"ATP 模板占位符缺少取值: {name}")
        text = "" if default is None else str(default)
        return text.rjust(width) if width else text

    text: str
    if format_spec:
        text = _format_value(value, format_spec)
    elif isinstance(value, bool):
        text = "1" if value else "0"
    else:
        text = str(value)
    return text.rjust(width) if width else text


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


def _read_external_result_payload(
    *,
    contract: dict[str, Any],
    stdout_text: str,
    run_dir: Path,
) -> dict[str, Any]:
    result_file = str(contract.get("result_file") or "").strip()
    source_text: str
    if result_file:
        result_path = (run_dir / result_file).resolve(strict=False)
        if not result_path.is_relative_to(run_dir.resolve(strict=False)):
            raise RuntimeError(f"外部结果文件越界: {result_file}")
        if not result_path.exists():
            raise RuntimeError(f"外部 ATP/Wine 未生成结果文件: {result_file}")
        source_text = result_path.read_text(encoding="utf-8", errors="replace")
    else:
        source_text = stdout_text

    payload = _parse_external_payload(source_text, contract)
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
    resolved_job: ResolvedExternalWaveformJob,
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
        "asset_id": resolved_job.asset.id,
        "asset_code": resolved_job.asset.code,
        "asset_name": resolved_job.asset.name,
        "release_id": resolved_job.release.id,
        "release_no": resolved_job.release.release_no,
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


def _risk_level_from_grade(grade: int) -> str:
    if grade >= 3:
        return "high"
    if grade == 2:
        return "medium"
    return "low"
