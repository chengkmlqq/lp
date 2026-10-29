"""ATP 模型槽位扫描器（改造目标 1）。

从真实 ATP 模型文件自动提取两类槽位信息，供模型管理查看、
参数模板配置下拉（并集）、覆盖检测、以及 .dat 几何改写使用：

1. **work.atp 的 $PARAMETER 段**：`NAME=VALUE` 赋值行 → 槽位名及其当前值。
2. **几何 .dat（long/short/dahao/xiaohao）**：推导几何改写所需坐标：
   - `conductor_start`：导体卡起始行（METRIC 行下一行，1-based）
   - `conductor_count`：实际导体行数（METRIC 之后 → "BLANK CARD ENDING
     CONDUCTOR" 之前），天然适配「无避雷线变体」（12 导体 vs 14 导体）
   - `col_*`：列位常量（ATP 卡格式固定：34=X 中距 / 42=Y 高度 / 50=第三维）
   - `span_rows`：频率卡块行号（"ENDING CONDUCTOR" → "ENDING FREQUENCY" 之间非空行）
   - `span_col` / `span_width`：档距列位与宽度

产物结构（dict，可直接 json 序列化存 AtpAsset.slots_json）::

    {
      "scanned_at": "2026-10-29T...",
      "work_atp": {
        "slots": {"RER001": "15.", "RELE01": "24.", ...},
        "count": 26
      },
      "geometry": {
        "long":  {"conductor_start": 7, "conductor_count": 5,
                  "col_x": 34, "col_y": 42, "col_z": 50,
                  "span_rows": [12, 13, 14], "span_col": 44, "span_width": 10},
        "short": {...}, "dahao": {...}, "xiaohao": {...}
      }
    }

本模块只做解析，不碰数据库；文件内容由调用方提供（bytes / 文本行），
便于 API 层从 storage driver 读取后传入。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# 与 atp_dat_writer 保持一致的 .dat 名称集合
DAT_GEOMETRY_NAMES: tuple[str, ...] = ("long", "short", "dahao", "xiaohao")

# ATP LINE CONSTANTS 卡几何列位（固定格式，非塔型差异）
COL_X = 34   # 导体 X（中距）
COL_Y = 42   # 导体 Y（高度）
COL_Z = 50   # 第三维
# 档距写在频率卡块，固定列位
SPAN_COL = 44
SPAN_WIDTH = 10

_PARAM_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\S+)\s*$")


def scan_work_atp_slots(text: str) -> dict[str, Any]:
    """解析 work.atp 的 $PARAMETER 段，返回槽位名 → 当前展示值。"""
    slots: dict[str, str] = {}
    in_params = False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        up = line.strip()
        if up.upper() == "$PARAMETER":
            in_params = True
            continue
        if not in_params:
            continue
        if up.upper().startswith("BLANK $PARAMETER") or up.upper() in ("$ENDBR", "BLANK"):
            break
        m = _PARAM_RE.match(line)
        if m:
            slots[m.group(1)] = m.group(2)
    return {"slots": slots, "count": len(slots)}


def _conductor_start_and_count(lines: list[str]) -> tuple[int, int]:
    """返回 (导体卡起始 1-based 行号, 实际导体行数)。

    与 atp_dat_writer._conductor_line_offset / _count_conductor_lines 同源逻辑：
    METRIC 行的下一行为导体 1；找不到 METRIC 时回退起始 7。
    导体数 = METRIC 之后到 "ENDING CONDUCTOR" 之前的非空行数。
    """
    start = 7
    seen = 0
    in_metric = False
    for i, ln in enumerate(lines):
        up = ln.strip().upper()
        if up == "METRIC":
            start = i + 2  # 1-based：METRIC 行(i+1)的下一行 = i+2
            in_metric = True
            continue
        if in_metric and "ENDING CONDUCTOR" in up:
            break
        if in_metric and ln.strip():
            seen += 1
    return start, seen


def _span_rows(lines: list[str]) -> list[int]:
    """频率卡块 1-based 行号（"ENDING CONDUCTOR" → "ENDING FREQUENCY" 之间非空行）。"""
    rows: list[int] = []
    start: int | None = None
    for i, ln in enumerate(lines):
        up = ln.upper()
        if start is None and "ENDING CONDUCTOR" in up:
            start = i + 1  # 1-based
        elif start is not None and "ENDING FREQUENCY" in up:
            break
        elif start is not None and ln.strip():
            rows.append(i + 1)
    return rows


def scan_geometry_dat(text: str) -> dict[str, Any]:
    """解析单个几何 .dat，返回几何改写所需坐标。"""
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    conductor_start, conductor_count = _conductor_start_and_count(lines)
    return {
        "conductor_start": conductor_start,
        "conductor_count": conductor_count,
        "col_x": COL_X,
        "col_y": COL_Y,
        "col_z": COL_Z,
        "span_rows": _span_rows(lines),
        "span_col": SPAN_COL,
        "span_width": SPAN_WIDTH,
    }


def scan_model_slots(
    *,
    work_atp_text: str | None = None,
    dat_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """组合扫描一个 ATP 模型：work.atp 槽位 + 各几何 .dat 坐标。

    参数:
        work_atp_text: work.atp 全文（文本）。缺省时 work_atp 部分置空。
        dat_texts: {"long": 文本, "short": 文本, ...}，键须在 DAT_GEOMETRY_NAMES 内。
    返回:
        可直接序列化存 AtpAsset.slots_json 的 dict。
    """
    result: dict[str, Any] = {
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if work_atp_text:
        result["work_atp"] = scan_work_atp_slots(work_atp_text)
    else:
        result["work_atp"] = {"slots": {}, "count": 0}

    geometry: dict[str, Any] = {}
    for name in DAT_GEOMETRY_NAMES:
        text = (dat_texts or {}).get(name)
        if text is not None:
            geometry[name] = scan_geometry_dat(text)
    result["geometry"] = geometry
    return result


# 便捷入口：从磁盘路径扫描（本地开发/模板探测用，生产走 storage driver）
def scan_model_slots_from_paths(
    *,
    work_atp: str | None = None,
    dats: dict[str, str] | None = None,
) -> dict[str, Any]:
    """同 scan_model_slots，但接受文件路径；.dat 二进制文件按 GBK 解码兜底。"""
    work_atp_text: str | None = None
    if work_atp:
        raw = open(work_atp, "rb").read()
        try:
            work_atp_text = raw.decode("utf-8", errors="replace")
        except Exception:
            work_atp_text = raw.decode("gbk", errors="replace")

    dat_texts: dict[str, str] = {}
    for name, path in (dats or {}).items():
        raw = open(path, "rb").read()
        try:
            dat_texts[name] = raw.decode("utf-8", errors="replace")
        except Exception:
            dat_texts[name] = raw.decode("gbk", errors="replace")

    return scan_model_slots(work_atp_text=work_atp_text, dat_texts=dat_texts)