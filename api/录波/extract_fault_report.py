"""
Extract fault information from scanned fault-analysis PDF reports.

Usage:
    python extract_fault_report.py document1.pdf
    python extract_fault_report.py document1.pdf -o fault_info.xlsx --dump-text ocr_text.txt
    python extract_fault_report.py document1.pdf --input-text ocr_text.txt -o fault_info.xlsx

Notes:
    This report type is often a scanned/image PDF. The script first tries the
    PDF text layer, then falls back to OCR. For Chinese OCR, PaddleOCR is
    recommended. Tesseract can also work if Chinese language data is installed.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Iterable


FIELDS = [
    "录波记录厂站",
    "故障时刻",
    "故障线路名称",
    "故障相",
    "故障持续时间(ms)",
    "重合闸情况",
    "故障相电压",
    "故障相电流",
    "最大零序电流(A)",
    "零序补偿系数K",
    "线路总长度L(km)",
    "线路正序灵敏角(°)",
    "线路正序阻抗定值(Ω)",
]


LABEL_ALIASES = {
    "录波记录厂站": [r"录波记录厂站", r"录波.*?厂站"],
    "故障时刻": [r"故障时刻", r"故障时间"],
    "故障线路名称": [r"故障线路名称", r"故障线路"],
    "故障相": [r"故障相"],
    "故障持续时间(ms)": [r"故障持续时间\s*\(?ms\)?", r"持续时间\s*\(?ms\)?"],
    "重合闸情况": [r"重合闸情况", r"重合闸"],
    "故障相电压": [r"故障相电压\s*\(?[kKVV]*\)?", r"故障.*?电压"],
    "故障相电流": [r"故障相电流\s*\(?[kK]?A\)?", r"故障.*?电流"],
    "最大零序电流(A)": [r"最大零序电流\s*\(?A\)?", r"零序电流"],
    "零序补偿系数K": [r"零序补偿系数\s*K", r"补偿系数\s*K"],
    "线路总长度L(km)": [r"线路总长度\s*L\s*\(?km\)?", r"线路总长度"],
    "线路正序灵敏角(°)": [r"线路正序灵敏角\s*°?", r"正序灵敏角"],
    "线路正序阻抗定值(Ω)": [r"线路正序阻抗定值\s*\(?Ω\)?", r"正序阻抗定值"],
}


def normalize_text(text: str) -> str:
    replacements = {
        "（": "(",
        "）": ")",
        "，": ",",
        "：": ":",
        "；": ";",
        "／": "/",
        "．": ".",
        "。": ".",
        "一": "-",
        "Ω": "Ω",
        "\u3000": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact_text(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(?<=\d)[-－](?=\d{2}[-－]\d{2})", "-", text)
    text = text.replace("－", "-")
    return text


def extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pymupdf as fitz  # type: ignore

        with fitz.open(str(pdf_path)) as doc:
            text = normalize_text("\n".join(page.get_text("text") for page in doc))
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if len(chinese_chars) >= 20:
            return text
        return ""
    except ImportError:
        return ""


def render_pdf_to_images(pdf_path: Path, dpi: int) -> list[Path]:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("未安装 PyMuPDF，无法读取 PDF。") from exc

    tmpdir = Path(tempfile.mkdtemp(prefix="fault_pdf_pages_"))
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    image_paths: list[Path] = []
    with fitz.open(str(pdf_path)) as doc:
        for page_no, page in enumerate(doc, start=1):
            image_path = tmpdir / f"page-{page_no}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(str(image_path))
            image_paths.append(image_path)
    return image_paths


def ocr_with_rapid(images: Iterable[Path]) -> str:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    ocr = RapidOCR()
    image_list = list(images)
    lines: list[str] = []
    for page_no, image in enumerate(image_list, start=1):
        print(f"OCR page {page_no}/{len(image_list)}: {image.name}", flush=True)
        lines.append(f"--- PAGE {page_no} ---")
        result, _ = ocr(str(image))
        if result:
            lines.extend(str(item[1]) for item in result if len(item) >= 2)
        lines.append("")
    return normalize_text("\n".join(lines))


def ocr_with_paddle(images: Iterable[Path]) -> str:
    os.environ.setdefault("FLAGS_use_onednn", "0")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    from paddleocr import PaddleOCR  # type: ignore

    try:
        ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            lang="ch",
        )
    except TypeError:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
    image_list = list(images)
    lines: list[str] = []
    for page_no, image in enumerate(image_list, start=1):
        print(f"OCR page {page_no}/{len(image_list)}: {image.name}", flush=True)
        lines.append(f"--- PAGE {page_no} ---")
        try:
            result = ocr.ocr(str(image), cls=True)
        except TypeError:
            result = ocr.predict(str(image))
        lines.extend(paddle_result_to_lines(result))
        lines.append("")
    return normalize_text("\n".join(lines))


def paddle_result_to_lines(result: object) -> list[str]:
    lines: list[str] = []
    if not result:
        return lines
    if isinstance(result, list):
        for page_result in result:
            if isinstance(page_result, dict):
                rec_texts = page_result.get("rec_texts") or page_result.get("text")
                if isinstance(rec_texts, list):
                    lines.extend(str(item) for item in rec_texts)
                    continue
            if isinstance(page_result, list):
                for item in page_result:
                    if isinstance(item, dict):
                        text = item.get("text") or item.get("rec_text")
                        if text:
                            lines.append(str(text))
                    elif isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]:
                        if isinstance(item[1], (list, tuple)):
                            lines.append(str(item[1][0]))
                        else:
                            lines.append(str(item[1]))
    return lines


def ocr_with_tesseract(images: Iterable[Path], lang: str) -> str:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    lines: list[str] = []
    for image in images:
        with Image.open(image) as im:
            text = pytesseract.image_to_string(im, lang=lang, config="--psm 6")
        lines.append(text)
    return normalize_text("\n".join(lines))


def parse_pages_spec(spec: str | None, total: int) -> set[int]:
    if not spec:
        return set(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return {page for page in pages if 1 <= page <= total}


def ocr_pdf(pdf_path: Path, engine: str, dpi: int, tesseract_lang: str, pages: str | None) -> str:
    all_images = render_pdf_to_images(pdf_path, dpi=dpi)
    temp_dir = all_images[0].parent if all_images else None
    try:
        selected_pages = parse_pages_spec(pages, total=len(all_images))
        images = [image for idx, image in enumerate(all_images, start=1) if idx in selected_pages]
        if not images:
            raise RuntimeError(f"页码范围无效: {pages}")
        if engine in {"auto", "rapid"}:
            try:
                return ocr_with_rapid(images)
            except ImportError:
                if engine == "rapid":
                    raise RuntimeError("未安装 RapidOCR。建议执行: pip install rapidocr_onnxruntime")
            except Exception as exc:
                if engine == "rapid":
                    raise RuntimeError(f"RapidOCR 识别失败: {exc}") from exc

        if engine in {"auto", "paddle"}:
            try:
                return ocr_with_paddle(images)
            except ImportError:
                if engine == "paddle":
                    raise RuntimeError("未安装 paddleocr。建议执行: pip install paddleocr")
            except Exception as exc:
                if engine == "paddle":
                    raise RuntimeError(f"PaddleOCR 识别失败: {exc}") from exc

        if engine in {"auto", "tesseract"}:
            try:
                return ocr_with_tesseract(images, lang=tesseract_lang)
            except ImportError:
                if engine == "tesseract":
                    raise RuntimeError("未安装 pytesseract/Pillow。建议执行: pip install pytesseract pillow")
            except Exception as exc:
                if engine == "tesseract":
                    raise RuntimeError(f"Tesseract 识别失败: {exc}") from exc

        raise RuntimeError(
            "PDF 文本层不可用，且未找到可用 OCR。推荐安装 RapidOCR: pip install rapidocr_onnxruntime"
        )
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def label_pattern(label: str) -> str:
    aliases = LABEL_ALIASES.get(label, [re.escape(label)])
    return r"(?:%s)" % "|".join(aliases)


def value_after_label(text: str, label: str, next_labels: list[str]) -> str:
    current = label_pattern(label)
    next_pattern = "|".join(label_pattern(item) for item in next_labels if item != label)
    if not next_pattern:
        return ""
    pattern = re.compile(current + r"\s*[:：]?\s*(.*?)\s*(?=" + next_pattern + r"|$)", re.S)
    match = pattern.search(text)
    if not match:
        return ""
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :：,，;；")
    return value


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.S)
    return match.group(1).strip() if match else ""


def text_lines(raw_text: str) -> list[str]:
    return [line.strip() for line in normalize_text(raw_text).splitlines() if line.strip()]


def next_line_value(lines: list[str], labels: Iterable[str], offset: int = 1) -> str:
    label_set = set(labels)
    for idx, line in enumerate(lines):
        if line in label_set and idx + offset < len(lines):
            return lines[idx + offset].strip()
    return ""


def next_numeric_value(lines: list[str], label: str) -> str:
    for idx, line in enumerate(lines):
        if line == label:
            for candidate in lines[idx + 1 : idx + 5]:
                candidate = re.sub(r"(?<=\d)\s*[.．]\s*(?=\d)", ".", candidate)
                if re.fullmatch(r"\d+(?:\.\d+)?(?:ms|kA|A|V|Ω)?", candidate, re.I):
                    return candidate
    return ""


def next_numeric_value_with_unit(lines: list[str], label: str) -> str:
    for idx, line in enumerate(lines):
        if line != label:
            continue
        value = ""
        unit = ""
        for candidate in lines[idx + 1 : idx + 6]:
            candidate = re.sub(r"(?<=\d)\s*[.．]\s*(?=\d)", ".", candidate)
            combined = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|kV|kA|A|V|Ω|km)?", candidate, re.I)
            if combined and not value:
                value = combined.group(1)
                unit = normalize_unit(combined.group(2) or "")
                if unit:
                    break
                continue
            if value and re.fullmatch(r"ms|kV|kA|A|V|Ω|km", candidate, re.I):
                unit = normalize_unit(candidate)
                break
            if value and re.fullmatch(r"\d+", candidate):
                break
        if value:
            return append_unit(value, unit)
    return ""


def next_numeric_value_any(lines: list[str], labels: Iterable[str]) -> str:
    for label in labels:
        value = next_numeric_value(lines, label)
        if value:
            return re.sub(r"(ms|kA|A|V|Ω|km|o|O)$", "", value, flags=re.I)
    return ""


def repeated_param_values(lines: list[str], label: str) -> list[str]:
    values: list[str] = []
    for idx, line in enumerate(lines):
        if line == label and idx + 1 < len(lines):
            values.append(lines[idx + 1].strip())
    return values


def same_line_value(lines: list[str], labels: Iterable[str]) -> str:
    ordered_labels = sorted(labels, key=len, reverse=True)
    for line in lines:
        for label in ordered_labels:
            if line == label:
                continue
            if line.startswith(label):
                raw_value = line[len(label) :]
                if raw_value and (raw_value[0].isspace() or raw_value[0] in ":："):
                    return raw_value.strip(" :：,，;；")
    return ""


def multiline_value_after_label(
    lines: list[str],
    labels: Iterable[str],
    stop_labels: Iterable[str] = (),
    max_lines: int = 5,
) -> str:
    label_set = set(labels)
    stop_set = set(stop_labels)
    for idx, line in enumerate(lines):
        if line not in label_set:
            continue
        parts: list[str] = []
        for candidate in lines[idx + 1 : idx + 1 + max_lines]:
            if candidate in stop_set or re.fullmatch(r"\d+", candidate):
                break
            parts.append(candidate)
        return "".join(parts).strip()
    return ""


def normalize_fault_time(value: str) -> str:
    value = value.strip()
    return re.sub(r"(?<=\d{2}:\d{2}:\d{2}):(?=\d{1,6}\b)", ".", value, count=1)


def extract_line_name(value: str) -> str:
    value = clean_value(value)
    match = re.search(r"(\d{2,4}kV[\u4e00-\u9fffA-Za-z0-9#()（）_-]*?线)", value)
    if match:
        return match.group(1)
    value = re.sub(r"(?:\d{3,5})?(?:电流|电压|断路器|开关)$", "", value).strip()
    return value


def parse_measurement(text: str, phase: str, kind: str) -> tuple[str, str]:
    pattern = rf"{phase}\s*相\s*故障\s*{kind}\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(kV|kA|V|A)?"
    match = re.search(pattern, text, re.I)
    if not match:
        return "", ""
    return match.group(1), normalize_unit(match.group(2) or "")


def parse_measurement_lines(lines: list[str], phase: str, kind: str) -> tuple[str, str]:
    label_pattern_text = rf"{phase}\s*相\s*故障\s*{kind}"
    for idx, line in enumerate(lines):
        if not re.fullmatch(label_pattern_text, line):
            continue
        value = ""
        unit = ""
        for candidate in lines[idx + 1 : idx + 5]:
            if not value and re.fullmatch(r"\d+(?:\.\d+)?", candidate):
                value = candidate
                continue
            if value and re.fullmatch(r"kV|kA|V|A", candidate, re.I):
                unit = normalize_unit(candidate)
                break
            if value and re.fullmatch(r"\d+", candidate):
                break
        if value:
            return value, unit
    return "", ""


def parse_setting_row(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        match = re.search(rf"{label}\s*[:：]?\s*(\d+(?:\.\d+)?)", text, re.I)
        if match:
            return match.group(1)
    return ""


def parse_line_report_text(raw_text: str) -> dict[str, str]:
    text = normalize_text(raw_text)
    lines = text_lines(text)
    data: dict[str, str] = {}

    station = (
        same_line_value(lines, ["厂站名称", "录波记录厂站"])
        or multiline_value_after_label(
            lines,
            ["厂站名称", "录波记录厂站"],
            stop_labels=["生产厂家", "录波器名称", "装置型号"],
        )
        or next_line_value(lines, ["厂站名称", "录波记录厂站"])
    )
    if station:
        data["录波记录厂站"] = station

    time_match = re.search(
        r"((?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,2}[:.]\d{1,6})\s+(\d+(?:\.\d+)?)\s*ms",
        text,
    )
    if time_match:
        data["故障时刻"] = normalize_fault_time(time_match.group(1))
        data["故障持续时间(ms)"] = time_match.group(2)

    device_or_line = same_line_value(lines, ["故障设备名称", "一次设备名称", "故障线路名称"]) or next_line_value(
        lines, ["故障设备名称", "一次设备名称", "故障线路名称"]
    )
    if device_or_line:
        data["故障线路名称"] = extract_line_name(device_or_line)

    phase = same_line_value(lines, ["故障相别", "故障相"]) or next_line_value(lines, ["故障相别", "故障相"])
    phase_match = re.search(r"\b(ABC|ABN|BCN|ACN|AB|BC|AC|AN|BN|CN|A|B|C)\b", phase.upper())
    if phase_match:
        data["故障相"] = phase_match.group(1)

    phase_letters = [item for item in "ABC" if item in data.get("故障相", "").upper()]
    voltage_by_phase: dict[str, tuple[str, str]] = {}
    current_by_phase: dict[str, tuple[str, str]] = {}
    for item in "ABC":
        voltage = parse_measurement(text, item, "电压")
        if not voltage[0]:
            voltage = parse_measurement_lines(lines, item, "电压")
        current = parse_measurement(text, item, "电流")
        if not current[0]:
            current = parse_measurement_lines(lines, item, "电流")
        voltage_by_phase[item] = voltage
        current_by_phase[item] = current

    if phase_letters:
        voltage_values = [voltage_by_phase[item][0] for item in phase_letters if voltage_by_phase[item][0]]
        current_values = [current_by_phase[item][0] for item in phase_letters if current_by_phase[item][0]]
        voltage_unit = next((voltage_by_phase[item][1] for item in phase_letters if voltage_by_phase[item][1]), "")
        current_unit = next((current_by_phase[item][1] for item in phase_letters if current_by_phase[item][1]), "")
        if voltage_values:
            data["故障相电压"] = join_values_with_unit(voltage_values, voltage_unit)
        if current_values:
            data["故障相电流"] = join_values_with_unit(current_values, current_unit)

    settings = {
        "最大零序电流(A)": ["最大零序电流", "零序电流", "3I0"],
        "零序补偿系数K": ["零序电抗补偿系数", "零序补偿系数"],
        "线路总长度L(km)": ["线路总长度L", "线路总长度"],
        "线路正序灵敏角(°)": ["线路正序灵敏角"],
        "线路正序阻抗定值(Ω)": ["线路正序阻抗定值"],
    }
    for field, labels in settings.items():
        value = parse_setting_row(text, labels)
        if value:
            data[field] = value

    reclosing = infer_reclosing_status(text)
    if reclosing:
        data["重合闸情况"] = reclosing

    return data


def parse_fault_info(raw_text: str) -> dict[str, str]:
    text = normalize_text(raw_text)
    lines = text_lines(text)
    data = {field: "" for field in FIELDS}

    line_report_data = parse_line_report_text(text)
    for field, value in line_report_data.items():
        if value:
            data[field] = value

    unsafe_label_fields = {"重合闸情况", "故障相电压", "故障相电流"}
    for idx, field in enumerate(FIELDS):
        if data.get(field):
            continue
        if field in unsafe_label_fields:
            continue
        window = FIELDS[idx + 1 : idx + 6]
        data[field] = value_after_label(text, field, window)

    station = next_line_value(lines, ["厂站名称", "录波记录厂站"])
    if station and not data.get("录波记录厂站"):
        data["录波记录厂站"] = station

    device_or_line = next_line_value(lines, ["一次设备名称", "故障线路名称"])
    if device_or_line and not data.get("故障线路名称"):
        data["故障线路名称"] = device_or_line

    fault_date = next_line_value(lines, ["故障开始时间", "故障时刻"])
    if fault_date and not data.get("故障时刻"):
        maybe_time = next_line_value(lines, [fault_date])
        if re.fullmatch(r"\d{1,2}:\d{1,2}:\d{1,2}[:.]\d{1,6}", maybe_time):
            maybe_time = re.sub(r"(?<=\d{2}:\d{2}:\d{2}):", ".", maybe_time, count=1)
            data["故障时刻"] = f"{fault_date} {maybe_time}"
        else:
            data["故障时刻"] = fault_date

    duration = next_line_value(lines, ["故障持续时间"])
    if duration and not data.get("故障持续时间(ms)"):
        data["故障持续时间(ms)"] = re.sub(r"ms$", "", duration, flags=re.I)

    phase_values = repeated_param_values(lines, "故障相别")
    if phase_values and not data.get("故障相"):
        data["故障相"] = phase_values[0]

    phase = data["故障相"].strip().upper()
    voltage_by_phase = {
        "A": next_numeric_value_with_unit(lines, "UA"),
        "B": next_numeric_value_with_unit(lines, "UB"),
        "C": next_numeric_value_with_unit(lines, "UC"),
    }
    current_by_phase = {
        "A": next_numeric_value_with_unit(lines, "IA") or next_numeric_value_with_unit(lines, "A相差动电流"),
        "B": next_numeric_value_with_unit(lines, "IB") or next_numeric_value_with_unit(lines, "B相差动电流"),
        "C": next_numeric_value_with_unit(lines, "IC") or next_numeric_value_with_unit(lines, "C相差动电流"),
    }
    if phase in voltage_by_phase and voltage_by_phase[phase]:
        data["故障相电压"] = voltage_by_phase[phase]
    if phase in current_by_phase and current_by_phase[phase]:
        data["故障相电流"] = current_by_phase[phase]

    pdf2txt_data = parse_pdf2txt_compact(text)
    for field, value in pdf2txt_data.items():
        if value and not data.get(field):
            data[field] = value

    line_based_values = {
        "最大零序电流(A)": ["3I0", "3I0电流", "310", "3l0", "3IO", "零序电流"],
        "线路总长度L(km)": ["线路总长度", "线路总长度L"],
        "线路正序灵敏角(°)": ["线路正序灵敏角"],
        "线路正序阻抗定值(Ω)": ["线路正序阻抗定值"],
        "零序补偿系数K": ["零序电抗补偿系数", "零序补偿系数"],
    }
    for field, labels in line_based_values.items():
        value = next_numeric_value_any(lines, labels)
        if value and not data.get(field):
            data[field] = value

    reclosing = infer_reclosing_status(text)
    if reclosing:
        data["重合闸情况"] = reclosing

    compact = re.sub(r"\s+", "", text)

    # Pattern fallbacks are useful when OCR reads a table as rows instead of
    # "label: value" pairs.
    data["故障时刻"] = data["故障时刻"] or first_match(
        compact, r"((?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\d{1,2}:\d{1,2}:\d{1,2}(?:\.\d{1,6})?)"
    )
    data["录波记录厂站"] = data["录波记录厂站"] or first_match(
        compact, r"([\u4e00-\u9fff]{2,}(?:\d{3,4}kV)?[\u4e00-\u9fff]*变)"
    )
    data["故障线路名称"] = data["故障线路名称"] or first_match(
        compact, r"(\d{2,4}kV[\u4e00-\u9fffA-Za-z0-9#()（）-]{1,20}线)"
    )

    allowed_phase = r"(?:ABC|ABN|BCN|ACN|AB|BC|AC|AN|BN|CN|A|B|C)"
    data["故障相"] = data["故障相"] or first_match(compact, rf"故障相({allowed_phase})")

    numeric_fallbacks = {
        "故障持续时间(ms)": r"故障持续时间.*?(\d{1,6}(?:\.\d+)?)",
        "故障相电压": r"故障相电压.*?(\d+(?:\.\d+)?)",
        "故障相电流": r"故障相电流.*?(\d+(?:\.\d+)?)",
        "最大零序电流(A)": r"最大零序电流.*?(\d+(?:\.\d+)?)",
        "零序补偿系数K": r"零序补偿系数K?.*?(\d+(?:\.\d+)?)",
        "线路总长度L(km)": r"线路总长度L?.*?(\d+(?:\.\d+)?)",
        "线路正序灵敏角(°)": r"线路正序灵敏角.*?(\d+(?:\.\d+)?)",
        "线路正序阻抗定值(Ω)": r"线路正序阻抗定值.*?(\d+(?:\.\d+)?)",
    }
    for field, pattern in numeric_fallbacks.items():
        if not data[field]:
            data[field] = first_match(compact, pattern)

    return {field: clean_value(data[field]) for field in FIELDS}


def parse_pdf2txt_compact(text: str) -> dict[str, str]:
    token_data = parse_pdf2txt_tokens(text)
    if token_data:
        return token_data

    compact = compact_text(text)
    data: dict[str, str] = {}

    station = first_match(compact, r"录波分析报告((?:\d{2,4}kV)?[\u4e00-\u9fff]{1,20}站)")
    if station:
        data["录波记录厂站"] = station

    time_match = re.search(
        r"值((?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2})(\d{1,2})[.:：](\d{1,2})[.:：](\d{1,2})[.:：](\d{1,6})",
        compact,
    )
    if time_match:
        date, hour, minute, second, milli = time_match.groups()
        data["故障时刻"] = f"{date} {hour.zfill(2)}:{minute.zfill(2)}:{second.zfill(2)}.{milli}"

    duration = first_match(compact, r"值(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}.*?(\d+(?:\.\d+)?)ms")
    if duration:
        data["故障持续时间(ms)"] = duration

    fault_match = re.search(
        r"故障参数实际值((?:\d{2,4}kV)?[\u4e00-\u9fffA-Za-z0-9_-]{2,30}线)"
        r"([ABC]{1,3}N?)"
        r"(\d+(?:\.\d+)?)(\d+(?:\.\d+)?)(\d+(?:\.\d+)?)"
        r"(\d+(?:\.\d+)?)(\d+(?:\.\d+)?)(\d+(?:\.\d+)?)",
        compact,
    )
    if fault_match:
        line, phase, ua, ub, uc, ia, ib, ic = fault_match.groups()
        data["故障线路名称"] = line
        data["故障相"] = phase
        voltage_by_phase = {"A": ua, "B": ub, "C": uc}
        current_by_phase = {"A": ia, "B": ib, "C": ic}
        phase_letters = [item for item in "ABC" if item in phase]
        if phase_letters:
            data["故障相电压"] = "/".join(voltage_by_phase[item] for item in phase_letters)
            data["故障相电流"] = "/".join(current_by_phase[item] for item in phase_letters)

    reclosing = infer_reclosing_status(text)
    if reclosing:
        data["重合闸情况"] = reclosing

    return data


def infer_reclosing_status(text: str) -> str:
    normalized = normalize_text(text)
    compact = compact_text(normalized)
    event_section = compact
    start = compact.find("保护动作事件")
    if start >= 0:
        end_candidates = [
            pos
            for marker in ["故障前开关量", "保护定值信息"]
            for pos in [compact.find(marker, start + 1)]
            if pos > start
        ]
        end = min(end_candidates) if end_candidates else min(len(compact), start + 2000)
        event_section = compact[start:end]

    # OCR-style event table: require a time token immediately associated with
    # "重合闸动作", not just a setting/status name somewhere in the report.
    if re.search(r"\d+(?:\.\d+)?ms\s*重合闸动作\s*1", normalized):
        return "成功"
    if re.search(r"重合闸动作\s*1\s*\d+(?:\.\d+)?ms", normalized):
        return "成功"
    if "重合闸动作重合闸动作" in event_section:
        return "成功"
    if "开关重合闸动作" in event_section:
        last_close = event_section.rfind("开关合位")
        last_open = event_section.rfind("开关分位")
        if last_close > last_open >= 0:
            return "成功"

    return ""


def parse_pdf2txt_tokens(text: str) -> dict[str, str]:
    tokens = normalize_text(text).split()
    data: dict[str, str] = {}
    if not tokens:
        return data

    def find_sequence(sequence: list[str], start: int = 0) -> int:
        last = len(tokens) - len(sequence) + 1
        for idx in range(start, max(last, 0)):
            if tokens[idx : idx + len(sequence)] == sequence:
                return idx
        return -1

    def parse_number_at(idx: int) -> tuple[str, int]:
        if idx >= len(tokens):
            return "", idx
        token = normalize_number_token(tokens[idx])
        if token.endswith(".") and idx + 1 < len(tokens):
            right = normalize_number_token(tokens[idx + 1])
            if re.fullmatch(r"\d+", token[:-1]) and re.fullmatch(r"\d+", right):
                return f"{token[:-1]}.{right}", idx + 2
        if idx + 2 < len(tokens):
            left = normalize_number_token(tokens[idx])
            middle = normalize_number_token(tokens[idx + 1])
            right = normalize_number_token(tokens[idx + 2])
            right_match = re.fullmatch(r"(\d+)(ms|kV|km|A|V|Hz|S)?", right, re.I)
            if re.fullmatch(r"\d+", left) and tokens[idx + 1] == "&" and right_match:
                return f"{left}{middle}.{right_match.group(1)}", idx + 3
        if idx + 2 < len(tokens):
            left = normalize_number_token(tokens[idx])
            dot = tokens[idx + 1]
            right = normalize_number_token(tokens[idx + 2])
            if re.fullmatch(r"\d+", left) and dot in {".", ","} and re.fullmatch(r"\d+", right):
                return f"{left}.{right}", idx + 3
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|kV|km|A|V|Hz|S)?", token, re.I)
        if match:
            return match.group(1), idx + 1
        return "", idx

    report_idx = find_sequence(["录", "波", "分", "析", "报", "告"])
    if report_idx >= 0:
        idx = report_idx + 6
        if idx < len(tokens) and tokens[idx].upper() == "SIFANG":
            data["录波记录厂站"] = " ".join(tokens[idx + 1 : idx + 3]).strip()
            data["故障线路名称"] = " ".join(tokens[idx + 3 : idx + 5]).strip()
        else:
            station_parts: list[str] = []
            while idx < len(tokens):
                station_parts.append(tokens[idx])
                if tokens[idx] == "站":
                    break
                idx += 1
            station = "".join(station_parts)
            if station:
                data["录波记录厂站"] = station

    nature_idx = find_sequence(["故", "障", "性", "质"])
    if nature_idx >= 0:
        stop_sequences = [
            ["中", "元", "华", "电"],
            ["SIFANG"],
            ["值"],
        ]
        station_parts: list[str] = []
        idx = nature_idx + 4
        while idx < len(tokens):
            if any(tokens[idx : idx + len(seq)] == seq for seq in stop_sequences):
                break
            station_parts.append(tokens[idx])
            idx += 1
        station = "".join(station_parts).replace("(", "（").replace(")", "）")
        if "录波分析报告" in station:
            station = station.split("录波分析报告", 1)[1]
            station = station.split("站", 1)[0] + "站" if "站" in station else station
        if "站" in station and len(station) > 4:
            data["录波记录厂站"] = station

    value_idx = find_sequence(["值"])
    if value_idx >= 0:
        duration, _ = parse_number_at(value_idx + 1)
        duration_token = "".join(tokens[value_idx + 1 : value_idx + 4])
        if duration and re.search(r"ms", duration_token, re.I):
            data["故障持续时间(ms)"] = duration
    for idx in range(value_idx + 1 if value_idx >= 0 else 0, len(tokens) - 9):
        if re.fullmatch(r"(?:19|20)\d{2}", tokens[idx]) and tokens[idx + 1] == "-":
            if tokens[idx + 3] == "-":
                year, month, day = tokens[idx], tokens[idx + 2], tokens[idx + 4]
                hour = tokens[idx + 5]
                minute = tokens[idx + 7] if idx + 7 < len(tokens) else ""
                second = tokens[idx + 9] if idx + 9 < len(tokens) else ""
                milli = tokens[idx + 11] if idx + 11 < len(tokens) else ""
                if all(re.fullmatch(r"\d+", item or "") for item in [hour, minute, second, milli]):
                    data["故障时刻"] = (
                        f"{year}-{month.zfill(2)}-{day.zfill(2)} "
                        f"{hour.zfill(2)}:{minute.zfill(2)}:{second.zfill(2)}.{milli}"
                    )
                    first_duration_token = tokens[idx + 12] if idx + 12 < len(tokens) else ""
                    first_after_time, after_first = parse_number_at(idx + 12)
                    second_after_time, _ = parse_number_at(after_first)
                    if re.search(r"ms$", first_duration_token, re.I):
                        duration = first_after_time
                    elif second_after_time:
                        duration = second_after_time
                    else:
                        duration = first_after_time
                    if duration and not data.get("故障持续时间(ms)"):
                        data["故障持续时间(ms)"] = duration
                    break

    fault_idx = find_sequence(
        ["故", "障", "参", "数", "实", "际", "值"],
        start=report_idx if report_idx >= 0 else 0,
    )
    if fault_idx >= 0:
        idx = fault_idx + 7
        line_parts: list[str] = []
        while idx < len(tokens):
            token = tokens[idx].upper()
            if re.fullmatch(r"[ABC]{1,3}N?", token):
                break
            line_parts.append(tokens[idx])
            idx += 1
        if line_parts and not data.get("故障线路名称") and not re.fullmatch(r"[\d.]+", "".join(line_parts)):
            data["故障线路名称"] = "".join(line_parts).replace("-", "")
        if idx < len(tokens):
            phase = tokens[idx].upper()
            data["故障相"] = phase
            idx += 1
            values: list[str] = []
            for _ in range(15):
                value, next_idx = parse_number_at(idx)
                if not value:
                    break
                values.append(value)
                idx = next_idx
            if len(values) >= 6:
                ua, ub, uc, ia, ib, ic = values[:6]
                voltage_unit, current_unit = infer_fault_units(tokens, idx)
                voltage_by_phase = {"A": ua, "B": ub, "C": uc}
                current_by_phase = {"A": ia, "B": ib, "C": ic}
                phase_letters = [item for item in "ABC" if item in phase]
                if phase_letters:
                    data["故障相电压"] = join_values_with_unit(
                        [voltage_by_phase[item] for item in phase_letters], voltage_unit
                    )
                    data["故障相电流"] = join_values_with_unit(
                        [current_by_phase[item] for item in phase_letters], current_unit
                    )
    if not data.get("故障相") and "C" in tokens:
        data["故障相"] = "C"

    # CSC line-protection reports can lose the non-numeric phase cells in
    # PDF2TXT. In that case map the known numeric sequence after "实际值".
    if fault_idx >= 0:
        idx = fault_idx + 7
        first_values: list[str] = []
        while idx < len(tokens) and tokens[idx : idx + 5] != ["故", "障", "参", "数", "单"]:
            value, next_idx = parse_number_at(idx)
            if value:
                first_values.append(value)
                idx = next_idx
                continue
            idx += 1

        ic_idx = -1
        for pos in range(idx, min(idx + 40, len(tokens))):
            if tokens[pos].upper() == "IC":
                ic_idx = pos
                break
        tail_values: list[str] = []
        idx = ic_idx + 1 if ic_idx >= 0 else idx
        while idx < len(tokens) and len(tail_values) < 8:
            value, next_idx = parse_number_at(idx)
            if value:
                tail_values.append(value)
                idx = next_idx
                continue
            idx += 1
        phase = data.get("故障相", "").upper()
        if phase == "C" and len(first_values) >= 15:
            voltage_unit, current_unit = infer_fault_units(tokens, idx)
            if tail_values and tail_values[0] == "310":
                tail_values = tail_values[1:]
            data["故障相电压"] = append_unit(first_values[13], voltage_unit)
            data["故障相电流"] = append_unit(tail_values[1], current_unit) if len(tail_values) > 1 else ""
            data["最大零序电流(A)"] = tail_values[2] if len(tail_values) > 2 else ""

    setting_sequences = {
        "线路正序阻抗定值(Ω)": ["线", "路", "正", "序", "阻", "抗", "定", "值"],
        "线路正序灵敏角(°)": ["线", "路", "正", "序", "灵", "敏", "角"],
        "线路总长度L(km)": ["线", "路", "总", "长", "度"],
        "零序补偿系数K": ["零", "序", "电", "抗", "补", "偿", "系", "数"],
    }
    for field, sequence in setting_sequences.items():
        pos = find_sequence(sequence)
        if pos >= 0:
            idx = pos + len(sequence)
            first_value = ""
            first_next = idx
            while first_next < len(tokens):
                first_value, first_next = parse_number_at(first_next)
                if first_value:
                    break
                first_next += 1
            second_value = ""
            second_next = first_next
            while second_next < len(tokens):
                second_value, second_next = parse_number_at(second_next)
                if second_value:
                    break
                second_next += 1
            if first_value:
                if "." not in first_value and second_value:
                    data[field] = second_value
                else:
                    data[field] = first_value

    return data


def infer_fault_units(tokens: list[str], start: int) -> tuple[str, str]:
    unit_idx = -1
    for idx in range(start, min(start + 80, len(tokens) - 5)):
        if tokens[idx : idx + 5] == ["故", "障", "参", "数", "单"]:
            unit_idx = idx
            break
    if unit_idx < 0:
        return "V", "A"
    units = [token for token in tokens[unit_idx + 6 : unit_idx + 20] if re.fullmatch(r"kV|kA|V|A", token, re.I)]
    voltage_unit = next((unit for unit in units if unit.lower().endswith("v")), "V")
    current_unit = next((unit for unit in units if unit.lower().endswith("a")), "")
    if not current_unit:
        current_unit = "kA" if voltage_unit.lower() == "kv" else "A"
    return normalize_unit(voltage_unit), normalize_unit(current_unit)


def normalize_unit(unit: str) -> str:
    if unit.lower() == "kv":
        return "kV"
    if unit.lower() == "ka":
        return "kA"
    return unit.upper()


def append_unit(value: str, unit: str) -> str:
    return f"{value} {unit}" if value and unit else value


def join_values_with_unit(values: list[str], unit: str) -> str:
    return append_unit("/".join(values), unit)


def normalize_number_token(token: str) -> str:
    token = token.strip()
    if token in {"l", "I"}:
        return "1"
    if token == "&":
        return "8"
    token = token.replace("l.", "1.").replace("I.", "1.")
    token = token.replace("&", "8")
    token = token.replace("，", ".").replace(",", ".")
    return token


def clean_value(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"^[：:;,，\s]+|[：:;,，\s]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def write_output(data: dict[str, str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() in {".xlsx", ".xls"}:
        from openpyxl import Workbook  # type: ignore
        from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore
        from openpyxl.utils import get_column_letter  # type: ignore

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "故障信息"
        sheet.append(FIELDS)
        sheet.append([data.get(field, "") for field in FIELDS])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for index, field in enumerate(FIELDS, start=1):
            value = str(data.get(field, ""))
            width = min(max(len(field) * 2, len(value) + 2, 14), 34)
            sheet.column_dimensions[get_column_letter(index)].width = width
        workbook.save(output)
    else:
        with output.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(data)


def validate_output(data: dict[str, str], output: Path, text: str) -> list[str]:
    issues: list[str] = []
    if not output.exists():
        issues.append(f"输出文件不存在: {output}")
    elif output.stat().st_size <= 0:
        issues.append(f"输出文件为空: {output}")

    required_fields = [
        "故障时刻",
        "故障相",
        "故障持续时间(ms)",
        "故障相电压",
        "故障相电流",
    ]
    missing_required = [field for field in required_fields if not data.get(field)]
    if missing_required:
        issues.append("关键字段为空: " + ", ".join(missing_required))

    station = data.get("录波记录厂站", "")
    line = data.get("故障线路名称", "")
    if len(station) > 80:
        issues.append("录波记录厂站字段异常过长，可能发生串表")
    if len(line) > 80 or "故障参数" in line or "保护动作" in line:
        issues.append("故障线路名称字段异常，可能发生串表")

    duration = data.get("故障持续时间(ms)", "")
    if duration and not re.fullmatch(r"\d+(?:\.\d+)?", duration):
        issues.append("故障持续时间不是纯数值")

    for field in ["故障相电压", "故障相电流"]:
        value = data.get(field, "")
        if value in {"0", "00", "0/0", "00/00"}:
            issues.append(f"{field}疑似误提取为全零")
        if value and not re.fullmatch(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)*(?:\s*(?:kV|kA|V|A))?", value):
            issues.append(f"{field}格式异常: {value}")

    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_count < 20:
        issues.append("OCR/文本内容过少，可能没有成功识别 PDF")

    return issues


def write_validation_log(log_path: Path, data: dict[str, str], issues: list[str]) -> None:
    lines = ["fault report extraction validation", ""]
    if issues:
        lines.append("STATUS: FAILED")
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("STATUS: OK")
    lines.append("")
    lines.append("FIELDS:")
    lines.extend(f"{field}: {data.get(field, '')}" for field in FIELDS)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    no_args = len(sys.argv) == 1
    parser = argparse.ArgumentParser(description="提取故障分析报告 PDF 中的故障信息。")
    parser.add_argument("pdf", nargs="?", type=Path, default=Path("document1.pdf"), help="输入 PDF 文件路径")
    parser.add_argument("-o", "--output", type=Path, default=Path("fault_info.xlsx"), help="输出 CSV/XLSX")
    parser.add_argument("--engine", choices=["auto", "rapid", "paddle", "tesseract", "text"], default="auto")
    parser.add_argument("--dpi", type=int, default=150, help="OCR 前 PDF 渲染分辨率")
    parser.add_argument("--pages", help="只 OCR 指定页码，如 1 或 1-2 或 1,3")
    parser.add_argument("--tesseract-lang", default="chi_sim+eng", help="Tesseract OCR 语言")
    parser.add_argument("--dump-text", type=Path, help="保存抽取/OCR 原文，便于调试")
    parser.add_argument("--input-text", type=Path, help="直接解析已有 OCR 文本，不重新 OCR")
    parser.add_argument("--validate-log", type=Path, help="保存校验日志")
    args = parser.parse_args()
    if no_args and not args.dump_text:
        args.dump_text = Path("ocr_text.txt")

    if not args.pdf.exists():
        raise FileNotFoundError(f"PDF 不存在: {args.pdf}")

    if args.input_text:
        text = args.input_text.read_text(encoding="utf-8")
    else:
        text = extract_pdf_text(args.pdf)
    if not text and args.engine != "text":
        text = ocr_pdf(
            args.pdf,
            engine=args.engine,
            dpi=args.dpi,
            tesseract_lang=args.tesseract_lang,
            pages=args.pages,
        )
    if not text:
        raise RuntimeError("未能从 PDF 提取到有效文本。该文件可能需要 OCR。")

    if args.dump_text:
        args.dump_text.write_text(text, encoding="utf-8")

    data = parse_fault_info(text)
    write_output(data, args.output)
    issues = validate_output(data, args.output, text)
    if args.validate_log:
        write_validation_log(args.validate_log, data, issues)

    print(f"已写出: {args.output}")
    for field in FIELDS:
        print(f"{field}: {data[field]}")
    if issues:
        print("校验失败:")
        for issue in issues:
            print(f"- {issue}")
        return 2
    if args.validate_log:
        print(f"校验通过: {args.validate_log}")
    else:
        print("校验通过")
    return 0


if __name__ == "__main__":
    should_pause = len(sys.argv) == 1
    try:
        exit_code = main()
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        exit_code = 1
    if should_pause:
        input("按回车键退出...")
    raise SystemExit(exit_code)
