"""单风机计算 —— 业务编排层（参数校验 + matlab-wind 调度 + CSV 解析落库 + 导出）。

核心 MATLAB 编译产物视为黑盒：本模块只写 params.json、调度专用 worker、
解析 results/failure_rate_by_theta.csv 并落库，不改动任何算法或积分步长。
"""

from __future__ import annotations

import io
import os
import shutil
import signal
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.wind_turbine_calc import WindTurbineCalcJob, WindTurbineCalcResult
from ..schemas.wind_turbine_calc import (
    WindTurbineCalcCancelResponse,
    WindTurbineCalcCreateResponse,
    WindTurbineCalcEngineInfo,
    WindTurbineCalcJobDetail,
    WindTurbineCalcJobListResponse,
    WindTurbineCalcJobSummary,
    WindTurbineCalcResultListResponse,
    WindTurbineCalcResultRow,
)
from ..services import minio_storage
from ..services import wind_turbine_calc as calc
from ..services.audit_service import compose_audit_detail, write_audit_log

WIND_TURBINE_CALC_TOPIC = "admin.wind-turbine-calc"
TASK_NAME = "app.tasks.wind_turbine_calc_tasks.run_wind_turbine_calc"
API_PREFIX = "/api/v1/wind-turbine-calc"
WORK_SUBDIR = "wind-turbine-calc"
ENGINE_MODULE_SLUG = "wind_turbine_calc"

_ACTIVE_STATUSES = ("pending", "processing")


def _settings():
    return get_settings()


# ---------------------------------------------------------------------------
# 引擎信息（读取 matlab_engine 模块/版本配置）
# ---------------------------------------------------------------------------
def _load_engine_module() -> dict[str, Any] | None:
    from ..services.fault_matlab_engine_service import get_module

    try:
        from ..core.database import SessionLocal

        db = SessionLocal()
        try:
            return get_module(db, ENGINE_MODULE_SLUG)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - 配置读取失败降级为 None
        return None


def get_engine_info() -> WindTurbineCalcEngineInfo:
    settings = _settings()
    configured_dir = settings.wind_turbine_calc_compiled_dir or ""
    exe_name = settings.wind_turbine_calc_exe or ""
    script_name = settings.wind_turbine_calc_launch_script or ""
    module = _load_engine_module()
    active_hash: str | None = None
    active_tag: str | None = None
    if module:
        from ..core.database import SessionLocal
        from ..services.fault_matlab_engine_service import list_versions

        try:
            db = SessionLocal()
            try:
                versions = list_versions(db, ENGINE_MODULE_SLUG)
                releases = versions.get("releases", [])
                active = next((r for r in releases if r.get("is_active")), releases[0] if releases else None)
                if active:
                    active_hash = active.get("version_hash")
                    active_tag = active.get("version_tag")
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            pass

    compiled_dir = Path(configured_dir) if configured_dir else None
    exe_exists = bool(compiled_dir and exe_name and (compiled_dir / exe_name).is_file())
    script_exists = bool(compiled_dir and script_name and (compiled_dir / script_name).is_file())
    info = WindTurbineCalcEngineInfo(
        module_slug=ENGINE_MODULE_SLUG,
        configured_dir=configured_dir,
        compiled_dir_exists=bool(compiled_dir and compiled_dir.is_dir()),
        exe_name=exe_name,
        exe_exists=exe_exists,
        launch_script=script_name,
        launch_script_exists=script_exists,
        runtime_version=settings.wind_turbine_calc_runtime_version or None,
        active_version_hash=active_hash,
        active_version_tag=active_tag,
    )
    if not module:
        info.message = "引擎管理中尚无「单风机计算」模块，请先在引擎管理页确认模块与编译产物"
    elif not (exe_exists or script_exists):
        info.message = (
            f"编译产物未部署到 matlab-wind worker 的 {configured_dir} "
            f"（期望 {exe_name} 或 {script_name}）；请在引擎管理页上传并同步版本"
        )
    return info


