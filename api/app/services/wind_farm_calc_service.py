"""风电场计算 —— 业务编排层（批次校验 + Wine 调度 + 解析落库 + 导出）。

输入只来自 LP-33 已完成的「风电场数据准备」批次：从对象存储取回 file_1~4 + P0.abc，
落到独立工作目录后用受管 exe 在 Wine 中执行，解析 GBK 的 file_out.txt 并落库。
核心程序视为黑盒，本模块不改动其代码与算法。
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import signal
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.wind_data_prep import WindDataPrepBatch, WindDataPrepTurbine
from ..models.wind_farm_calc import WindFarmCalcJob, WindFarmCalcResult
from ..schemas.wind_farm_calc import (
    WindFarmCalcCancelResponse,
    WindFarmCalcCreateResponse,
    WindFarmCalcEngineInfo,
    WindFarmCalcJobDetail,
    WindFarmCalcJobListResponse,
    WindFarmCalcJobSummary,
    WindFarmCalcLogResponse,
    WindFarmCalcPrepBatchOption,
    WindFarmCalcPrepBatchOptions,
    WindFarmCalcResultListResponse,
    WindFarmCalcResultRow,
)
from ..services import minio_storage
from ..services import wind_farm_calc as calc
from ..services.audit_service import compose_audit_detail, write_audit_log
from ..services.wine_probe import probe_wine_binary

WIND_FARM_CALC_TOPIC = "admin.wind-farm-calc"
TASK_NAME = "app.tasks.wind_farm_calc_tasks.run_wind_farm_calc"
API_PREFIX = "/api/v1/wind-farm-calc"
WORK_SUBDIR = "wind-farm-calc"

# LP-33 批次中五个产物字段（与 wind_data_prep_service.FILE_KEY_FIELDS 同口径）
PREP_FILE_FIELDS = {
    "file_1.txt": "file1_key",
    "file_2.txt": "file2_key",
    "file_3.txt": "file3_key",
    "file_4.txt": "file4_key",
    "P0.abc": "p0abc_key",
}

_ACTIVE_STATUSES = ("pending", "processing")


def _settings():
    return get_settings()


# ---------------------------------------------------------------------------
# 引擎解析与信息
# ---------------------------------------------------------------------------
def resolve_engine(raw_path: str | None = None) -> str | None:
    """与 atp_asset_service._resolve_configured_wine_executable 同款路径白名单校验。"""
    configured = (raw_path if raw_path is not None else _settings().wind_farm_calc_executable).strip()
    if not configured:
        return None
    allowed_root = Path(_settings().wine_allowed_root).expanduser().resolve(strict=False)
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = (allowed_root / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    if candidate != allowed_root and allowed_root not in candidate.parents:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return str(candidate)


def _md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wine_binary() -> str:
    configured = (_settings().wine_binary_path or "").strip() or "wine"
    return shutil.which(configured) or configured


def get_engine_info() -> WindFarmCalcEngineInfo:
    configured = _settings().wind_farm_calc_executable or ""
    resolved = resolve_engine(configured)
    info = WindFarmCalcEngineInfo(
        configured=configured,
        resolved=resolved,
        wine_binary=_wine_binary(),
    )
    if resolved:
        path = Path(resolved)
        stat = path.stat()
        info.exists = True
        info.size = int(stat.st_size)
        info.modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
        info.md5 = _md5_of(path)
    else:
        info.message = "引擎未部署：请将 FengLiFangLei-10.exe 放到 wine_allowed_root/wind_farm/ 下"
    probe = probe_wine_binary(_wine_binary(), timeout_seconds=10)
    info.wine_available = probe.available
    info.wine_version = probe.version
    info.wine_error = probe.error
    return info


# ---------------------------------------------------------------------------
# 工作目录
# ---------------------------------------------------------------------------
def _workdir(job_id: str) -> Path:
    """工作目录固定在 wine_allowed_root/wind-farm-calc/{job_id}/，且必须在白名单内。"""
    allowed_root = Path(_settings().wine_allowed_root).expanduser().resolve(strict=False)
    candidate = (allowed_root / WORK_SUBDIR / job_id).resolve(strict=False)
    if candidate != allowed_root and allowed_root not in candidate.parents:
        raise calc.WindFarmCalcError("计算工作目录越出 wine_allowed_root，拒绝执行")
    return candidate


def cleanup_workdir(job_id: str) -> None:
    try:
        shutil.rmtree(_workdir(job_id), ignore_errors=True)
    except Exception:  # noqa: BLE001 - 清理失败不影响主流程
        pass


# ---------------------------------------------------------------------------
# 查询 / 序列化
# ---------------------------------------------------------------------------
def _get_job_or_404(db: Session, job_id: str) -> WindFarmCalcJob:
    job = db.execute(
        select(WindFarmCalcJob).where(
            WindFarmCalcJob.id == job_id,
            WindFarmCalcJob.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="风电场计算任务不存在")
    return job


def _files_ready(batch: WindDataPrepBatch) -> int:
    return sum(1 for key in PREP_FILE_FIELDS.values() if getattr(batch, key, None))


def _summary(job: WindFarmCalcJob) -> WindFarmCalcJobSummary:
    return WindFarmCalcJobSummary(
        id=job.id,
        name=job.name or "",
        prep_batch_id=job.prep_batch_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        task_id=job.task_id,
        error_message=job.error_message,
        cancel_requested=bool(job.cancel_requested),
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=job.duration_seconds,
        turbine_count=job.turbine_count,
        risk_I_count=job.risk_I_count,
        risk_II_count=job.risk_II_count,
        risk_III_count=job.risk_III_count,
        risk_IV_count=job.risk_IV_count,
        shutdown_count=job.shutdown_count,
        circuit_shutdown_count=job.circuit_shutdown_count,
        farm_shutdown_count=job.farm_shutdown_count,
        risk_mismatch_count=job.risk_mismatch_count,
        create_user=job.create_user,
        create_date=job.create_date,
    )


def list_jobs(
    db: Session,
    *,
    keyword: str | None = None,
    status_filter: str | None = None,
    prep_batch_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> WindFarmCalcJobListResponse:
    filters: list[Any] = [WindFarmCalcJob.is_deleted.is_(False)]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(
            or_(WindFarmCalcJob.name.ilike(pattern), WindFarmCalcJob.id.ilike(pattern))
        )
    if status_filter:
        filters.append(WindFarmCalcJob.status == status_filter)
    if prep_batch_id:
        filters.append(WindFarmCalcJob.prep_batch_id == prep_batch_id)
    if date_from:
        filters.append(WindFarmCalcJob.create_date >= date_from)
    if date_to:
        filters.append(WindFarmCalcJob.create_date <= date_to)
    total = db.execute(
        select(func.count()).select_from(WindFarmCalcJob).where(*filters)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindFarmCalcJob)
            .where(*filters)
            .order_by(WindFarmCalcJob.create_date.desc(), WindFarmCalcJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindFarmCalcJobListResponse(total=int(total), items=[_summary(row) for row in rows])


def get_job_detail(db: Session, job_id: str) -> WindFarmCalcJobDetail:
    job = _get_job_or_404(db, job_id)
    return WindFarmCalcJobDetail(
        **_summary(job).model_dump(),
        engine_path=job.engine_path,
        engine_md5=job.engine_md5,
        stdout_object_key=job.stdout_object_key,
        output_object_key=job.output_object_key,
        preflight_json=job.preflight_json,
        update_date=job.update_date,
    )


def list_prep_batch_options(db: Session) -> WindFarmCalcPrepBatchOptions:
    """只列出已完成的准备批次（五个文件齐全），新建页下拉用。"""
    rows = (
        db.execute(
            select(WindDataPrepBatch)
            .where(
                WindDataPrepBatch.is_deleted.is_(False),
                WindDataPrepBatch.status == "completed",
            )
            .order_by(WindDataPrepBatch.create_date.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    items = [
        WindFarmCalcPrepBatchOption(
            id=row.id,
            name=row.name or "",
            wind_farm_name=row.wind_farm_name,
            turbine_count=row.turbine_count,
            grid_nx=row.grid_nx,
            grid_ny=row.grid_ny,
            risk_base_s=row.risk_base_s,
            files_ready=_files_ready(row),
            create_date=row.create_date,
        )
        for row in rows
        if _files_ready(row) == len(PREP_FILE_FIELDS)
    ]
    return WindFarmCalcPrepBatchOptions(items=items)


def list_results(
    db: Session,
    job_id: str,
    *,
    risk_level: int | None = None,
    suggestion_code: int | None = None,
    sort_by: str = "seq",
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> WindFarmCalcResultListResponse:
    job = _get_job_or_404(db, job_id)
    filters: list[Any] = [WindFarmCalcResult.job_id == job.id]
    if risk_level is not None:
        filters.append(WindFarmCalcResult.risk_level == risk_level)
    if suggestion_code is not None:
        filters.append(WindFarmCalcResult.suggestion_code == suggestion_code)
    total = db.execute(
        select(func.count()).select_from(WindFarmCalcResult).where(*filters)
    ).scalar() or 0
    sort_column = {
        "seq": WindFarmCalcResult.seq,
        "value_v": WindFarmCalcResult.value_v,
        "risk_level": WindFarmCalcResult.risk_level,
        "turbine_no": WindFarmCalcResult.turbine_no,
    }.get(sort_by, WindFarmCalcResult.seq)
    order_clause = sort_column.desc() if order.lower() == "desc" else sort_column.asc()
    rows = (
        db.execute(
            select(WindFarmCalcResult)
            .where(*filters)
            .order_by(order_clause, WindFarmCalcResult.seq.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindFarmCalcResultListResponse(
        total=int(total),
        items=[
            WindFarmCalcResultRow(
                seq=row.seq,
                turbine_no=row.turbine_no,
                lon=row.lon,
                lat=row.lat,
                value_v=row.value_v,
                risk_level=row.risk_level,
                suggestion_code=row.suggestion_code,
                suggestion_text=row.suggestion_text,
                circuit_no=row.circuit_no,
                raw_line=row.raw_line,
            )
            for row in rows
        ],
    )


def get_log_info(db: Session, job_id: str) -> WindFarmCalcLogResponse:
    job = _get_job_or_404(db, job_id)
    task_id = job.task_id
    return WindFarmCalcLogResponse(
        job_id=job.id,
        task_id=task_id,
        sse_url=f"/api/v1/admin/task-logs/{task_id}/sse" if task_id else None,
        raw_url=f"/api/v1/admin/task-logs/{task_id}/raw" if task_id else None,
    )


# ---------------------------------------------------------------------------
# 创建 / 取消 / 删除
# ---------------------------------------------------------------------------
def _dispatch_task(job_id: str) -> str | None:
    from ..core.celery_app import celery_app as _celery_app

    try:
        task = _celery_app.send_task(
            TASK_NAME,
            kwargs={"job_id": job_id},
            queue=_settings().wind_farm_calc_queue or "wind_farm_calc",
        )
        return str(task.id)
    except Exception:  # noqa: BLE001 - broker 不可用时不阻塞接口
        return None


def _fetch_prep_files(batch: WindDataPrepBatch) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name, key_field in PREP_FILE_FIELDS.items():
        key = getattr(batch, key_field, None)
        if not key:
            raise calc.WindFarmCalcError(f"数据准备批次缺少 {name} 产物")
        files[name] = minio_storage.get_object(key)
    return files


def create_job(
    db: Session,
    *,
    prep_batch_id: str,
    name: str = "",
    actor_user_id: str,
) -> WindFarmCalcCreateResponse:
    batch = db.execute(
        select(WindDataPrepBatch).where(
            WindDataPrepBatch.id == prep_batch_id,
            WindDataPrepBatch.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="数据准备批次不存在")
    if batch.status != "completed" or _files_ready(batch) != len(PREP_FILE_FIELDS):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="仅可选择已完成且五文件齐全的数据准备批次",
        )
    engine = resolve_engine()
    if not engine:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="计算引擎未部署，请先检查引擎信息",
        )

    # 提交前预检：失败不建记录、不派发任务
    files = _fetch_prep_files(batch)
    report = calc.preflight(files)
    if not report.ok:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"message": "输入文件预检未通过", "checks": report.checks, "errors": report.errors},
        )

    job_id = uuid4().hex
    job = WindFarmCalcJob(
        id=job_id,
        name=(name or "").strip() or batch.name or batch.wind_farm_name or job_id,
        prep_batch_id=batch.id,
        engine_path=engine,
        engine_md5=_md5_of(Path(engine)),
        status="pending",
        stage="fetching",
        progress=0,
        turbine_count=report.params.n if report.params else batch.turbine_count,
        preflight_json=report.as_dict(),
        create_user=actor_user_id,
        create_date=utcnow(),
        update_date=utcnow(),
    )
    db.add(job)
    db.commit()
    write_audit_log(
        db,
        action="wind_farm_calc.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"job_id={job.id}", f"name={job.name}", f"prep_batch_id={batch.id}"
        ),
    )
    db.commit()

    task_id = _dispatch_task(job.id)
    job.task_id = task_id
    job.status = "processing"
    job.started_at = utcnow()
    db.commit()
    return WindFarmCalcCreateResponse(job_id=job.id, task_id=task_id, status="processing")


def cancel_job(db: Session, job_id: str, *, actor_user_id: str) -> WindFarmCalcCancelResponse:
    job = _get_job_or_404(db, job_id)
    if job.status not in _ACTIVE_STATUSES:
        return WindFarmCalcCancelResponse(job_id=job.id, status=job.status)
    job.cancel_requested = True
    job.update_user = actor_user_id
    job.update_date = utcnow()
    db.commit()
    if job.task_id:
        try:
            from ..core.celery_app import celery_app as _celery_app

            _celery_app.control.revoke(job.task_id, terminate=False)
        except Exception:  # noqa: BLE001 - revoke 失败时工作进程仍会轮询取消标志
            pass
    write_audit_log(
        db,
        action="wind_farm_calc.cancel",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"job_id={job.id}", f"name={job.name}"),
    )
    db.commit()
    return WindFarmCalcCancelResponse(job_id=job.id, status=job.status)


def delete_job(db: Session, job_id: str, *, actor_user_id: str) -> None:
    job = _get_job_or_404(db, job_id)
    if job.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="任务仍在运行，请先取消再删除"
        )
    job.is_deleted = True
    job.update_user = actor_user_id
    job.update_date = utcnow()
    db.commit()
    cleanup_workdir(job.id)
    write_audit_log(
        db,
        action="wind_farm_calc.delete",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"job_id={job.id}", f"name={job.name}"),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 任务执行体
# ---------------------------------------------------------------------------
def mark_job_failed(db: Session, job_id: str, error_message: str, *, cancelled: bool = False) -> None:
    job = db.execute(select(WindFarmCalcJob).where(WindFarmCalcJob.id == job_id)).scalar_one_or_none()
    if not job:
        return
    job.status = "cancelled" if cancelled else "failed"
    job.stage = "failed"
    job.error_message = error_message[:3000]
    job.finished_at = utcnow()
    if job.started_at:
        delta = (utcnow() - job.started_at).total_seconds()
        job.duration_seconds = round(max(0.0, delta), 3)
    job.update_date = utcnow()
    db.commit()


def _tail_lines(path: Path, count: int = 30) -> str:
    try:
        with path.open("rb") as handle:
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-count:])[-3000:]
    except OSError:
        return ""


def _kill_group(proc: Any, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def run_job(
    db: Session,
    job_id: str,
    *,
    task_id: str,
    on_progress: Callable[[int, str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Celery 任务体：取文件 → 预检 → Wine 执行 → GBK 解析 → 落库。

    超时与取消三层中的 exe 软/硬上限在此实现；Celery 软/硬上限在任务定义处实现。
    """
    import subprocess

    job = db.execute(select(WindFarmCalcJob).where(WindFarmCalcJob.id == job_id)).scalar_one_or_none()
    if not job:
        raise calc.WindFarmCalcError(f"计算任务不存在（job_id={job_id}）")

    job.status = "processing"
    job.stage = "fetching"
    job.progress = 0
    job.error_message = None
    job.started_at = utcnow()
    db.commit()

    def report(percent: int, stage: str) -> None:
        job.progress = int(max(0, min(100, percent)))
        job.stage = stage
        db.commit()
        if on_progress:
            on_progress(job.progress, stage)

    def log(text: str) -> None:
        if on_log:
            on_log(text)

    engine = resolve_engine(job.engine_path)
    if not engine:
        raise calc.WindFarmCalcError(f"计算引擎不存在或不在白名单内：{job.engine_path}")
    batch = db.execute(
        select(WindDataPrepBatch).where(WindDataPrepBatch.id == job.prep_batch_id)
    ).scalar_one_or_none()
    if not batch:
        raise calc.WindFarmCalcError("来源数据准备批次不存在")

    workdir = _workdir(job_id)
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    files = _fetch_prep_files(batch)
    for name, content in files.items():
        (workdir / name).write_bytes(content)

    report(3, "preflight")
    checked = calc.preflight(files)
    job.preflight_json = checked.as_dict()
    db.commit()
    if not checked.ok:
        raise calc.WindFarmCalcError("预检失败：" + "；".join(checked.errors))
    params = checked.params
    assert params is not None

    stdout_path = workdir / "stdout.log"
    output_path = workdir / "file_out.txt"
    env = {**os.environ}
    env.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d")
    env.setdefault("DISPLAY", "")
    wine_binary = _wine_binary()
    command = [wine_binary, engine]
    log(f"启动计算：exe={engine}，工作目录={workdir}，N={params.n}，S={params.s}")

    state: dict[str, Any] = {"marks": 0, "lines": 0, "tail": deque(maxlen=25)}
    state_lock = threading.Lock()
    total_marks = max(1, checked.grid_rows * calc.CURRENT_LEVELS)
    last_reported = -1

    def read_stdout(pipe: Any) -> None:
        try:
            with stdout_path.open("wb") as log_file:
                for raw_line in pipe:
                    log_file.write(raw_line)
                    line = raw_line.decode("utf-8", errors="replace").rstrip()
                    with state_lock:
                        state["lines"] += 1
                        state["marks"] += calc.count_progress_marks(line)
                        state["tail"].append(line)
        except Exception:  # noqa: BLE001 - 读取线程异常由主流程的 returncode 判定
            pass

    proc = subprocess.Popen(
        command,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,  # 独立进程组：取消 / 超时时 killpg 收割 Wine 全家
    )
    reader = threading.Thread(target=read_stdout, args=(proc.stdout,), daemon=True)
    reader.start()

    settings = _settings()
    soft_timeout = int(settings.wind_farm_calc_exe_soft_timeout_seconds)
    hard_timeout = int(settings.wind_farm_calc_exe_hard_timeout_seconds)
    hard_timer = threading.Timer(hard_timeout, _kill_group, args=(proc, signal.SIGKILL))
    hard_timer.daemon = True
    hard_timer.start()
    started = time.monotonic()
    status_result: str | None = None

    try:
        report(5, "running")
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            cancel_flag = db.execute(
                select(WindFarmCalcJob.cancel_requested).where(WindFarmCalcJob.id == job_id)
            ).scalar()
            if cancel_flag:
                log("收到取消请求，正在终止 Wine 进程组")
                _kill_group(proc, signal.SIGTERM)
                status_result = "cancelled"
                break
            if elapsed >= soft_timeout:
                log(f"exe 执行超过软上限 {soft_timeout}s，主动终止")
                _kill_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    _kill_group(proc, signal.SIGKILL)
                raise calc.WindFarmCalcError(
                    f"计算超过 exe 软超时上限（{soft_timeout}s），已终止"
                )
            with state_lock:
                marks = state["marks"]
            percent = min(95, 5 + int(marks / total_marks * 90))
            if percent != last_reported:
                last_reported = percent
                report(percent, "running")
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                continue

        if status_result != "cancelled":
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill_group(proc, signal.SIGKILL)
                proc.wait()
        reader.join(timeout=10)
        hard_timer.cancel()

        if status_result == "cancelled":
            job.status = "cancelled"
            job.stage = "cancelled"
            job.finished_at = utcnow()
            job.duration_seconds = round(max(0.0, time.monotonic() - started), 3)
            db.commit()
            log("计算已取消，Wine 进程组已终止")
            return {"status": "cancelled", "job_id": job_id}

        returncode = proc.returncode
        if returncode != 0:
            tail = "\n".join(list(state["tail"])[-20:])
            raise calc.WindFarmCalcError(
                f"核心程序退出码 {returncode}，stdout 尾部：\n{tail or '(空)'}"
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise calc.WindFarmCalcError("核心程序未产出 file_out.txt 或文件为空")

        report(92, "parsing")
        parsed = calc.parse_file_out(
            output_path.read_bytes(), s=params.s, expected_n=params.n
        )
        turbine_meta = {
            row.seq: (row.turbine_no, row.circuit)
            for row in db.execute(
                select(WindDataPrepTurbine)
                .where(WindDataPrepTurbine.batch_id == batch.id)
                .order_by(WindDataPrepTurbine.seq.asc())
            ).scalars().all()
        }

        stdout_key = f"wind-farm-calc/{job_id}/stdout.log"
        output_key = f"wind-farm-calc/{job_id}/file_out.txt"
        minio_storage.put_object(stdout_key, stdout_path.read_bytes(), content_type="text/plain")
        minio_storage.put_object(output_key, output_path.read_bytes(), content_type="text/plain")
        job.stdout_object_key = stdout_key
        job.output_object_key = output_key

        report(96, "saving")
        db.execute(WindFarmCalcResult.__table__.delete().where(WindFarmCalcResult.job_id == job.id))
        rows = []
        for row in parsed.rows:
            turbine_no, circuit_no = turbine_meta.get(row.seq, (None, None))
            rows.append(
                {
                    "id": uuid4().hex,
                    "job_id": job.id,
                    "seq": row.seq,
                    "turbine_no": turbine_no,
                    "lon": row.lon,
                    "lat": row.lat,
                    "value_v": row.value_v,
                    "risk_level": row.risk_level,
                    "suggestion_code": row.suggestion_code,
                    "suggestion_text": row.suggestion_text,
                    "circuit_no": circuit_no,
                    "raw_line": row.raw_line,
                }
            )
        if rows:
            db.execute(WindFarmCalcResult.__table__.insert(), rows)

        job.turbine_count = len(rows)
        job.risk_I_count = sum(1 for r in rows if r["risk_level"] == 1)
        job.risk_II_count = sum(1 for r in rows if r["risk_level"] == 2)
        job.risk_III_count = sum(1 for r in rows if r["risk_level"] == 3)
        job.risk_IV_count = sum(1 for r in rows if r["risk_level"] == 4)
        job.shutdown_count = sum(1 for r in rows if r["suggestion_code"] >= 2)
        job.circuit_shutdown_count = sum(1 for r in rows if r["suggestion_code"] == 3)
        job.farm_shutdown_count = sum(1 for r in rows if r["suggestion_code"] == 4)
        job.risk_mismatch_count = parsed.risk_mismatch_count
        job.status = "completed"
        job.stage = "done"
        job.progress = 100
        job.error_message = None
        job.finished_at = utcnow()
        job.duration_seconds = round(max(0.0, time.monotonic() - started), 3)
        job.update_date = utcnow()
        db.commit()
        log(
            f"计算完成：{len(rows)} 台风机，风险 I/II/III/IV = "
            f"{job.risk_I_count}/{job.risk_II_count}/{job.risk_III_count}/{job.risk_IV_count}，"
            f"GBK 风险列对照不一致 {parsed.risk_mismatch_count} 行"
        )
        return {
            "status": "completed",
            "job_id": job.id,
            "turbine_count": len(rows),
            "risk_mismatch_count": parsed.risk_mismatch_count,
        }
    finally:
        hard_timer.cancel()
        if proc.poll() is None:
            _kill_group(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001 - 交给 orphan_reaper 兜底收割
                pass
        if proc.stdout:
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
def export_results(db: Session, job_id: str) -> tuple[bytes, str, str]:
    job = _get_job_or_404(db, job_id)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise HTTPException(status_code=500, detail="服务端缺少 openpyxl，无法导出 Excel") from exc

    rows = (
        db.execute(
            select(WindFarmCalcResult)
            .where(WindFarmCalcResult.job_id == job.id)
            .order_by(WindFarmCalcResult.seq.asc())
        )
        .scalars()
        .all()
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "风电场计算结果"
    headers = [
        "序号", "风机编号", "经度", "纬度", "计算值 V", "风险等级",
        "停运建议", "回路号", "GBK 原始行",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        sheet.append(
            [
                row.seq,
                row.turbine_no or "",
                row.lon,
                row.lat,
                row.value_v,
                calc.RISK_LABELS.get(row.risk_level, str(row.risk_level)),
                row.suggestion_text,
                row.circuit_no if row.circuit_no is not None else "",
                row.raw_line or "",
            ]
        )
    sheet.freeze_panes = "A2"
    sheet.column_dimensions["I"].width = 60
    buffer = io.BytesIO()
    workbook.save(buffer)
    return (
        buffer.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"{(job.name or 'wind-farm-calc')}-results.xlsx",
    )
