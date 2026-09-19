from __future__ import annotations

from celery import Celery

from .config import get_settings

settings = get_settings()

celery_app = Celery(
    "fquiz",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=[
        "app.tasks.atp_asset_tasks",
        "app.tasks.elevation_tasks",
        "app.tasks.fl_analysis_tasks",
        "app.tasks.fault_diagnosis_tasks",
        "app.tasks.lightning_tasks",
        "app.tasks.log_cleanup_tasks",
        "app.tasks.scheduled_task_tasks",
        "app.tasks.sync_matlab_engine_task",
        "app.tasks.traveling_wave_tasks",
        "app.tasks.worker_registry_tasks",
    ],
)

celery_app.conf.update(
    accept_content=["json"],
    beat_schedule={
        "sweep-worker-registry-offline": {
            "task": "app.tasks.worker_registry_tasks.sweep_worker_registry_offline",
            "schedule": 30.0,
        },
        "dispatch-due-scheduled-tasks": {
            "task": "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks",
            "schedule": 60.0,
        },
        "flush-task-log-buffers": {
            "task": "app.tasks.worker_registry_tasks.flush_task_log_buffers",
            "schedule": 30.0,
        },
        "cleanup-expired-task-logs": {
            "task": "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
            "schedule": 3600.0,  # 每小时清理一次（与 30 天保留期解耦，无需更频繁）
        },
        "cleanup-expired-lightning-temp-files": {
            "task": "app.tasks.lightning_tasks.cleanup_lightning_temp_files",
            "schedule": 3600.0,  # 每小时清理一次（覆盖 24h 保留期的孤儿临时文件）
        },
    },
    # Redis broker 默认 visibility_timeout=3600s，重任务（如雷电分布导入约 106 分钟）超 1 小时
    # 会被 Redis 重新投递，导致同一任务被两个 worker 并行执行。
    # ⚠️ 2026-09-18：实测防雷任务单任务可跑 10 小时以上（159 塔约 10.2h），6h（21600s）仍会被
    # 超时重投 → 同 task 双执行 → 结果表翻倍。调大到 86400s（24h）覆盖最长任务耗时。
    broker_transport_options={"visibility_timeout": 86400},
    enable_utc=True,
    result_serializer="json",
    # 心跳间隔显式设为 15s，替代 Celery event 模式约 2s 的默认值，降低每个 worker 对
    # worker_registry 表的心跳 UPSERT 写频率（2s → 15s）。配合 worker_registry_ttl_seconds=90，
    # 90s 内可收约 6 次心跳，离线判定仍可靠（TTL ≥ 3× 心跳间隔）。
    worker_heartbeat_interval=15.0,
    task_acks_late=True,
    # worker 异常退出时任务消息被 reject 而非 ack，配合 acks_late 让消息及时回到队列
    # 由其他 worker 继续处理，而不是依赖 Redis visibility_timeout 的漫长等待。
    task_reject_on_worker_lost=True,
    task_serializer="json",
    task_track_started=True,
    timezone=settings.celery_timezone,
    worker_prefetch_multiplier=1,
)

# Register worker lifecycle signals for auto-registration/heartbeat/offline states.
from . import worker_signals as _worker_signals  # noqa: F401,E402
# Register task lifecycle signals for persistent task history in PostgreSQL.
from . import task_history_signals as _task_history_signals  # noqa: F401,E402
# Ensure TaskLogCapture is installed at worker startup (root handler + stdout/stderr Tee).
from . import task_log_capture as _task_log_capture  # noqa: F401,E402
# Re-install TaskLogCapture after Celery clears logging on the forked worker process.
# Celery's setup_logging may wipe root handlers; re-install guarantees capture works.
from celery.signals import worker_process_init


