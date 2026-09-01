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


def _build_wave_response(parsed: dict[str, Any], ocr_used: bool, preview: str | None) -> ExtractWavePdfResponse:
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


def extract_wave_file(content: bytes, file_name: str = "upload") -> ExtractWavePdfResponse:
    """按扩展名分发提取 13 个故障字段：pdf→文本/OCR；txt/csv→表头+首个数据行；xlsx→首个工作表；
    json→对象/数组首元素。统一经 canonicalize_fault_fields 归一化后返回，不回写数据库。"""
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    if ext == "pdf":
        parsed, ocr_used, preview = _extract_from_bytes(content)
        return _build_wave_response(parsed, ocr_used, preview)

    if ext in {"txt", "csv", "json", "xlsx"}:
        import json as _json

        from ..services.fault_diagnosis_core import (
            _first_tabular_row,
            _read_csv_rows,
            _read_xlsx_first_row,
        )

        if ext == "json":
            try:
                parsed = _json.loads(content.decode("utf-8-sig"))
            except Exception as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"JSON 解析失败：{exc}") from exc
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON 顶层应为对象或数组")
            return _build_wave_response(parsed, False, str(parsed)[:200])

        fd, tmp_path = tempfile.mkstemp(suffix=f".{ext}")
        os.close(fd)
        try:
            Path(tmp_path).write_bytes(content)
            if ext == "xlsx":
                try:
                    row = _read_xlsx_first_row(Path(tmp_path))
                except Exception as exc:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"XLSX 解析失败：{exc}") from exc
            else:
                rows = _read_csv_rows(Path(tmp_path))
                try:
                    row = _first_tabular_row(rows)
                except Exception as exc:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"未在文件中找到有效数据行：{exc}") from exc
            return _build_wave_response(row, False, str(row)[:200])
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="暂不支持该格式，录波数据支持 pdf/txt/csv/json/xlsx",
    )
