"""
Basic unit tests for task log service.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.services.task_log_service import (
    TaskLogServiceError,
    TaskLogNotFoundError,
    _get_log_path,
    _get_legacy_log_path,
    cleanup_expired_task_logs,
    upload_task_log,
    get_task_log,
)


def test_get_log_path_with_timestamp():
    """Test fixed log path generation (no longer date-based)"""
    timestamp = datetime(2026, 6, 28, 12, 30, 45, tzinfo=timezone.utc)
    task_id = "test-task-123"

    result = _get_log_path(task_id, timestamp)

    assert result == "logs/test-task-123.log"


def test_get_log_path_without_timestamp():
    """Test log path generation with current timestamp"""
    task_id = "test-task-456"

    result = _get_log_path(task_id)

    assert result == "logs/test-task-456.log"


def test_get_legacy_log_path_keeps_date_pattern():
    """Legacy fallback path retains the date-based pattern for old logs"""
    timestamp = datetime(2026, 6, 28, 12, 30, 45, tzinfo=timezone.utc)
    task_id = "test-task-123"

    result = _get_legacy_log_path(task_id, timestamp)

    assert result == "logs/2026/06/28/test-task-123.log"


@patch("app.services.task_log_service.get_settings")
def test_upload_task_log_minio_disabled(mock_get_settings):
    """Test upload fails when MinIO is disabled"""
    mock_settings = MagicMock()
    mock_settings.minio_enabled = False
    mock_get_settings.return_value = mock_settings

    with pytest.raises(TaskLogServiceError) as exc_info:
        upload_task_log("task-123", "log content")

    assert "Object storage is not enabled" in str(exc_info.value)


@patch("app.services.task_log_service.get_settings")
def test_get_task_log_minio_disabled(mock_get_settings):
    """Test retrieval fails when MinIO is disabled"""
    mock_settings = MagicMock()
    mock_settings.minio_enabled = False
    mock_get_settings.return_value = mock_settings

    with pytest.raises(TaskLogServiceError) as exc_info:
        get_task_log("task-123")

    assert "Object storage is not enabled" in str(exc_info.value)


# ---------------------------------------------------------------------------
# cleanup_expired_task_logs（LP-283：任务日志保留期清理）
# 2026-11-08 起实现走 minio_storage 双后端（local/s3），测试直接 patch 抽象层
# ---------------------------------------------------------------------------
def _make_settings():
    settings = MagicMock()
    settings.minio_enabled = True
    return settings


@patch("app.services.task_log_service.get_settings")
@patch("app.services.minio_storage.delete_object")
@patch("app.services.minio_storage.list_object_mtimes")
def test_cleanup_expired_deletes_only_expired(mock_list, mock_delete, mock_get_settings):
    """Only objects older than retain_days are deleted; fresh objects are kept."""
    mock_get_settings.return_value = _make_settings()

    old_key = "logs/task-old.log"
    fresh_key = "logs/task-fresh.log"
    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    last_modified_old = now - timedelta(days=40)
    last_modified_fresh = now - timedelta(days=5)

    mock_list.return_value = [
        (old_key, last_modified_old),
        (fresh_key, last_modified_fresh),
    ]

    deleted = cleanup_expired_task_logs(retain_days=30, now=now)

    assert deleted == 1
    mock_delete.assert_called_once_with(old_key)


@patch("app.services.task_log_service.get_settings")
@patch("app.services.minio_storage.delete_object")
@patch("app.services.minio_storage.list_object_mtimes")
def test_cleanup_paginates_multiple_pages(mock_list, mock_delete, mock_get_settings):
    """多页/多对象：全部对象都应被评估，超期对象同样被删。"""
    mock_get_settings.return_value = _make_settings()

    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    old_1 = now - timedelta(days=100)
    old_2 = now - timedelta(days=60)

    mock_list.return_value = [
        ("logs/a.log", old_1),
        ("logs/b.log", old_2),
    ]

    deleted = cleanup_expired_task_logs(retain_days=30, now=now)

    assert deleted == 2
    # 必须只扫 logs/ 前缀
    assert mock_list.call_args.args[0] == "logs/"
    assert mock_delete.call_count == 2


@patch("app.services.task_log_service.get_settings")
def test_cleanup_respects_retain_days_zero(mock_get_settings):
    """retain_days=0 表示永久保留，直接返回 0，不触碰对象存储。"""
    mock_get_settings.return_value = _make_settings()

    with patch("app.services.minio_storage.list_object_mtimes") as mock_list:
        deleted = cleanup_expired_task_logs(retain_days=0)

    assert deleted == 0
    mock_list.assert_not_called()


@patch("app.services.task_log_service.get_settings")
@patch("app.services.minio_storage.delete_object")
@patch("app.services.minio_storage.list_object_mtimes")
def test_cleanup_dry_run_does_not_delete(mock_list, mock_delete, mock_get_settings):
    """dry_run=True 时仅统计，不调用 delete_object。"""
    mock_get_settings.return_value = _make_settings()

    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=100)
    mock_list.return_value = [("logs/a.log", old)]

    deleted = cleanup_expired_task_logs(retain_days=30, now=now, dry_run=True)

    assert deleted == 1
    mock_delete.assert_not_called()


@patch("app.services.task_log_service.get_settings")
def test_cleanup_minio_disabled(mock_get_settings):
    """对象存储未启用时抛 TaskLogServiceError。"""
    settings = _make_settings()
    settings.minio_enabled = False
    mock_get_settings.return_value = settings

    with pytest.raises(TaskLogServiceError) as exc_info:
        cleanup_expired_task_logs(retain_days=30)

    assert "Object storage is not enabled" in str(exc_info.value)
