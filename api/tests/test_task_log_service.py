"""
Basic unit tests for task log service.
"""
from __future__ import annotations

import sys

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

    assert "MinIO storage is not enabled" in str(exc_info.value)


@patch("app.services.task_log_service.get_settings")
def test_get_task_log_minio_disabled(mock_get_settings):
    """Test retrieval fails when MinIO is disabled"""
    mock_settings = MagicMock()
    mock_settings.minio_enabled = False
    mock_get_settings.return_value = mock_settings

    with pytest.raises(TaskLogServiceError) as exc_info:
        get_task_log("task-123")

    assert "MinIO storage is not enabled" in str(exc_info.value)


# ---------------------------------------------------------------------------
# cleanup_expired_task_logs（LP-283：任务日志保留期清理）
# boto3 在函数内惰性 import，因此通过 patch sys.modules 注入假 boto3
# ---------------------------------------------------------------------------
def _make_settings():
    settings = MagicMock()
    settings.minio_enabled = True
    settings.minio_access_key = "ak"
    settings.minio_secret_key = "sk"
    settings.minio_endpoint = "http://minio:9000"
    settings.minio_region = "us-east-1"
    settings.minio_bucket = "fquiz-files"
    return settings


def _fake_paginator(pages):
    paginator = MagicMock()
    paginator.paginate.return_value = pages
    return paginator


def _patch_boto3():
    fake_boto3 = MagicMock()
    p = patch.dict(sys.modules, {"boto3": fake_boto3})
    p.start()
    return fake_boto3


@patch("app.services.task_log_service.get_settings")
def test_cleanup_expired_deletes_only_expired(mock_get_settings):
    """Only objects older than retain_days are deleted; fresh objects are kept."""
    mock_get_settings.return_value = _make_settings()

    old_key = "logs/task-old.log"
    fresh_key = "logs/task-fresh.log"
    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    last_modified_old = now - timedelta(days=40)
    last_modified_fresh = now - timedelta(days=5)

    fake_boto3 = _patch_boto3()
    client = MagicMock()
    pages = [
        {
            "Contents": [
                {"Key": old_key, "LastModified": last_modified_old},
                {"Key": fresh_key, "LastModified": last_modified_fresh},
            ]
        }
    ]
    client.get_paginator.return_value = _fake_paginator(pages)
    fake_boto3.session.Session.return_value.client.return_value = client

    try:
        deleted = cleanup_expired_task_logs(retain_days=30, now=now)
    finally:
        patch.stopall()

    assert deleted == 1
    client.delete_object.assert_called_once_with(Bucket="fquiz-files", Key=old_key)

    called_keys = [call.kwargs["Key"] for call in client.delete_object.call_args_list]
    assert called_keys == [old_key]
    assert fresh_key not in called_keys


@patch("app.services.task_log_service.get_settings")
def test_cleanup_paginates_multiple_pages(mock_get_settings):
    """分页遍历：多页对象都应被评估，最后一页超期对象同样被删。"""
    mock_get_settings.return_value = _make_settings()

    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    old_1 = now - timedelta(days=100)
    old_2 = now - timedelta(days=60)

    fake_boto3 = _patch_boto3()
    client = MagicMock()
    pages = [
        {"Contents": [{"Key": "logs/a.log", "LastModified": old_1}]},
        {"Contents": [{"Key": "logs/b.log", "LastModified": old_2}]},
    ]
    client.get_paginator.return_value = _fake_paginator(pages)
    fake_boto3.session.Session.return_value.client.return_value = client

    try:
        deleted = cleanup_expired_task_logs(retain_days=30, now=now)
    finally:
        patch.stopall()

    assert deleted == 2
    # 分页必须只扫 logs/ 前缀
    assert client.get_paginator.return_value.paginate.call_args.kwargs["Prefix"] == "logs/"
    assert client.delete_object.call_count == 2


@patch("app.services.task_log_service.get_settings")
def test_cleanup_respects_retain_days_zero(mock_get_settings):
    """retain_days=0 表示永久保留，直接返回 0，不触碰 MinIO。"""
    mock_get_settings.return_value = _make_settings()

    fake_boto3 = _patch_boto3()
    try:
        deleted = cleanup_expired_task_logs(retain_days=0)
    finally:
        patch.stopall()

    assert deleted == 0
    fake_boto3.session.Session.assert_not_called()


@patch("app.services.task_log_service.get_settings")
def test_cleanup_dry_run_does_not_delete(mock_get_settings):
    """dry_run=True 时仅统计，不调用 delete_object。"""
    mock_get_settings.return_value = _make_settings()

    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=100)
    fake_boto3 = _patch_boto3()
    client = MagicMock()
    client.get_paginator.return_value = _fake_paginator(
        [{"Contents": [{"Key": "logs/a.log", "LastModified": old}]}]
    )
    fake_boto3.session.Session.return_value.client.return_value = client

    try:
        deleted = cleanup_expired_task_logs(retain_days=30, now=now, dry_run=True)
    finally:
        patch.stopall()

    assert deleted == 1
    client.delete_object.assert_not_called()


@patch("app.services.task_log_service.get_settings")
def test_cleanup_minio_disabled(mock_get_settings):
    """MinIO 未启用时抛 TaskLogServiceError。"""
    settings = _make_settings()
    settings.minio_enabled = False
    mock_get_settings.return_value = settings

    with pytest.raises(TaskLogServiceError) as exc_info:
        cleanup_expired_task_logs(retain_days=30)

    assert "MinIO storage is not enabled" in str(exc_info.value)
