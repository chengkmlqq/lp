from __future__ import annotations

import logging
import os
import signal
import time

from ..core.celery_app import celery_app
from ..services.fl_analysis_service import execute_job

logger = logging.getLogger(__name__)


def _kill_processes_matching(pattern: str) -> int:
    """按 cmdline 关键字杀进程（返回命中数）。

    容器内没有 procps（`ps`/`pkill` 均缺失），因此直接扫 ``/proc`` 自证，
    不依赖外部命令。只匹配 cmdline 含 pattern 的进程，绝不误伤 celery worker 自身。
    """
    victims: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if pattern in cmdline:
            victims.append(pid)
    for pid in victims:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    if victims:
        time.sleep(3)
        for pid in victims:
            try:
                os.kill(pid, signal.SIGKILL)  # 3 秒内未退出的（wine 有时忽略 TERM）补刀
            except OSError:
                pass  # 已退出
    return len(victims)


def _task_pid_path(job_id: str) -> str:
    """任务 PID 文件路径（运行目录内，供取消时精准 SIGKILL）。"""
    root = os.environ.get("FL_ANALYSIS_RUN_ROOT") or "/app/data/wine/atp-models/runs/fl-analysis"
    return f"{root}/{job_id}/.task_pid"


def _write_task_pid(job_id: str) -> None:
    """把当前 worker 子进程 PID 落到任务运行目录。

    为什么需要：``revoke(terminate=True)`` 送的是 SIGTERM，而 celery 子进程此刻往往阻塞在
    ``subprocess.run``（C 调用）里，Python 层信号处理器要等它返回才执行 —— 实测取消后任务
    仍继续计算数十秒，其 DB 事务一直持有 fl_analysis_job 行锁，导致取消状态写不进去。
    落 PID 后，清理任务可以 SIGKILL 该子进程：立刻停机 + 连接断开即释放行锁。
    """
    try:
        path = _task_pid_path(job_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        logger.debug("写任务 PID 文件失败：job=%s", job_id)


def _kill_task_process(job_id: str) -> bool:
    """按 PID 文件 SIGKILL 执行该任务的 celery 子进程（返回是否命中）。

    仅当该 PID 的 cmdline 含 ``celery`` 时才动手，避免误杀（PID 复用/文件残留）。
    """
    try:
        with open(_task_pid_path(job_id)) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return False
    if pid <= 1 or pid == os.getpid():
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        return False  # 进程已退出
    if "celery" not in cmdline:
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return False
    return True


def _ensure_cancelled_status(job_id: str) -> bool:
    """兜底：把仍是 pending/queued/running 的任务置为 cancelled（返回是否发生变更）。

    为什么需要：取消接口写状态时，worker 侧会话可能正持有该 job 行锁（快照计数更新），
    接口按 lock_timeout 重试后仍可能失败。本任务在「任务进程已被杀」之后执行，此时锁
    一般已释放，可安全补写状态，保证前端最终看到「已取消」。

    ⚠️ 本任务自身也必须带 lock_timeout：实测首次实现无超时，被同一把行锁挡了 **71 秒**
    才写成（任务收尾事务未结束时锁仍在）。
    """
    from sqlalchemy import select, text
    from sqlalchemy.exc import OperationalError

    from ..core.database import SessionLocal
    from ..models.base import utcnow
    from ..models.fl_analysis import FlAnalysisJob

    for attempt in range(6):
        db = SessionLocal()
        try:
            db.execute(text("SET LOCAL lock_timeout = '3s'"))
            job = db.execute(select(FlAnalysisJob).where(FlAnalysisJob.id == job_id)).scalar_one_or_none()
            if job is None or job.status not in {"pending", "queued", "running"}:
                return False
            now = utcnow()
            job.status = "cancelled"
            job.error_message = "用户取消"
            job.finished_at = now
            job.update_date = now
            db.commit()
            try:
                from ..services.fl_analysis_service import _publish_change

                _publish_change(
                    "fl_analysis.job.cancelled",
                    {"action": "job_cancelled", "job_id": job_id, "line_id": job.line_id, "fallback": True},
                )
            except Exception:  # noqa: BLE001 —— 事件发布失败不影响状态
                pass
            return True
        except OperationalError as exc:
            db.rollback()
            logger.info("兜底写取消状态遇行锁，重试 %d/6：job=%s err=%s", attempt + 1, job_id, exc)
            time.sleep(3)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("取消状态兜底写入失败：job=%s err=%s", job_id, exc)
            return False
        finally:
            db.close()
    logger.warning("取消状态兜底写入仍被锁阻塞，放弃：job=%s", job_id)
    return False


@celery_app.task(
    name="app.tasks.fl_analysis_tasks.cleanup_cancelled_fl_analysis_run",
    bind=True,
    queue="wine",
)
def cleanup_cancelled_fl_analysis_run(self, job_id: str) -> dict[str, str]:
    """取消任务后：清理残留外部引擎进程 + 兜底写「已取消」状态。

    背景：取消时 ``revoke(terminate=True)`` 只终止执行任务的 worker 子进程，
    其**孙进程**（wine 包装的 tpbig/EGM）可能继续跑完当前一轮 —— 白烧 CPU，
    还会继续往运行目录写文件。这里按运行目录路径 ``runs/fl-analysis/<job_id>/``
    精确匹配 cmdline，只杀属于该任务的进程。
    """
    pattern = f"runs/fl-analysis/{job_id}/"
    killed = 0
    task_killed = False
    error = ""
    try:
        # 1) 先 SIGKILL 执行该任务的 celery 子进程（SIGTERM 对它不即时生效，见 _write_task_pid 注释）
        task_killed = _kill_task_process(job_id)
        time.sleep(1)
        # 2) 再清残留的外部引擎孙进程（wine / tpbig / rjtzl_egm*.exe）
        killed = _kill_processes_matching(pattern)
    except Exception as exc:  # noqa: BLE001 —— 清理是 best-effort
        error = str(exc)
        logger.warning("取消清理失败：job=%s err=%s", job_id, exc)
    status_fixed = _ensure_cancelled_status(job_id)
    logger.info(
        "取消清理完成：job=%s 杀任务进程=%s 命中引擎进程数=%d 兜底写状态=%s",
        job_id, task_killed, killed, status_fixed,
    )
    return {
        "job_id": job_id,
        "task_process_killed": str(task_killed),
        "killed": str(killed),
        "status_fallback_written": str(status_fixed),
        "error": error,
    }


@celery_app.task(name="app.tasks.fl_analysis_tasks.execute_fl_analysis_job", bind=True, queue="wine")
def execute_fl_analysis_job(self, job_id: str) -> dict[str, str]:
    task_id = self.request.id
    # 记录本子进程 PID：取消时清理任务据此 SIGKILL（SIGTERM 对阻塞在 C 调用的进程不即时生效）
    _write_task_pid(job_id)
    log_parts: list[str] = [f"[{task_id}] Starting FL analysis job {job_id}"]
    try:
        from ..services.task_log_service import append_task_log_lines, mark_task_log_end

        append_task_log_lines(task_id, log_parts)
        execute_job(job_id)
        log_parts.append(f"[{task_id}] FL analysis job {job_id} completed successfully")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        try:
            mark_task_log_end(task_id)
        except Exception:
            pass
        return {"job_id": job_id, "status": "done"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] FL analysis job {job_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        try:
            from ..services.task_log_service import append_task_log_lines, mark_task_log_end
            append_task_log_lines(task_id, log_parts)
            mark_task_log_end(task_id)
        except Exception:
            pass
        raise