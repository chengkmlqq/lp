from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.wine import WineRun
from ..schemas.wine import WineRunDetail, WineRunListResponse, WineRunRequest, WineRunSummary, WineStatusResponse
from .wine_probe import probe_wine_binary, probe_wine_binary_async
from .task_log_service import TaskLogServiceError, upload_task_log


settings = get_settings()
LOG_MAX_CHARS = 200_000


def _decode_output(data: bytes | None) -> str:
    """Decode bytes, preferring gbk then utf-8.

    ATP (tpbig.exe) is a Chinese Windows program; its Chinese text
    (dates, comments) uses GBK encoding under Wine.  UTF-8 decoding
    alone would mangle those characters into � replacement glyphs.
    """
    if data is None:
        return ""
    for encoding in ["gbk", "utf-8"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Last resort: utf-8 with replacement
    return data.decode("utf-8", errors="replace")


def _truncate_output(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= LOG_MAX_CHARS:
        return value
    return f"{value[:LOG_MAX_CHARS]}\n...[truncated]"


def _allowed_root() -> Path:
    return Path(settings.wine_allowed_root).expanduser().resolve(strict=False)


def _resolve_binary() -> str | None:
    configured = settings.wine_binary_path.strip() or "wine"
    resolved = shutil.which(configured)
    if resolved:
        return resolved

    candidate = Path(configured).expanduser()
    if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def _resolve_path_under_root(raw_path: str, *, field_name: str, must_exist: bool) -> Path:
    root = _allowed_root()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate

    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be inside wine allowed root: {root}",
        )
    if must_exist and not resolved.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} does not exist: {resolved}",
        )
    return resolved


def _resolve_executable(raw_path: str) -> Path:
    executable = _resolve_path_under_root(raw_path, field_name="exe_path", must_exist=True)
    if not executable.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"exe_path is not a file: {executable}",
        )
    return executable


def _resolve_working_dir(raw_path: str | None, executable: Path) -> Path:
    if not raw_path:
        return executable.parent
    working_dir = _resolve_path_under_root(raw_path, field_name="working_dir", must_exist=True)
    if not working_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"working_dir is not a directory: {working_dir}",
        )
    return working_dir


def _resolve_timeout(payload_timeout: int | None) -> int:
    timeout_seconds = payload_timeout or settings.wine_default_timeout_seconds
    if timeout_seconds > settings.wine_max_timeout_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"timeout_seconds cannot exceed {settings.wine_max_timeout_seconds}",
        )
    return timeout_seconds


async def get_wine_status() -> WineStatusResponse:
    binary = settings.wine_binary_path.strip() or "wine"
    allowed_root = str(_allowed_root())
    resolved = _resolve_binary()
    if not resolved:
        return WineStatusResponse(
            wine_binary=binary,
            available=False,
            allowed_root=allowed_root,
            default_timeout_seconds=settings.wine_default_timeout_seconds,
            max_timeout_seconds=settings.wine_max_timeout_seconds,
            error="Wine binary not found",
        )

    probe = await probe_wine_binary_async(resolved)
    return WineStatusResponse(
        wine_binary=binary,
        resolved_binary=resolved,
        available=probe.available,
        version=probe.version,
        allowed_root=allowed_root,
        default_timeout_seconds=settings.wine_default_timeout_seconds,
        max_timeout_seconds=settings.wine_max_timeout_seconds,
        error=probe.error,
    )


def serialize_run(item: WineRun) -> WineRunSummary:
    stdout_text = item.stdout_text or ""
    stderr_text = item.stderr_text or ""
    return WineRunSummary(
        id=item.id,
        task_id=item.task_id,
        status=item.status,  # type: ignore[arg-type]
        exe_path=item.exe_path,
        arguments=item.arguments_json or [],
        working_dir=item.working_dir,
        timeout_seconds=item.timeout_seconds,
        command_text=item.command_text,
        resolved_binary=item.resolved_binary,
        exit_code=item.exit_code,
        timed_out=item.timed_out,
        started_at=item.started_at,
        finished_at=item.finished_at,
        duration_ms=item.duration_ms,
        error_message=item.error_message,
        stdout_size=len(stdout_text),
        stderr_size=len(stderr_text),
        create_date=item.create_date,
        create_user=item.create_user,
    )


def serialize_run_detail(item: WineRun) -> WineRunDetail:
    summary = serialize_run(item)
    return WineRunDetail(
        **summary.model_dump(),
        stdout_text=item.stdout_text,
        stderr_text=item.stderr_text,
    )