# ---------------------------------------------------------------------------
# 工作目录
# ---------------------------------------------------------------------------
def _workdir(job_id: str) -> Path:
    root = Path(_settings().wind_turbine_calc_work_root).expanduser().resolve(strict=False)
    candidate = (root / WORK_SUBDIR / job_id).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise calc.WindTurbineCalcError("计算工作目录越出 wind_turbine_calc_work_root，拒绝执行")
    return candidate


def cleanup_workdir(job_id: str) -> None:
    try:
        shutil.rmtree(_workdir(job_id), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 查询 / 序列化
# ---------------------------------------------------------------------------
def _get_job_or_404(db: Session, job_id: str) -> WindTurbineCalcJob:
    job = db.execute(
        select(WindTurbineCalcJob).where(
            WindTurbineCalcJob.id == job_id,
            WindTurbineCalcJob.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="单风机计算任务不存在")
    return job


def _summary(job: WindTurbineCalcJob) -> WindTurbineCalcJobSummary:
    return WindTurbineCalcJobSummary(
        id=job.id,
        name=job.name or "",
        hub_height=job.hub_height,
        receptor_radii=job.receptor_radii or [],
        blade_length=job.blade_length,
        start_current=job.start_current,
        angle_list=job.angle_list or [],
        angle_count=job.angle_count,
        engine_module=job.engine_module,
        engine_version_hash=job.engine_version_hash,
        engine_version_tag=job.engine_version_tag,
        runtime_version=job.runtime_version,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        task_id=job.task_id,
        error_message=job.error_message,
        cancel_requested=bool(job.cancel_requested),
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_seconds=job.duration_seconds,
        mean_failure_rate=job.mean_failure_rate,
        min_failure_rate=job.min_failure_rate,
        max_failure_rate=job.max_failure_rate,
        create_user=job.create_user,
        create_date=job.create_date,
    )


def list_jobs(
    db: Session,
    *,
    keyword: str | None = None,
    status_filter: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> WindTurbineCalcJobListResponse:
    filters: list[Any] = [WindTurbineCalcJob.is_deleted.is_(False)]
    if keyword:
        pattern = f"%{keyword.strip()}%"
        filters.append(or_(WindTurbineCalcJob.name.ilike(pattern), WindTurbineCalcJob.id.ilike(pattern)))
    if status_filter:
        filters.append(WindTurbineCalcJob.status == status_filter)
    if date_from:
        filters.append(WindTurbineCalcJob.create_date >= date_from)
    if date_to:
        filters.append(WindTurbineCalcJob.create_date <= date_to)
    total = db.execute(
        select(func.count()).select_from(WindTurbineCalcJob).where(*filters)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindTurbineCalcJob)
            .where(*filters)
            .order_by(WindTurbineCalcJob.create_date.desc(), WindTurbineCalcJob.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindTurbineCalcJobListResponse(total=int(total), items=[_summary(row) for row in rows])


def get_job_detail(db: Session, job_id: str) -> WindTurbineCalcJobDetail:
    job = _get_job_or_404(db, job_id)
    return WindTurbineCalcJobDetail(
        **_summary(job).model_dump(),
        min_failure_rate_theta=job.min_failure_rate_theta,
        max_failure_rate_theta=job.max_failure_rate_theta,
        chart_object_key=job.chart_object_key,
        csv_object_key=job.csv_object_key,
        update_date=job.update_date,
    )


def list_results(db: Session, job_id: str, *, limit: int = 100, offset: int = 0) -> WindTurbineCalcResultListResponse:
    job = _get_job_or_404(db, job_id)
    total = db.execute(
        select(func.count()).select_from(WindTurbineCalcResult).where(WindTurbineCalcResult.job_id == job.id)
    ).scalar() or 0
    rows = (
        db.execute(
            select(WindTurbineCalcResult)
            .where(WindTurbineCalcResult.job_id == job.id)
            .order_by(WindTurbineCalcResult.theta_deg.asc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return WindTurbineCalcResultListResponse(
        total=int(total),
        items=[
            WindTurbineCalcResultRow(
                theta_deg=row.theta_deg,
                failure_rate=row.failure_rate,
                failure_rate_pct=row.failure_rate_pct,
            )
            for row in rows
        ],
        summary={
            "mean_failure_rate": job.mean_failure_rate,
            "min_failure_rate": job.min_failure_rate,
            "max_failure_rate": job.max_failure_rate,
            "min_failure_rate_theta": job.min_failure_rate_theta,
            "max_failure_rate_theta": job.max_failure_rate_theta,
            "angle_count": job.angle_count,
        },
    )


# ---------------------------------------------------------------------------
# 创建 / 取消 / 删除
# ---------------------------------------------------------------------------
def _active_engine_meta() -> tuple[str | None, str | None, str | None]:
    """返回创建任务时引擎的 (version_hash, version_tag, runtime_version)。"""
    module = _load_engine_module()
    if not module:
        return None, None, None
    try:
        from ..core.database import SessionLocal
        from ..services.fault_matlab_engine_service import list_versions

        db = SessionLocal()
        try:
            versions = list_versions(db, ENGINE_MODULE_SLUG)
            releases = versions.get("releases", [])
            active = next((r for r in releases if r.get("is_active")), releases[0] if releases else None)
            if not active:
                return None, None, None
            return active.get("version_hash"), active.get("version_tag"), _settings().wind_turbine_calc_runtime_version or None
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return None, None, None


def _dispatch_task(job_id: str, params: dict[str, Any]) -> str | None:
    from ..core.celery_app import celery_app as _celery_app

    try:
        task = _celery_app.send_task(
            TASK_NAME,
            kwargs={"job_id": job_id, "params": params},
            queue=_settings().wind_turbine_calc_queue or "matlab-wind",
        )
        return str(task.id)
    except Exception:  # noqa: BLE001 - broker 不可用时不阻塞接口
        return None


def create_job(
    db: Session,
    *,
    name: str,
    hub_height: float,
    receptor_radii: list[float],
    blade_length: float | None,
    start_current: float,
    angle_list: list[float],
    actor_user_id: str,
) -> WindTurbineCalcCreateResponse:
    checked = calc.validate_params(
        hub_height=hub_height,
        receptor_radii=receptor_radii,
        blade_length=blade_length,
        start_current=start_current,
        angle_list=angle_list,
    )
    if not checked.ok or checked.params is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail={"message": "参数校验未通过", "errors": checked.errors})
    params = checked.params

    version_hash, version_tag, runtime_version = _active_engine_meta()
    job_id = uuid4().hex
    # 留存 params.json 便于复现/对拍
    try:
        minio_storage.put_object(
            f"{WORK_SUBDIR}/{job_id}/params.json",
            calc.build_params_json(params),
            content_type="application/json",
        )
    except Exception:  # noqa: BLE001 - 留存失败不阻断任务
        pass

    job = WindTurbineCalcJob(
        id=job_id,
        name=(name or "").strip() or f"单风机计算-{job_id[:8]}",
        hub_height=params["hub_height"],
        receptor_radii=params["receptor_radii"],
        blade_length=params["blade_length"],
        start_current=params["start_current"],
        angle_list=params["angle_list"],
        angle_count=len(params["angle_list"]),
        engine_module=ENGINE_MODULE_SLUG,
        engine_version_hash=version_hash,
        engine_version_tag=version_tag,
        runtime_version=runtime_version,
        status="pending",
        stage="preparing",
        progress=0,
        create_user=actor_user_id,
        create_date=utcnow(),
        update_date=utcnow(),
    )
    db.add(job)
    db.commit()
    write_audit_log(
        db,
        action="wind_turbine_calc.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"job_id={job.id}", f"name={job.name}", f"angle_count={job.angle_count}"),
    )
    db.commit()

    task_id = _dispatch_task(job.id, params)
    job.task_id = task_id
    job.status = "processing"
    job.started_at = utcnow()
    db.commit()
    return WindTurbineCalcCreateResponse(job_id=job.id, task_id=task_id, status="processing")


def cancel_job(db: Session, job_id: str, *, actor_user_id: str) -> WindTurbineCalcCancelResponse:
    job = _get_job_or_404(db, job_id)
    if job.status not in _ACTIVE_STATUSES:
        return WindTurbineCalcCancelResponse(job_id=job.id, status=job.status)
    job.cancel_requested = True
    job.update_user = actor_user_id
    job.update_date = utcnow()
    db.commit()
    if job.task_id:
        try:
            from ..core.celery_app import celery_app as _celery_app

            _celery_app.control.revoke(job.task_id, terminate=False)
        except Exception:  # noqa: BLE001 - 工作进程仍会轮询取消标志
            pass
    write_audit_log(
        db,
        action="wind_turbine_calc.cancel",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"job_id={job.id}", f"name={job.name}"),
    )
    db.commit()
    return WindTurbineCalcCancelResponse(job_id=job.id, status=job.status)


def delete_job(db: Session, job_id: str, *, actor_user_id: str) -> None:
    job = _get_job_or_404(db, job_id)
    if job.status in _ACTIVE_STATUSES:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="任务仍在运行，请先取消再删除")
    job.is_deleted = True
    job.update_user = actor_user_id
    job.update_date = utcnow()
    db.commit()
    cleanup_workdir(job.id)
    write_audit_log(
        db,
        action="wind_turbine_calc.delete",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(f"job_id={job.id}", f"name={job.name}"),
    )
    db.commit()


# ---------------------------------------------------------------------------
# 任务执行体
# ---------------------------------------------------------------------------
def mark_job_failed(db: Session, job_id: str, error_message: str, *, cancelled: bool = False) -> None:
    job = db.execute(select(WindTurbineCalcJob).where(WindTurbineCalcJob.id == job_id)).scalar_one_or_none()
    if not job:
        return
    job.status = "cancelled" if cancelled else "failed"
    job.stage = "cancelled" if cancelled else "failed"
    job.error_message = error_message[:3000]
    job.finished_at = utcnow()
    if job.started_at:
        job.duration_seconds = round(max(0.0, (utcnow() - job.started_at).total_seconds()), 3)
    job.update_date = utcnow()
    db.commit()


def _kill_group(proc: Any, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _resolve_command(compiled_dir: Path, settings: Any) -> tuple[list[str], str]:
    """优先用启动脚本（内含 Runtime 环境变量），否则直接执行编译产物。"""
    script = compiled_dir / settings.wind_turbine_calc_launch_script
    if settings.wind_turbine_calc_launch_script and script.is_file():
        return ["bash", str(script)], f"启动脚本 {script.name}"
    exe = compiled_dir / settings.wind_turbine_calc_exe
    if settings.wind_turbine_calc_exe and exe.is_file():
        return [str(exe)], f"编译产物 {exe.name}"
    raise calc.WindTurbineCalcError(
        f"matlab-wind 编译产物未部署：{compiled_dir} 下未找到 "
        f"{settings.wind_turbine_calc_launch_script} 或 {settings.wind_turbine_calc_exe}"
    )


def run_job(
    db: Session,
    job_id: str,
    params: dict[str, Any],
    *,
    task_id: str,
    on_progress: Callable[[int, str], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Celery 任务体：写 params.json → 调编译产物 → 解析 CSV → 生成曲线 → 落库。"""
    import subprocess

    job = db.execute(select(WindTurbineCalcJob).where(WindTurbineCalcJob.id == job_id)).scalar_one_or_none()
    if not job:
        raise calc.WindTurbineCalcError(f"计算任务不存在（job_id={job_id}）")

    job.status = "processing"
    job.stage = "preparing"
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

    settings = _settings()
    compiled_dir = Path(settings.wind_turbine_calc_compiled_dir or "")
    if not compiled_dir.is_dir():
        raise calc.WindTurbineCalcError(f"编译产物目录不存在：{compiled_dir}")
    command, source_desc = _resolve_command(compiled_dir, settings)

    workdir = _workdir(job_id)
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "params.json").write_bytes(calc.build_params_json(params))

    stdout_path = workdir / "stdout.log"
    csv_path = workdir / "results" / "failure_rate_by_theta.csv"
    env = {**os.environ}
    env.setdefault("TZ", "Asia/Shanghai")
    log(f"启动单风机计算：{source_desc}，工作目录={workdir}，角度数={len(params['angle_list'])}")

    proc = subprocess.Popen(
        command,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,  # 独立进程组：取消/超时时 killpg 收割 MATLAB Runtime 全家
    )
    reader_done = threading.Event()

    def read_stdout() -> None:
        try:
            with stdout_path.open("wb") as log_file:
                for raw in proc.stdout:
                    log_file.write(raw)
                    log_file.flush()
        except Exception:  # noqa: BLE001
            pass
        finally:
            reader_done.set()

    reader = threading.Thread(target=read_stdout, args=(), daemon=True)
    reader.start()

    soft_timeout = int(settings.wind_turbine_calc_exe_soft_timeout_seconds)
    hard_timeout = int(settings.wind_turbine_calc_exe_hard_timeout_seconds)
    hard_timer = threading.Timer(hard_timeout, _kill_group, args=(proc, signal.SIGKILL))
    hard_timer.daemon = True
    hard_timer.start()
    started = time.monotonic()
    status_result: str | None = None
    expected_angles = max(1, len(params["angle_list"]))

    try:
        report(5, "running")
        while proc.poll() is None:
            elapsed = time.monotonic() - started
            cancel_flag = db.execute(
                select(WindTurbineCalcJob.cancel_requested).where(WindTurbineCalcJob.id == job_id)
            ).scalar()
            if cancel_flag:
                log("收到取消请求，正在终止 MATLAB Runtime 进程组")
                _kill_group(proc, signal.SIGTERM)
                status_result = "cancelled"
                break
            if elapsed >= soft_timeout:
                log(f"执行超过软上限 {soft_timeout}s，主动终止")
                _kill_group(proc, signal.SIGTERM)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    _kill_group(proc, signal.SIGKILL)
                raise calc.WindTurbineCalcError(f"计算超过 exe 软超时上限（{soft_timeout}s），已终止")
            # 进度按已完成角度数：产物若增量写 CSV，按数据行数推进；否则停留在 running。
            try:
                if csv_path.is_file():
                    with csv_path.open("rb") as handle:
                        line_count = max(0, sum(1 for _ in handle) - 1)
                    done = min(expected_angles, line_count)
                    report(min(95, 5 + int(done / expected_angles * 90)), "running")
            except OSError:
                pass
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
            log("计算已取消，MATLAB Runtime 进程组已终止")
            return {"status": "cancelled", "job_id": job_id}

        returncode = proc.returncode
        if returncode != 0:
            tail = ""
            if stdout_path.is_file():
                with stdout_path.open("rb") as handle:
                    tail = "\n".join(handle.read().decode("utf-8", errors="replace").splitlines()[-20:])
            raise calc.WindTurbineCalcError(f"核心程序退出码 {returncode}，stdout 尾部：\n{tail or '(空)'}")

        if not csv_path.is_file() or csv_path.stat().st_size == 0:
            raise calc.WindTurbineCalcError("核心程序未产出 results/failure_rate_by_theta.csv 或文件为空")

        report(92, "parsing")
        parsed = calc.parse_failure_rate_csv(csv_path.read_bytes(), angle_list=params["angle_list"])
        if parsed.has_unrequested_rows:
            extra = len(parsed.all_rows) - len(parsed.rows)
            log(
                f"引擎返回 {len(parsed.all_rows)} 个角度，其中 {extra} 个不在请求的 angle_list 内"
                f"（疑似旧版引擎全角度扫描）；统计与曲线已按请求角度过滤"
            )

        # 曲线：优先产物自带 PNG；若已按请求角度过滤，产物 PNG 画的仍是全角度曲线，改用过滤后数据现画
        chart_bytes: bytes | None = None
        if not parsed.has_unrequested_rows:
            for candidate in (workdir / "results" / "failure_rate_by_theta.png", workdir / "failure_rate_by_theta.png"):
                if candidate.is_file() and candidate.stat().st_size > 0:
                    chart_bytes = candidate.read_bytes()
                    break
        if chart_bytes is None:
            chart_bytes = calc.render_chart_png(parsed)

        csv_key = f"{WORK_SUBDIR}/{job_id}/failure_rate_by_theta.csv"
        chart_key = f"{WORK_SUBDIR}/{job_id}/failure_rate_by_theta.png"
        minio_storage.put_object(csv_key, csv_path.read_bytes(), content_type="text/csv; charset=utf-8")
        minio_storage.put_object(chart_key, chart_bytes, content_type="image/png")
        job.csv_object_key = csv_key
        job.chart_object_key = chart_key

        report(96, "saving")
        db.execute(WindTurbineCalcResult.__table__.delete().where(WindTurbineCalcResult.job_id == job.id))
        db.execute(
            WindTurbineCalcResult.__table__.insert(),
            [
                {
                    "id": uuid4().hex,
                    "job_id": job.id,
                    "theta_deg": row.theta_deg,
                    "failure_rate": row.failure_rate,
                    "failure_rate_pct": row.failure_rate_pct,
                }
                for row in parsed.rows
            ],
        )
        job.mean_failure_rate = parsed.mean_failure_rate
        job.min_failure_rate = parsed.min_failure_rate
        job.max_failure_rate = parsed.max_failure_rate
        job.min_failure_rate_theta = parsed.min_failure_rate_theta
        job.max_failure_rate_theta = parsed.max_failure_rate_theta
        job.status = "completed"
        job.stage = "done"
        job.progress = 100
        job.error_message = None
        job.finished_at = utcnow()
        job.duration_seconds = round(max(0.0, time.monotonic() - started), 3)
        job.update_date = utcnow()
        db.commit()
        log(f"计算完成：{len(parsed.rows)} 个角度，均值失效率={parsed.mean_failure_rate:.17g}")
        return {
            "status": "completed",
            "job_id": job.id,
            "angle_count": len(parsed.rows),
            "mean_failure_rate": parsed.mean_failure_rate,
        }
    finally:
        hard_timer.cancel()
        if proc.poll() is None:
            _kill_group(proc, signal.SIGKILL)
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
        if proc.stdout:
            try:
                proc.stdout.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 导出 / 曲线下载
# ---------------------------------------------------------------------------
def export_results(db: Session, job_id: str, *, export_type: str = "csv") -> tuple[bytes, str, str]:
    job = _get_job_or_404(db, job_id)
    rows = (
        db.execute(
            select(WindTurbineCalcResult)
            .where(WindTurbineCalcResult.job_id == job.id)
            .order_by(WindTurbineCalcResult.theta_deg.asc())
        )
        .scalars()
        .all()
    )
    lines = [",".join(calc.CSV_HEADER)]
    for row in rows:
        lines.append(f"{row.theta_deg:g},{row.failure_rate:.17g},{row.failure_rate_pct:.17g}")
    lines.append("")
    mean_text = f"{job.mean_failure_rate:.17g}" if job.mean_failure_rate is not None else ""
    lines.append(f"# mean_failure_rate,{mean_text}")
    content = ("\n".join(lines)).encode("utf-8-sig")
    if export_type != "all":
        return content, "text/csv; charset=utf-8", f"{(job.name or 'wind-turbine-calc')}-results.csv"

    # type=all：CSV + 曲线 PNG + params.json 打成一个 ZIP
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("failure_rate_by_theta.csv", content)
        if job.chart_object_key:
            try:
                zf.writestr("failure_rate_by_theta.png", minio_storage.get_object(job.chart_object_key))
            except Exception:  # noqa: BLE001
                pass
        try:
            zf.writestr("params.json", minio_storage.get_object(f"{WORK_SUBDIR}/{job.id}/params.json"))
        except Exception:  # noqa: BLE001
            pass
    return (
        buffer.getvalue(),
        "application/zip",
        f"{(job.name or 'wind-turbine-calc')}-results.zip",
    )


def get_chart_bytes(db: Session, job_id: str) -> bytes:
    job = _get_job_or_404(db, job_id)
    if not job.chart_object_key:
        raise HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail="曲线图尚未生成")
    try:
        return minio_storage.get_object(job.chart_object_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="曲线图文件不存在") from exc
