"""Tests for traveling wave environment detection (LP-334)."""
import sys
import types
from unittest.mock import patch

from app.schemas.traveling_wave import TravelingWaveStatusResponse
from app.services.traveling_wave_service import check_environment


def _fake_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__name__ = name
    return module


def test_check_environment_healthy_has_empty_missing_components():
    """Healthy environment returns no missing components and no error."""
    modules = {"numpy": _fake_module("numpy"), "scipy": _fake_module("scipy"), "matplotlib": _fake_module("matplotlib")}
    with patch.dict(sys.modules, modules, clear=False):
        result = check_environment()
    assert isinstance(result, TravelingWaveStatusResponse)
    assert result.python_available is True
    assert result.numpy_available is True
    assert result.scipy_available is True
    assert result.matplotlib_available is True
    assert result.missing_components == []
    assert result.error is None


def test_check_environment_reports_missing_components():
    """Missing numpy/scipy/matplotlib are listed as structured components."""
    with patch.dict(sys.modules, {"numpy": None, "scipy": None, "matplotlib": None}, clear=False):
        result = check_environment()

    assert result.python_available is True
    assert result.numpy_available is False
    assert result.scipy_available is False
    assert result.matplotlib_available is False
    assert set(result.missing_components) == {"numpy", "scipy", "matplotlib"}
    assert result.error is not None
    assert "numpy" in result.error


def test_status_response_defaults_missing_components_empty():
    """Backward-compatible default: missing_components is an empty list."""
    response = TravelingWaveStatusResponse()
    assert response.missing_components == []
