from __future__ import annotations

import io
import logging
import os
import shutil
import zipfile
from pathlib import Path

from ..core.celery_app import celery_app

logger = logging.getLogger(__name__)

MATLAB_ENGINE_TOPIC = "admin.matlab-engine"
LEGACY_DEFAULT_SLUG = "waveform_diagnosis"


def _publish_sync_event(event_name: str, payload: dict) -> None:
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            MATLAB_ENGINE_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/fault-matlab/modules", "/api/v1/fault-matlab/modules/{slug}/versions"],
            dedupe_key=f"{event_name}:{payload.get('slug')}:{payload.get('version_hash', 'unknown')}",
        )
    except Exception:
        pass


@celery_app.task(
    name="app.tasks.sync_matlab_engine_task.sync_matlab_engine_module",
    bind=True,
    queue="default",
    soft_time_limit=120,
    time_limit=180,
)
def sync_matlab_engine_module(self, slug: str, version_hash: str, worker_deploy_path: str, actor_user_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [
        f"[{task_id}] Syncing MATLAB engine module={slug} version={version_hash}",
        f"[{task_id}] Target deploy path={worker_deploy_path}",
    ]

    try:
        from ..services.minio_storage import get_object, build_matlab_engine_release_prefix

        _publish_sync_event("engine.sync_started", {
            "slug": slug,
            "version_hash": version_hash,
            "task_id": task_id,
        })

        target_dir = Path(worker_deploy_path) if worker_deploy_path else None
        if not target_dir:
            from ..core.config import get_settings
            fallback = (get_settings().fault_diag_matlab_compiled_dir or "").strip()
            if not fallback:
                raise RuntimeError("worker_deploy_path is not configured for module and FAULT_DIAG_MATLAB_COMPILED_DIR is empty")
            target_dir = Path(fallback)

        target_dir.mkdir(parents=True, exist_ok=True)

        zip_key = f"{build_matlab_engine_release_prefix(slug, version_hash)}engine.zip"
        log_parts.append(f"[{task_id}] Downloading engine ZIP from MinIO: {zip_key}")
        zip_data = get_object(zip_key)

        backup_dir = target_dir.parent / f"{target_dir.name}_backup_{version_hash}"
        if target_dir.exists() and any(target_dir.iterdir()):
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.copytree(target_dir, backup_dir)
            log_parts.append(f"[{task_id}] Backed up current engine to {backup_dir}")

        for item in target_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            zf.extractall(target_dir)

        log_parts.append(f"[{task_id}] Extracted engine files to {target_dir}")

        exe_names = ("RunWaveAnalysisModule", "waveform_engine_v2.exe", "waveform_engine.exe")
        found = [n for n in exe_names if (target_dir / n).is_file()]
        if not found:
            log_parts.append(f"[{task_id}] WARNING: No known executable found in {target_dir}")
        else:
            log_parts.append(f"[{task_id}] Found executables: {', '.join(found)}")

        _publish_sync_event("engine.sync_completed", {
            "slug": slug,
            "version_hash": version_hash,
            "task_id": task_id,
            "target_dir": str(target_dir),
            "executables_found": found,
        })

        log_parts.append(f"[{task_id}] MATLAB engine sync completed for module={slug} version={version_hash}")
        log_content = "\n".join(log_parts)

        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass

        return {
            "slug": slug,
            "version_hash": version_hash,
            "status": "done",
            "target_dir": str(target_dir),
        }

    except Exception as exc:
        import traceback

        _publish_sync_event("engine.sync_failed", {
            "slug": slug,
            "version_hash": version_hash,
            "task_id": task_id,
            "error": str(exc),
        })

        log_parts.append(f"[{task_id}] MATLAB engine sync FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)

        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass

        raise


@celery_app.task(
    name="app.tasks.sync_matlab_engine_task.sync_matlab_engine",
    bind=True,
    queue="default",
    soft_time_limit=120,
    time_limit=180,
)
def sync_matlab_engine(self, version_hash: str, actor_user_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Syncing legacy MATLAB engine version {version_hash}"]

    try:
        from ..core.config import get_settings
        from ..services.minio_storage import get_object, MATLAB_ENGINE_PREFIX

        _publish_sync_event("engine.sync_started", {
            "slug": LEGACY_DEFAULT_SLUG,
            "version_hash": version_hash,
            "task_id": task_id,
        })

        settings = get_settings()
        target_dir = Path(settings.fault_diag_matlab_compiled_dir)
        if not target_dir:
            raise RuntimeError("FAULT_DIAG_MATLAB_COMPILED_DIR is not configured")

        target_dir.mkdir(parents=True, exist_ok=True)

        zip_key = f"{MATLAB_ENGINE_PREFIX}{version_hash}/engine.zip"
        log_parts.append(f"[{task_id}] Downloading engine ZIP from MinIO: {zip_key}")
        zip_data = get_object(zip_key)

        backup_dir = target_dir.parent / f"{target_dir.name}_backup_{version_hash}"
        if target_dir.exists() and any(target_dir.iterdir()):
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.copytree(target_dir, backup_dir)
            log_parts.append(f"[{task_id}] Backed up current engine to {backup_dir}")

        for item in target_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item, ignore_errors=True)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            zf.extractall(target_dir)

        log_parts.append(f"[{task_id}] Extracted engine files to {target_dir}")

        exe_names = ("RunWaveAnalysisModule", "waveform_engine_v2.exe", "waveform_engine.exe")
        found = [n for n in exe_names if (target_dir / n).is_file()]
        if not found:
            log_parts.append(f"[{task_id}] WARNING: No known executable found in {target_dir}")
        else:
            log_parts.append(f"[{task_id}] Found executables: {', '.join(found)}")

        _publish_sync_event("engine.sync_completed", {
            "slug": LEGACY_DEFAULT_SLUG,
            "version_hash": version_hash,
            "task_id": task_id,
            "target_dir": str(target_dir),
            "executables_found": found,
        })

        log_parts.append(f"[{task_id}] MATLAB engine sync completed for version {version_hash}")
        log_content = "\n".join(log_parts)

        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass

        return {
            "version_hash": version_hash,
            "status": "done",
            "target_dir": str(target_dir),
        }

    except Exception as exc:
        import traceback

        _publish_sync_event("engine.sync_failed", {
            "slug": LEGACY_DEFAULT_SLUG,
            "version_hash": version_hash,
            "task_id": task_id,
            "error": str(exc),
        })

        log_parts.append(f"[{task_id}] MATLAB engine sync FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)

        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass

        raise
