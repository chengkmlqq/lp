"""Test debug mode configuration and exception handling."""
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.core.exception_handlers import global_exception_handler


def test_debug_mode_default_enabled():
    """Test that debug_mode defaults to True."""
    settings = Settings()
    assert settings.debug_mode is True


def test_debug_mode_can_be_disabled():
    """Test that debug_mode can be disabled via environment."""
    with patch.dict("os.environ", {"DEBUG_MODE": "false"}):
        settings = Settings()
        assert settings.debug_mode is False


async def test_exception_handler_with_debug_enabled():
    """Test exception handler includes stacktrace when debug is enabled."""
    with patch("app.core.exception_handlers.get_settings") as mock_settings:
        mock_settings.return_value.debug_mode = True

        request = None
        exc = ValueError("Test error")

        response = await global_exception_handler(request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

        content = response.body.decode()
        assert "Test error" in content
        assert "ValueError" in content
        assert "stacktrace" in content


async def test_exception_handler_with_debug_disabled():
    """Test exception handler excludes stacktrace when debug is disabled."""
    with patch("app.core.exception_handlers.get_settings") as mock_settings:
        mock_settings.return_value.debug_mode = False

        request = None
        exc = ValueError("Test error")

        response = await global_exception_handler(request, exc)

        assert isinstance(response, JSONResponse)
        assert response.status_code == 500

        content = response.body.decode()
        assert "Test error" in content
        assert "ValueError" in content
        assert "stacktrace" not in content
