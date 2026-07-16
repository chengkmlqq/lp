from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services import legacy_atp_adapter


def test_resolve_legacy_atp_job_rejects_paths_outside_allowed_root(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "wine_allowed_root", str(tmp_path / "wine-root"))
    monkeypatch.setattr(settings, "atp_legacy_root", str(tmp_path / "outside" / "ATP"))
    monkeypatch.setattr(settings, "atp_template_root", str(tmp_path / "outside" / "ATP" / "templates"))
    monkeypatch.setattr(settings, "atp_run_root", str(tmp_path / "wine-root" / "runs"))

    with pytest.raises(RuntimeError, match="legacy_root必须位于"):
        legacy_atp_adapter.resolve_legacy_atp_job(adapter_config_json={}, execution_options={})


def test_resolve_legacy_atp_job_reports_missing_egm_directory(monkeypatch, tmp_path: Path) -> None:
    allowed_root = tmp_path / "wine-root"
    template_root = allowed_root / "ATP" / "templates"
    template_dir = template_root / "raoji1"
    template_dir.mkdir(parents=True)
    (template_dir / "sample.atp").write_text("0123456789" * 200, encoding="utf-8")
    (allowed_root / "ATP" / "rjtzl.exe").write_text("binary", encoding="utf-8")
    (allowed_root / "ATP" / "tpbig.exe").write_text("binary", encoding="utf-8")

    settings = get_settings()
    monkeypatch.setattr(settings, "wine_allowed_root", str(allowed_root))
    monkeypatch.setattr(settings, "atp_legacy_root", str(allowed_root / "ATP"))
    monkeypatch.setattr(settings, "atp_template_root", str(template_root))
    monkeypatch.setattr(settings, "atp_run_root", str(allowed_root / "runs"))
    monkeypatch.setattr(settings, "atp_rjtzl_executable", "ATP/rjtzl.exe")
    monkeypatch.setattr(settings, "atp_tpbig_executable", "ATP/tpbig.exe")

    with pytest.raises(RuntimeError, match="EGM子目录不存在"):
        legacy_atp_adapter.resolve_legacy_atp_job(
            adapter_config_json={
                "calculation_mode": "raoji1",
                "template_subdir": "raoji1",
                "use_egm": True,
            },
            execution_options={},
        )


def test_build_legacy_atp_status_checks_marks_missing_binaries(monkeypatch, tmp_path: Path) -> None:
    allowed_root = tmp_path / "wine-root"
    template_root = allowed_root / "ATP" / "templates"
    template_root.mkdir(parents=True)
    (template_root / "EGM").mkdir(parents=True)

    settings = get_settings()
    monkeypatch.setattr(settings, "wine_allowed_root", str(allowed_root))
    monkeypatch.setattr(settings, "wine_binary_path", "wine")
    monkeypatch.setattr(settings, "atp_legacy_root", str(allowed_root / "ATP"))
    monkeypatch.setattr(settings, "atp_template_root", str(template_root))
    monkeypatch.setattr(settings, "atp_run_root", str(allowed_root / "runs"))
    monkeypatch.setattr(settings, "atp_tpbig_executable", "ATP/tpbig.exe")
    monkeypatch.setattr(settings, "atp_rjtzl_executable", "ATP/rjtzl.exe")
    monkeypatch.setattr(legacy_atp_adapter, "_resolve_binary", lambda _raw: None)

    checks = legacy_atp_adapter.build_legacy_atp_status_checks()

    assert checks["wine"]["available"] is False
    assert checks["tpbig_executable"]["available"] is False
    assert checks["rjtzl_executable"]["available"] is False
    assert checks["egm_subdir"]["available"] is True