def _reinstall_task_log_capture(**kwargs):  # type: ignore[no-untyped-def]
    import logging as _logging

    from .config import get_settings as _get_settings

    # Re-import task_history_signals and explicitly register its signal handlers
    # in the forked worker child process. Celery prefork inherits sys.modules cache,
    # so a plain import won't re-execute module-level @signals.connect decorators.
    from . import task_history_signals as _ths  # noqa: F401

    # Force re-registration of signal handlers in this process.
    # ⚠️ 该函数在 task_history_signals 中并不存在（历史重构遗留）——此前这里直接调用会抛
    # AttributeError，导致 worker 子进程初始化时整段 handler 中断、下面的日志捕获安装被跳过
    # （2026-09-15 在 worker 启动日志中实测到该报错）。用 getattr 兜底，缺函数不作为致命错误。
    _register = getattr(_ths, "_register_setup_logging_receiver", None)
    if callable(_register):
        _register()

    root = _logging.getLogger()
    root_has_capture = any(
        type(h).__name__ == "_CaptureHandler" for h in root.handlers
    )
    if not root_has_capture:
        _task_log_capture.TaskLogCapture.install(force=True)


worker_process_init.connect(_reinstall_task_log_capture, weak=False)


# ---------------------------------------------------------------------------
# 孤儿进程收割（wine/tpbig 孙进程 reparent 到 worker，不收割会堆积僵尸直至
# EAGAIN。容器化 wine 经典问题，见 app/core/orphan_reaper.py 模块 docstring。）
# ---------------------------------------------------------------------------
from app.core.orphan_reaper import enable_subreaper, start_orphan_reaper
from celery.signals import worker_ready, worker_process_init as _wpi

_MAIN_ORPHAN_REAPER_STARTED = False
# 每个 worker 子进程（fork 后）都会 `worker_process_init`，用 per-child 标记避免重复起线程。
# 注意：子进程是从主进程 fork 而来，Python 全局变量会被继承；fork 后初始化线程即可。
_CHILD_ORPHAN_REAPER_STARTED = False


def _init_main_process_reaper(**kwargs):  # type: ignore[no-untyped-def]
    """主进程（prefork 调度者）设为 subreaper 并启动常驻收割线程。

    僵尸的父进程是 celery worker **主进程**（复盘：19033 个僵尸全挂在主进程 pid 下）。
    subreaper + 守护线程 waitpid(-1, WNOHANG) 周期性收割 reparent 上来的孤儿孙进程，
    根治 wine 造成的僵尸堆积。只有主进程需要常驻收割线程。
    """
    global _MAIN_ORPHAN_REAPER_STARTED
    if _MAIN_ORPHAN_REAPER_STARTED:
        return
    _MAIN_ORPHAN_REAPER_STARTED = True
    # 无条件启动收割线程（即使 subreaper 设置失败也先让 waitpid 尽量收割直接子进程）；
    # 若承接孤儿孙进程，仍依赖 subreaper 语义，因此单独再尝试一次设置。
    try:
        enable_subreaper()
    except Exception:  # noqa: BLE001 —— subreaper 失败不阻断收割线程
        pass
    start_orphan_reaper(interval_seconds=10.0)


def _init_worker_child_reaper(**kwargs):  # type: ignore[no-untyped-def]
    """每个 fork 出的 worker 子进程设 subreaper + 启动独立收割线程。

    实测（2026-09-16）：僵尸堆积在**执行任务的 worker 子进程**（宿主 1124823，即 fork 后
    跑 wine 的子进程）下，而非主进程。每次 `subprocess.run(wine ...)` 会启动 wine 的常驻
    daemon（wineserver / wine64 / services.exe / winedevice...），这些孙进程 reparent 到本
    子进程（已设 subreaper）后退出变僵尸；若本子进程没有收割线程，就会像主进程一样堆积。

    因此除主进程外，每个 worker 子进程也要单独启一个 daemon 收割线程。
    """
    global _CHILD_ORPHAN_REAPER_STARTED
    try:
        enable_subreaper()
    except Exception:  # noqa: BLE001 —— subreaper 失败不阻断收割线程
        pass
    # fork 后线程不复存在，因此这里始终新起一个（而非判断 per-child 标记 —— 每个
    # 子进程都是新 fork 的，主进程的 _CHILD 标记是 False；只需防单进程内重复）。
    if not _CHILD_ORPHAN_REAPER_STARTED:
        _CHILD_ORPHAN_REAPER_STARTED = True
        start_orphan_reaper(interval_seconds=10.0)


worker_ready.connect(_init_main_process_reaper, weak=False)
_wpi.connect(_init_worker_child_reaper, weak=False)
