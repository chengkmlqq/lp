from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

CATEGORY_WAVE = "wave"
CATEGORY_LIGHTNING = "lightning"
CATEGORY_LEDGER = "ledger"
CATEGORY_TRAVELING_WAVE = "traveling_wave"

CATEGORY_FIELDS: dict[str, str] = {
    CATEGORY_WAVE: "wave_data_file",
    CATEGORY_LIGHTNING: "lightning_data_file",
    CATEGORY_LEDGER: "ledger_data_file",
    CATEGORY_TRAVELING_WAVE: "traveling_wave_file",
}

SINGLE_FILE_CATEGORIES = {CATEGORY_WAVE, CATEGORY_LIGHTNING, CATEGORY_LEDGER}

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_WAVE: "录波数据",
    CATEGORY_LIGHTNING: "雷电定位数据",
    CATEGORY_LEDGER: "线路台账",
    CATEGORY_TRAVELING_WAVE: "行波数据",
}

CATEGORY_DISCOVER_SPECS: dict[str, tuple[str, set[str], str]] = {
    CATEGORY_WAVE: ("1", {".txt", ".json", ".csv", ".pdf", ".xlsx", ".xlsm"}, "录波数据"),
    CATEGORY_LIGHTNING: ("2", {".xlsx", ".xlsm", ".csv"}, "雷电定位数据"),
    CATEGORY_LEDGER: ("3", {".csv", ".xlsx"}, "线路台账"),
}

TRAVELING_WAVE_SUFFIXES = {".txt", ".json"}

_PREFIX_RE = re.compile(r"^[123]")


class InputDiscoveryError(ValueError):
    pass


def _matches_prefix(filename: str, prefix: str) -> bool:
    return bool(re.match(rf"^{re.escape(prefix)}", filename))


def discover_one(input_dir: Path, prefix: str, suffixes: set[str], label: str) -> Path | None:
    candidates: list[Path] = []
    for path in sorted(Path(input_dir).iterdir()):
        if not path.is_file():
            continue
        if _matches_prefix(path.name, prefix) and path.suffix.lower() in suffixes:
            candidates.append(path)
    if len(candidates) > 1:
        names = "、".join(p.name for p in candidates)
        raise InputDiscoveryError(f"发现多个{label}文件，请仅保留一个：{names}")
    return candidates[0] if candidates else None


def discover_waveforms(input_dir: Path) -> list[Path]:
    waves: list[Path] = []
    for path in sorted(Path(input_dir).iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TRAVELING_WAVE_SUFFIXES:
            continue
        if _PREFIX_RE.match(path.name):
            continue
        waves.append(path)
    return waves


def normalize_input_files(
    files: dict[str, Sequence[Path]],
) -> dict[str, list[Path]]:
    normalized: dict[str, list[Path]] = {}
    for category, paths in files.items():
        if category in SINGLE_FILE_CATEGORIES and len(paths) > 1:
            label = CATEGORY_LABELS.get(category, category)
            names = "、".join(p.name for p in paths)
            raise InputDiscoveryError(f"同一类别{label}允许且仅允许一个文件，请保留一个：{names}")
        normalized[category] = list(paths)
    return normalized


def map_category_to_field(category: str) -> str:
    field = CATEGORY_FIELDS.get(category)
    if field is None:
        raise InputDiscoveryError(f"未知输入类别: {category}")
    return field