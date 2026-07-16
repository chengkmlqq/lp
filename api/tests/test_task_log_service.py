"""
Basic unit tests for task log service.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.task_log_service import (
    TaskLogServiceError,
    TaskLogNotFoundError,
    _get_log_path,
    upload_task_log,
    get_task_log,
)


def test_get_log_path_with_timestamp():
    """Test log path generation with specific timestamp"""
    timestamp = datetime(2026, 6, 28, 12, 30, 45, tzinfo=timezone.utc)
    task_id = "test-task-123"

    result = _get_log_path(task_id, timestamp)

    assert result == "logs/2026/06/28/test-task-123.log"


def test_get_log_path_without_timestamp():
    """Test log path generation with current timestamp"""
    task_id = "test-task-456"

    result = _get_log_path(task_id)

    # Should contain the task_id and follow the pattern
    assert task_id in result
    assert result.startswith("logs/")
    assert result.endswith(f"/{task_id}.log")


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
