"""LP-293：audit_log_retain_days 配置项（默认 90 天，0=永久保留，负数为非法）。"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.config import Settings


def test_audit_log_retain_days_default_90():
    """默认保留 90 天。"""
    settings = Settings()
    assert settings.audit_log_retain_days == 90


def test_audit_log_retain_days_allow_zero_for_forever():
    """0=永久保留，不触发非法校验。"""
    with patch.dict("os.environ", {"AUDIT_LOG_RETAIN_DAYS": "0"}):
        settings = Settings()
        assert settings.audit_log_retain_days == 0


def test_audit_log_retain_days_custom():
    """可通过环境变量覆盖。"""
    with patch.dict("os.environ", {"AUDIT_LOG_RETAIN_DAYS": "7"}):
        settings = Settings()
        assert settings.audit_log_retain_days == 7


def test_audit_log_retain_days_negative_invalid():
    """负数配置应校验失败。"""
    with patch.dict("os.environ", {"AUDIT_LOG_RETAIN_DAYS": "-1"}):
        with pytest.raises(Exception):
            Settings()