def list_runs(db: Session, *, limit: int, offset: int) -> WineRunListResponse:
    total = int(db.scalar(select(func.count()).select_from(WineRun)) or 0)
    items = db.execute(
        select(WineRun).order_by(WineRun.create_date.desc(), WineRun.id.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return WineRunListResponse(items=[serialize_run(item) for item in items], total=total)


def get_run_by_id(db: Session, run_id: str) -> WineRun | None:
    return db.execute(select(WineRun).where(WineRun.id == run_id)).scalar_one_or_none()


def get_run_detail(db: Session, *, run_id: str) -> WineRunDetail:
    run = get_run_by_id(db, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wine run not found")
    return serialize_run_detail(run)


def create_run(
    db: Session,
    *,
    payload: WineRunRequest,
    actor_user_id: str,
) -> WineRunDetail:
    resolved_binary = _resolve_binary()
    if not resolved_binary:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wine binary not found")

    probe = probe_wine_binary(resolved_binary)
    if not probe.available:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=probe.error or "Wine binary unavailable")

    executable = _resolve_executable(payload.exe_path)
    working_dir = _resolve_working_dir(payload.working_dir, executable)
    timeout_seconds = _resolve_timeout(payload.timeout_seconds)
    command = [resolved_binary, str(executable), *payload.arguments]

    run = WineRun(
        status="pending",
        exe_path=str(executable),
        arguments_json=payload.arguments,
        working_dir=str(working_dir),
        environment_json=payload.environment,
        wine_binary=settings.wine_binary_path.strip() or "wine",
        resolved_binary=resolved_binary,
        command_text=" ".join(command),
        timeout_seconds=timeout_seconds,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(run)
    db.flush()
    db.commit()

    try:
        task = _dispatch_wine_run_task(run_id=run.id, actor_user_id=actor_user_id)
    except Exception as exc:
        _mark_run_failed(db, run=run, actor_user_id=actor_user_id, reason=f"Celery dispatch failed: {exc}")
        saved = get_run_by_id(db, run.id)
        if not saved:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Wine run save failed") from exc
        return serialize_run_detail(saved)
    run.task_id = str(task.id)
    run.update_user = actor_user_id
    run.update_date = utcnow()
    db.commit()

    saved = get_run_by_id(db, run.id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Wine run save failed")
    return serialize_run_detail(saved)


def _ensure_wine_prefix_initialized() -> None:
    """Ensure the Wine prefix (~/.wine) is initialized before running commands.

    On a headless server without DISPLAY, Wine's first-run initialization
    (wineboot --init) hangs waiting for a display driver. This function
    pre-initializes the prefix with a timeout so that subsequent wine commands
    do not block on first-time setup.
    """
    wine_binary = _resolve_binary()
    if not wine_binary:
        return

    wine_prefix = Path(os.path.expanduser("~/.wine"))
    update_timestamp = wine_prefix / ".update-timestamp"
    if update_timestamp.exists():
        # WINEPREFIX already initialized
        # Kill any stale wine processes that might interfere
        _kill_wine_processes()
        return

    # First-time initialization: run wineboot --init with a timeout
    try:
        proc = subprocess.run(
            [wine_binary, "wineboot", "--init"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # Timed out is expected on headless servers — kill the hung processes
        pass
    except FileNotFoundError:
        return

    # Kill any hung wineboot/wineserver processes
    _kill_wine_processes()


def _kill_wine_processes() -> None:
    """Kill stale wine processes (wineserver, wineboot) that may block."""
    for proc_name in ["wineserver", "wineboot"]:
        try:
            # Read /proc entries to find and kill matching processes
            for proc_entry in os.listdir("/proc"):
                if not proc_entry.isdigit():
                    continue
                try:
                    comm_path = f"/proc/{proc_entry}/comm"
                    with open(comm_path) as f:
                        comm = f.read().strip()
                except (OSError, FileNotFoundError):
                    continue
                if comm == proc_name:
                    try:
                        os.kill(int(proc_entry), 9)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
        except FileNotFoundError:
            # /proc not available
            pass


def _ensure_wine_drive_mapping() -> None:
    """Set up wine D: drive mapping for ATP $INCLUDE path compatibility.

    ATP templates reference library files via absolute DOS paths like
    ``D:\\ATP\\110\\ganzi\\fanji\\noM\\short.lib``. This function creates a
    wine dosdevices symlink so that ``D:\\`` resolves to the ATP legacy root,
    and ensures the required subdirectory structure exists.
    """
    allowed_root = _allowed_root()
    dosdevices = Path(os.path.expanduser("~/.wine/dosdevices"))
    dosdevices.mkdir(parents=True, exist_ok=True)
    d_link = dosdevices / "d:"
    target = str(allowed_root / "ATP")

    if d_link.is_symlink():
        existing = os.readlink(str(d_link))
        if existing == target:
            return
        d_link.unlink()
    elif d_link.exists():
        d_link.unlink()

    d_link.symlink_to(target)

    # Ensure the expected library subdirectory exists
    lib_dir = allowed_root / "ATP" / "ATP" / "110" / "ganzi" / "fanji" / "noM"
    lib_dir.mkdir(parents=True, exist_ok=True)

    # Copy template .lib files into the DOS path location if missing
    template_lib_dir = allowed_root / "ATP" / "templates" / "fanji"
    if template_lib_dir.is_dir():
        for lib_file in template_lib_dir.glob("*.lib"):
            dest = lib_dir / lib_file.name
            if not dest.exists():
                shutil.copy2(str(lib_file), str(dest))


def execute_run_job(*, run_id: str, actor_user_id: str | None) -> None:
    db = SessionLocal()
    try:
        run = get_run_by_id(db, run_id)
        if not run or run.status in {"success", "failed"}:
            return

        _ensure_wine_prefix_initialized()
        _ensure_wine_drive_mapping()

        resolved_binary = run.resolved_binary or _resolve_binary()
        if not resolved_binary:
            _mark_run_failed(db, run=run, actor_user_id=actor_user_id, reason="Wine binary not found")
            return

        command = [resolved_binary, run.exe_path, *(run.arguments_json or [])]
        env = os.environ.copy()
        # Suppress Wine UI popups on headless server
        env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
        env["WINEDEBUG"] = "-all"
        env.update(run.environment_json or {})

        run.status = "running"
        run.started_at = utcnow()
        run.finished_at = None
        run.error_message = None
        run.timed_out = False
        run.update_user = actor_user_id
        run.update_date = utcnow()
        db.commit()

        started_perf = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=run.working_dir,
                env=env,
                capture_output=True,
                timeout=run.timeout_seconds,
                check=False,
            )
            run.exit_code = result.returncode
            run.stdout_text = _truncate_output(_decode_output(result.stdout))
            run.stderr_text = _truncate_output(_decode_output(result.stderr))
            if result.returncode == 0:
                run.status = "success"
                run.error_message = None
            else:
                run.status = "failed"
                run.error_message = f"Wine process exited with code {result.returncode}"
        except subprocess.TimeoutExpired as exc:
            run.status = "failed"
            run.timed_out = True
            run.exit_code = None
            run.stdout_text = _truncate_output(_decode_output(exc.stdout))
            run.stderr_text = _truncate_output(_decode_output(exc.stderr))
            run.error_message = f"Execution timed out after {run.timeout_seconds} seconds"
        except OSError as exc:
            run.status = "failed"
            run.exit_code = None
            run.stdout_text = None
            run.stderr_text = None
            run.error_message = str(exc)

        run.duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
        run.finished_at = utcnow()
        run.update_user = actor_user_id
        run.update_date = utcnow()
        db.commit()

        # Upload task execution log to MinIO for task-monitor page
        if run.task_id:
            try:
                log_parts: list[str] = []
                if run.stderr_text:
                    log_parts.append("[STDERR]")
                    log_parts.append(run.stderr_text)
                if run.stdout_text:
                    log_parts.append("[STDOUT]")
                    log_parts.append(run.stdout_text)
                if run.error_message:
                    log_parts.append(f"[ERROR] {run.error_message}")
                log_content = "\n".join(log_parts)
                if log_content.strip():
                    upload_task_log(run.task_id, log_content)
            except TaskLogServiceError:
                pass  # Log upload failure should not break the task
    finally:
        db.close()


def _mark_run_failed(
    db: Session,
    *,
    run: WineRun,
    actor_user_id: str | None,
    reason: str,
) -> None:
    run.status = "failed"
    run.error_message = reason
    run.finished_at = utcnow()
    run.duration_ms = 0 if run.duration_ms is None else run.duration_ms
    run.update_user = actor_user_id
    run.update_date = utcnow()
    db.commit()

    # Upload failure log to MinIO
    if run.task_id:
        try:
            upload_task_log(run.task_id, f"[ERROR] {reason}")
        except TaskLogServiceError:
            pass


def _dispatch_wine_run_task(*, run_id: str, actor_user_id: str | None):
    from ..tasks.wine_tasks import execute_wine_run_job

    return execute_wine_run_job.delay(run_id, actor_user_id)
