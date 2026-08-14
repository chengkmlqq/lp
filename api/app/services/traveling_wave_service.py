from __future__ import annotations

import base64
import io
import math
import os
import re
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from ..schemas.traveling_wave import (
    TravelingWaveAnalyzeResponse,
    TravelingWaveParseResult,
    TravelingWaveStatusResponse,
)


# ── Environment detection ──────────────────────────────────────────────


def _check_import(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def check_environment() -> TravelingWaveStatusResponse:
    numpy_ok = False
    scipy_ok = False
    matplotlib_ok = False
    missing_components: list[str] = []
    error_parts: list[str] = []

    try:
        import numpy  # noqa: F401
        numpy_ok = True
    except ImportError:
        missing_components.append("numpy")
        error_parts.append("numpy not available")

    try:
        import scipy  # noqa: F401
        scipy_ok = True
    except ImportError:
        missing_components.append("scipy")
        error_parts.append("scipy not available")

    try:
        import matplotlib  # noqa: F401
        matplotlib_ok = True
    except ImportError:
        missing_components.append("matplotlib")
        error_parts.append("matplotlib not available")

    return TravelingWaveStatusResponse(
        python_available=True,
        numpy_available=numpy_ok,
        scipy_available=scipy_ok,
        matplotlib_available=matplotlib_ok,
        missing_components=missing_components,
        error="; ".join(error_parts) if error_parts else None,
    )


# ── Database persistence ──────────────────────────────────────────────

def create_job(
    db,
    sample_rate_hz: int = 1_000_000,
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
    file_a_path: str | None = None,
    file_b_path: str | None = None,
    file_c_path: str | None = None,
    created_by: str | None = None,
) -> str:
    """Create a new traveling wave job in the database. Returns job_id."""
    from ..models.traveling_wave_job import TravelingWaveJob

    job = TravelingWaveJob(
        status="pending",
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
        file_a_path=file_a_path,
        file_b_path=file_b_path,
        file_c_path=file_c_path,
        created_by=created_by,
    )
    db.add(job)
    db.commit()
    return job.id


def get_job(db, job_id: str):
    """Retrieve a traveling wave job from the database."""
    from ..models.traveling_wave_job import TravelingWaveJob

    return db.query(TravelingWaveJob).filter(TravelingWaveJob.id == job_id).first()


def _update_job_result(db, job_id: str, status: str, result_json: dict[str, Any] | None, error_message: str | None, log_text: str) -> None:
    """Update job result in database."""
    from ..models.traveling_wave_job import TravelingWaveJob

    job = db.query(TravelingWaveJob).filter(TravelingWaveJob.id == job_id).first()
    if job:
        job.status = status
        job.result_json = result_json
        job.error_message = error_message
        job.log_text = log_text
        job.finished_at = datetime.now(timezone.utc)
        db.commit()


# ── File parsing ──────────────────────────────────────────────────────


def _read_file_content(source: str) -> str:
    """Read content from a file path or treat source as raw content."""
    if os.path.isfile(source):
        with open(source, encoding="utf-8") as f:
            return f.read()
    # Treat as raw content
    return source


_HEADER_PATTERN = re.compile(r"^(\w+)=(.+)$")


def parse_phase_file(source: str) -> tuple[dict[str, str], list[float]]:
    """Parse a traveling wave data file (Key=Value header + CurrentDataInput CSV).

    Returns (headers_dict, current_values_list).
    """
    text = _read_file_content(source)
    headers: dict[str, str] = {}
    current_values: list[float] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _HEADER_PATTERN.match(stripped)
        if m:
            key = m.group(1)
            value = m.group(2)
            if key == "CurrentDataInput":
                # Parse CSV values
                for token in value.split(","):
                    t = token.strip()
                    if t:
                        try:
                            current_values.append(float(t))
                        except ValueError:
                            pass
            else:
                headers[key] = value

    return headers, current_values


def _parse_head_time_seconds(head_time_str: str) -> float:
    """Parse HeadTime (``YYYYMMDDHHmmssuuuuuuuu``) to absolute Unix seconds.

    The fractional part is nanoseconds (9 digits); pad or truncate as needed.
    """
    if len(head_time_str) < 14:
        return 0.0
    year = int(head_time_str[0:4])
    month = int(head_time_str[4:6])
    day = int(head_time_str[6:8])
    hour = int(head_time_str[8:10])
    minute = int(head_time_str[10:12])
    second = int(head_time_str[12:14])
    nano_str = head_time_str[14:]
    # Normalize to 9 digits
    nano_str = nano_str.ljust(9, "0")[:9]
    nano = int(nano_str)

    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.timestamp() + nano / 1_000_000_000.0


def _build_parse_result(headers: dict[str, str], head_time_abs: float) -> TravelingWaveParseResult:
    """Build a parse-result schema from parsed headers."""
    head_time_raw = headers.get("HeadTime", "")
    parsed_dt: datetime | None = None
    if head_time_raw:
        try:
            parsed_dt = datetime.fromtimestamp(head_time_abs, tz=timezone.utc)
        except (OSError, ValueError):
            pass
    return TravelingWaveParseResult(
        wave_batch_id=headers.get("WaveBatchID", ""),
        vo_level=headers.get("VoLevel", ""),
        sample_frequency=int(headers.get("SampleFrequency", "0")),
        head_time=head_time_raw,
        head_time_parsed=parsed_dt,
        left_dist_ohl=int(headers.get("LeftDistOHL", "0")),
        right_dist_ohl=int(headers.get("RightDistOHL", "0")),
        data_len=int(headers.get("DataLen", "0")),
        line_name=headers.get("MLineID", ""),
    )


# ── Interpolation & time alignment ────────────────────────────────────


def _align_and_interpolate(
    data_a: Sequence[float],
    time_a: Sequence[float],
    data_b: Sequence[float],
    time_b: Sequence[float],
    data_c: Sequence[float],
    time_c: Sequence[float],
    target_point_count: int = 2000,
) -> tuple[list[float], list[float], list[float], list[float]] | None:
    """Align three phases to a common time axis via PCHIP interpolation.

    Returns (common_time, interpolated_a, interpolated_b, interpolated_c)
    or None if alignment fails.
    """
    try:
        from scipy.interpolate import PchipInterpolator
    except ImportError:
        return None

    # Determine common time interval
    t_start = max(time_a[0], time_b[0], time_c[0])
    t_end = min(time_a[-1], time_b[-1], time_c[-1])

    if t_end <= t_start:
        # No overlap; fall back to the shortest span
        spans = [
            (time_a[-1] - time_a[0], time_a),
            (time_b[-1] - time_b[0], time_b),
            (time_c[-1] - time_c[0], time_c),
        ]
        spans.sort(key=lambda x: x[0])
        t_start = spans[0][1][0]
        t_end = spans[0][1][-1]

    common_time = [t_start + (t_end - t_start) * i / (target_point_count - 1) for i in range(target_point_count)]

    interp_a = PchipInterpolator(time_a, data_a, extrapolate=False)
    interp_b = PchipInterpolator(time_b, data_b, extrapolate=False)
    interp_c = PchipInterpolator(time_c, data_c, extrapolate=False)

    result_a = [float(v) if not math.isnan(float(v)) else 0.0 for v in interp_a(common_time)]
    result_b = [float(v) if not math.isnan(float(v)) else 0.0 for v in interp_b(common_time)]
    result_c = [float(v) if not math.isnan(float(v)) else 0.0 for v in interp_c(common_time)]

    return common_time, result_a, result_b, result_c


# ── Plotting ───────────────────────────────────────────────────────────


def _generate_combined_chart(
    common_time_us: list[float],
    phase_a: list[float],
    phase_b: list[float],
    phase_c: list[float],
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
) -> str | None:
    """Generate a combined two-panel chart (3-phase + zero-sequence) as base64 PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    if common_time_us:
        t0 = common_time_us[0]
        t_us = [(t - t0) * 1_000_000 for t in common_time_us]
    else:
        t_us = list(range(len(phase_a)))
    t_ms = [v / 1000.0 for v in t_us]

    i0 = [(a + b + c) / 3.0 for a, b, c in zip(phase_a, phase_b, phase_c)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Three-phase
    ax1.plot(t_ms, phase_a, color="#E74C3C", label="A相", linewidth=0.8)
    ax1.plot(t_ms, phase_b, color="#27AE60", label="B相", linewidth=0.8)
    ax1.plot(t_ms, phase_c, color="#3498DB", label="C相", linewidth=0.8)
    ax1.set_ylabel("电流 (A)")
    ax1.set_title("三相行波波形")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="gray", linewidth=0.5)

    # Zero-sequence
    ax2.plot(t_ms, i0, color="#8E44AD", label="I₀ = (A+B+C)/3", linewidth=0.8)
    ax2.set_xlabel("时间 (ms)")
    ax2.set_ylabel("电流 (A)")
    ax2.set_title("零序分量波形")
    ax2.legend(loc="upper right", fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color="gray", linewidth=0.5)

    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── Main analysis orchestration ────────────────────────────────────────


def run_analysis(
    file_a_content: str | None = None,
    file_b_content: str | None = None,
    file_c_content: str | None = None,
    file_a_path: str | None = None,
    file_b_path: str | None = None,
    file_c_path: str | None = None,
    sample_rate_hz: int = 1_000_000,
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
) -> TravelingWaveAnalyzeResponse:
    """Execute traveling wave analysis on three-phase data files.

    Returns a fully populated response with chart images and parsed info.
    """
    job_id = uuid.uuid4().hex
    log_parts: list[str] = []
    log_parts.append(f"分析任务 {job_id} 已创建")
    log_parts.append(f"采样率: {sample_rate_hz} Hz")

    result = TravelingWaveAnalyzeResponse(
        id=job_id,
        status="running",
        created_at=datetime.now(timezone.utc),
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
    )

    try:
        # 1. Parse files
        sources = {
            "A相": file_a_content or file_a_path,
            "B相": file_b_content or file_b_path,
            "C相": file_c_content or file_c_path,
        }
        phase_keys = ["A相", "B相", "C相"]
        parsed_headers: dict[str, dict[str, str]] = {}
        parsed_data: dict[str, list[float]] = {}
        head_times: dict[str, float] = {}

        for key in phase_keys:
            source = sources.get(key)
            if not source:
                log_parts.append(f"[{key}] 无数据输入")
                continue
            try:
                headers, values = parse_phase_file(source)
                parsed_headers[key] = headers
                parsed_data[key] = values
                ht_raw = headers.get("HeadTime", "")
                head_times[key] = _parse_head_time_seconds(ht_raw) if ht_raw else 0.0
                log_parts.append(
                    f"[{key}] 已解析: {len(values)} 采样点, "
                    f"采样率={headers.get('SampleFrequency', '?')} Hz, "
                    f"HeadTime={ht_raw[:18] if len(ht_raw) > 18 else ht_raw}..."
                )
            except Exception as exc:
                log_parts.append(f"[{key}] 解析失败: {exc}")

        # Check we have at least one phase
        if not parsed_data:
            result.status = "failed"
            result.error_message = "未解析到任何有效数据文件"
            result.log_text = "\n".join(log_parts)
            return result

        # 2. Extract common info
        primary_phase = "A相" if "A相" in parsed_headers else next(iter(parsed_headers))
        primary_h = parsed_headers.get(primary_phase, {})

        for key, headers in parsed_headers.items():
            setattr(result, f"phase_{key[0].lower()}_info", _build_parse_result(headers, head_times.get(key, 0.0)))

        result.vo_level = primary_h.get("VoLevel", "")
        result.line_name = primary_h.get("MLineID", "")
        result.left_dist_ohl = int(primary_h.get("LeftDistOHL", "0"))
        result.right_dist_ohl = int(primary_h.get("RightDistOHL", "0"))

        log_parts.append(f"电压等级: {result.vo_level}")
        log_parts.append(f"线路名称: {result.line_name}")
        log_parts.append(f"档距: {result.left_dist_ohl} / {result.right_dist_ohl} m")

        # 3. Build time axes
        time_axes: dict[str, list[float]] = {}
        for key in phase_keys:
            if key not in parsed_data:
                continue
            values = parsed_data[key]
            ht = head_times.get(key, 0.0)
            dt = 1.0 / sample_rate_hz
            time_axes[key] = [ht + i * dt for i in range(len(values))]

        # 4. Align & interpolate
        aligned_phases = _align_and_interpolate(
            parsed_data.get("A相", []),
            time_axes.get("A相", []),
            parsed_data.get("B相", []),
            time_axes.get("B相", []),
            parsed_data.get("C相", []),
            time_axes.get("C相", []),
        )

        if aligned_phases is None:
            log_parts.append("插值对齐失败（scipy 不可用），直接使用原始数据")
            # Use raw data without interpolation
            common_time = time_axes.get(primary_phase, [])
            data_a = parsed_data.get("A相", [])
            data_b = parsed_data.get("B相", [])
            data_c = parsed_data.get("C相", [])
            # Pad to same length
            max_len = max(len(data_a), len(data_b), len(data_c))
            data_a = data_a + [0.0] * (max_len - len(data_a))
            data_b = data_b + [0.0] * (max_len - len(data_b))
            data_c = data_c + [0.0] * (max_len - len(data_c))
            if len(common_time) < max_len:
                common_time = common_time + [common_time[-1] + i * (1.0 / sample_rate_hz) for i in range(1, max_len - len(common_time) + 1)]
            chart_b64 = _generate_combined_chart(
                common_time[:max_len], data_a[:max_len], data_b[:max_len], data_c[:max_len],
                fault_distance_km=fault_distance_km, tower_no=tower_no,
            )
        else:
            common_time, data_a, data_b, data_c = aligned_phases
            log_parts.append(f"插值对齐完成: {len(common_time)} 个公共时间点")
            chart_b64 = _generate_combined_chart(
                common_time, data_a, data_b, data_c,
                fault_distance_km=fault_distance_km, tower_no=tower_no,
            )

        if chart_b64:
            result.three_phase_chart = chart_b64
            result.zero_sequence_chart = chart_b64
            log_parts.append("图表已生成")
        else:
            log_parts.append("图表生成失败（matplotlib 不可用）")

        result.status = "success"
        log_parts.append("分析完成")

    except Exception as exc:
        result.status = "failed"
        result.error_message = str(exc)
        log_parts.append(f"分析异常: {exc}")

    result.log_text = "\n".join(log_parts)
    result.finished_at = datetime.now(timezone.utc)
    return result


# ── Synchronous job wrapper for API use ────────────────────────────────


def execute_analysis_sync(
    file_a_path: str | None = None,
    file_b_path: str | None = None,
    file_c_path: str | None = None,
    sample_rate_hz: int = 1_000_000,
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
    content_a: str | None = None,
    content_b: str | None = None,
    content_c: str | None = None,
) -> TravelingWaveAnalyzeResponse:
    """Synchronous analysis entry point.

    Can accept either file paths or raw file content strings.
    """
    return run_analysis(
        file_a_path=file_a_path,
        file_b_path=file_b_path,
        file_c_path=file_c_path,
        file_a_content=content_a,
        file_b_content=content_b,
        file_c_content=content_c,
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
    )


def execute_job(job_id: str) -> None:
    """Execute a traveling wave analysis job by retrieving from DB and processing.

    This is called by Celery worker. Updates the DB with results.
    """
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        log_parts: list[str] = [f"执行任务 {job_id}"]

        # Execute the analysis
        result = execute_analysis_sync(
            file_a_path=job.file_a_path,
            file_b_path=job.file_b_path,
            file_c_path=job.file_c_path,
            sample_rate_hz=job.sample_rate_hz or 1_000_000,
            fault_distance_km=job.fault_distance_km,
            tower_no=job.tower_no,
        )

        # Build result JSON from response
        result_dict: dict[str, Any] = {
            "status": result.status,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "finished_at": result.finished_at.isoformat() if result.finished_at else None,
            "sample_rate_hz": result.sample_rate_hz,
            "fault_distance_km": result.fault_distance_km,
            "tower_no": result.tower_no,
            "three_phase_chart": result.three_phase_chart,
            "zero_sequence_chart": result.zero_sequence_chart,
            "error_message": result.error_message,
            "log_text": result.log_text,
        }
        if result.phase_a_info:
            result_dict["phase_a_info"] = result.phase_a_info.model_dump()
        if result.phase_b_info:
            result_dict["phase_b_info"] = result.phase_b_info.model_dump()
        if result.phase_c_info:
            result_dict["phase_c_info"] = result.phase_c_info.model_dump()
        if hasattr(result, "vo_level"):
            result_dict["vo_level"] = result.vo_level
        if hasattr(result, "line_name"):
            result_dict["line_name"] = result.line_name
        if hasattr(result, "left_dist_ohl"):
            result_dict["left_dist_ohl"] = result.left_dist_ohl
        if hasattr(result, "right_dist_ohl"):
            result_dict["right_dist_ohl"] = result.right_dist_ohl

        log_text = result.log_text or ""
        _update_job_result(
            db,
            job_id,
            status=result.status,
            result_json=result_dict,
            error_message=result.error_message,
            log_text=log_text,
        )
    except Exception as exc:
        log_parts.append(f"任务执行异常: {exc}")
        import traceback
        log_parts.append(traceback.format_exc())
        _update_job_result(
            db,
            job_id,
            status="failed",
            result_json=None,
            error_message=str(exc),
            log_text="\n".join(log_parts),
        )
        raise
    finally:
        db.close()


def dispatch_traveling_wave_task(job_id: str) -> None:
    """Dispatch a traveling wave job to Celery for async execution."""
    from ..tasks.traveling_wave_tasks import execute_traveling_wave_job

    execute_traveling_wave_job.delay(job_id)


def create_analysis_job(
    db,
    file_a_path: str | None = None,
    file_b_path: str | None = None,
    file_c_path: str | None = None,
    sample_rate_hz: int = 1_000_000,
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
    content_a: str | None = None,
    content_b: str | None = None,
    content_c: str | None = None,
    created_by: str | None = None,
) -> tuple[str, TravelingWaveAnalyzeResponse]:
    """Create a traveling wave job and dispatch to Celery.

    Returns (job_id, pending_response).
    """
    import os
    from pathlib import Path

    # If content is provided, save to shared volume
    saved_paths = {}
    if content_a or content_b or content_c:
        vfs_root = os.environ.get("FILE_VFS_ROOT", "/app/data/vfs")
        os.makedirs(vfs_root, exist_ok=True)

        for phase, content in [("a", content_a), ("b", content_b), ("c", content_c)]:
            if content:
                filename = f"{uuid.uuid4().hex}_{phase}.dat"
                filepath = os.path.join(vfs_root, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                saved_paths[f"file_{phase}_path"] = filepath

    # Create job in database
    job_id = create_job(
        db,
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
        file_a_path=saved_paths.get("file_a_path") or file_a_path,
        file_b_path=saved_paths.get("file_b_path") or file_b_path,
        file_c_path=saved_paths.get("file_c_path") or file_c_path,
        created_by=created_by,
    )

    # Dispatch task to Celery
    dispatch_traveling_wave_task(job_id)

    # Return pending response
    result = TravelingWaveAnalyzeResponse(
        id=job_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
    )
    return job_id, result


def get_analysis_result(db, job_id: str) -> TravelingWaveAnalyzeResponse | None:
    """Retrieve a traveling wave analysis result from database."""
    job = get_job(db, job_id)
    if job is None:
        return None

    result = TravelingWaveAnalyzeResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        finished_at=job.finished_at,
        sample_rate_hz=job.sample_rate_hz,
        fault_distance_km=job.fault_distance_km,
        tower_no=job.tower_no,
        error_message=job.error_message,
        log_text=job.log_text,
    )

    # Populate from result_json if available
    if job.result_json:
        data = job.result_json
        result.three_phase_chart = data.get("three_phase_chart")
        result.zero_sequence_chart = data.get("zero_sequence_chart")
        if "phase_a_info" in data and data["phase_a_info"]:
            result.phase_a_info = TravelingWaveParseResult(**data["phase_a_info"])
        if "phase_b_info" in data and data["phase_b_info"]:
            result.phase_b_info = TravelingWaveParseResult(**data["phase_b_info"])
        if "phase_c_info" in data and data["phase_c_info"]:
            result.phase_c_info = TravelingWaveParseResult(**data["phase_c_info"])
        if "vo_level" in data:
            result.vo_level = data["vo_level"]
        if "line_name" in data:
            result.line_name = data["line_name"]
        if "left_dist_ohl" in data:
            result.left_dist_ohl = data["left_dist_ohl"]
        if "right_dist_ohl" in data:
            result.right_dist_ohl = data["right_dist_ohl"]

    return result
