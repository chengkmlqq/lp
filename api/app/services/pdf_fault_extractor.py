from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel

from ..services.fault_diagnosis_core import canonicalize_fault_fields
from ..core.config import get_settings


class ExtractWavePdfResponse(BaseModel):
    ok: bool
    extracted: dict[str, Any]
    missing: list[str]
    ocr_used: bool
    raw_text_preview: str | None = None


_EXTRACTOR_PATH = Path(__file__).resolve().parents[2] / "录波" / "extract_fault_report.py"


_WAVE_FIELD_KEYS = [
    "station",
    "fault_time",
    "line_name",
    "fault_phase",
    "duration_ms",
    "reclosing",
    "phase_voltage",
    "phase_current",
    "zero_sequence_current",
    "zero_sequence_compensation_k",
    "line_length_km",
    "sensitive_angle_deg",
    "positive_sequence_impedance_ohm",
]


def _extract_from_bytes(content: bytes) -> tuple[dict[str, Any], bool, str | None]:
    if _EXTRACTOR_PATH.exists() is False:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="录波 PDF 提取器不存在，请联系管理员",
        )

    import importlib.util

    spec = importlib.util.spec_from_file_location("fault_report_extractor", str(_EXTRACTOR_PATH))
    if spec is None or spec.loader is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="加载录波 PDF 提取器失败，请联系管理员",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tmp_pdf: str | None = None
    try:
        fd, tmp_pdf = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        Path(tmp_pdf).write_bytes(content)

        text = module.extract_pdf_text(Path(tmp_pdf))
        ocr_used = False
        if not text:
            text = module.ocr_pdf(
                Path(tmp_pdf),
                engine="auto",
                dpi=150,
                tesseract_lang="chi_sim+eng",
                pages=None,
            )
            ocr_used = True

        if not text:
            return {}, False, None

        preview = text[:200]
        parsed = dict(module.parse_fault_info(text))
        return parsed, ocr_used, preview
    finally:
        if tmp_pdf:
            try:
                Path(tmp_pdf).unlink(missing_ok=True)
            except Exception:
                pass


def extract_wave_pdf(content: bytes, file_name: str = "upload.pdf") -> ExtractWavePdfResponse:
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    parsed, ocr_used, preview = _extract_from_bytes(content)
    canonical = canonicalize_fault_fields(parsed)

    extracted: dict[str, Any] = {key: canonical.get(key) for key in _WAVE_FIELD_KEYS}
    missing = [key for key in _WAVE_FIELD_KEYS if not extracted.get(key)]

    return ExtractWavePdfResponse(
        ok=len(missing) == 0,
        extracted=extracted,
        missing=missing,
        ocr_used=ocr_used,
        raw_text_preview=preview,
    )
