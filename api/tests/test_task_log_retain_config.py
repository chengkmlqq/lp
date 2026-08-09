"""LP-283：task_log_retain_days 配置项（默认 30 天，0=永久保留，负数为非法）。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import Settings


def test_task_log_retain_days_default_30():
    """默认保留 30 天。"""
    settings = Settings()
    assert settings.task_log_retain_days == 30


def test_task_log_retain_days_allow_zero_for_forever():
    """0=永久保留，不触发正整数校验。"""
    with patch.dict("os.environ", {"TASK_LOG_RETAIN_DAYS": "0"}):
        settings = Settings()
        assert settings.task_log_retain_days == 0


def test_task_log_retain_days_custom():
    """可通过环境变量覆盖。"""
    with patch.dict("os.environ", {"TASK_LOG_RETAIN_DAYS": "7"}):
        settings = Settings()
        assert settings.task_log_retain_days == 7


def test_task_log_retain_days_negative_invalid():
    """负数配置应校验失败。"""
    with patch.dict("os.environ", {"TASK_LOG_RETAIN_DAYS": "-1"}):
        with pytest.raises(Exception):
            Settings()
