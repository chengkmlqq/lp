from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

"""ATP 目录树导出布局。

目标目录结构与 D:\\ATP 一致：

    电压等级 / 塔型 / 场景 / 避雷器措施 / 模型文件

约定（2026-11-23）：

* ``115``、``230`` 保持独立电压目录，不归并到 ``110`` / ``220``；
* ``shield_wire=single`` 在塔型后加 ``d``，如 ``66/guxingd``；
* ``shield_wire=none/no/without`` 在塔型后加 ``no``，如 ``110/ganzino``；
* ``arrester_config=shuzhi-noM`` 原样建目录，是独立于 ``noM`` 的新措施目录；
* 不生成 ``version`` 层目录，版本择一由导出侧决定（默认激活版本）。

除目录翻译外，本模块还负责导出时的 ``$INCLUDE`` / ``$INSERT`` 路径重写：
Web 端计算是在运行时把路径按文件名重构到任务私有目录（见
``fl_analysis_external._rewrite_includes``），而 C# 侧直接运行 tpbig，没有这一步。
因此导出 ``atp_tree`` 包时必须把路径改写成 C# 机器的绝对路径
``D:\\ATP\\{电压}\\{塔型}\\{场景}\\{措施}\\{文件名}``，否则 C# 会去打开上传者机器
上的原始路径（或静默读到本机另一份同名 lib）。

该模块只负责字段到路径段的翻译与文本改写，不依赖 ORM / 存储驱动，便于单测。
"""

ATP_TREE_LAYOUT = "atp_tree"
LEGACY_LAYOUT = "legacy"
SUPPORTED_EXPORT_LAYOUTS = frozenset({LEGACY_LAYOUT, ATP_TREE_LAYOUT})

# C# 侧 ATP 根目录（统一固定，2026-11-24 与用户确认）。
ATP_ROOT_DEFAULT = "D:\\ATP"

# ATP 卡片是 80 列固定格式；$INCLUDE 超列会 KILL=79「last card in error」
# （2026-09-15 真机实测，见 _private_engine_dir 注释）。
ATP_CARD_MAX_COLUMNS = 80

_SHIELD_SUFFIXES: dict[str, str] = {
    "single": "d",
    "none": "no",
    "no": "no",
    "without": "no",
    "无": "no",
    "无避雷线": "no",
}

_UNSAFE_SEGMENT_RE = re.compile(r"[\\/\x00-\x1f]+")
# 平台历史数据/导入包里的电压可能带单位（如 ``500kV``），而 D 盘目录是纯数字。
_VOLTAGE_UNIT_RE = re.compile(r"(?i)\s*kv$")


def _field(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _clean_segment(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"ATP 目录树导出缺少字段 {field_name}，无法确定目录")
    cleaned = _UNSAFE_SEGMENT_RE.sub("_", text)
    if cleaned in {".", ".."} or cleaned.endswith("."):
        raise ValueError(f"ATP 目录树导出字段 {field_name} 不是合法目录名: {value!r}")
    return cleaned


def tower_type_directory(tower_type: Any, shield_wire: Any = None) -> str:
    """把塔型 + 避雷线配置翻译成 D 盘二级目录名。

    ``with``（以及空值）保持塔型原名；``single`` 加 ``d``；无避雷线加 ``no``。
    已经带后缀的塔型（如 ``ganzino``）不会重复追加。
    """
    tower = _clean_segment(tower_type, "tower_type")
    shield = "" if shield_wire is None else str(shield_wire).strip().lower()
    suffix = _SHIELD_SUFFIXES.get(shield)
    if not suffix or tower.endswith(suffix):
        return tower
    return f"{tower}{suffix}"


def voltage_directory(value: Any) -> str:
    """电压等级目录名：去掉 ``kV`` 单位后缀，其余原样（115/230 不映射到 110/220）。"""
    text = _clean_segment(value, "voltage_level")
    stripped = _VOLTAGE_UNIT_RE.sub("", text).strip()
    if not stripped:
        raise ValueError(f"ATP 目录树导出电压等级为空: {value!r}")
    return stripped


def atp_tree_relative_dir(source: Any) -> str:
    """返回相对 ATP 根目录的 POSIX 风格目录，如 ``500/ganzi/fanji/noM``。

    ``source`` 可以是 ORM 对象、dict 或任意带同名字段的对象。
    """
    voltage = voltage_directory(_field(source, "voltage_level"))
    tower = tower_type_directory(
        _field(source, "tower_type"),
        _field(source, "shield_wire"),
    )
    scene = _clean_segment(_field(source, "scene_type"), "scene_type")
    measure = _clean_segment(_field(source, "arrester_config"), "arrester_config")
    return PurePosixPath(voltage, tower, scene, measure).as_posix()


def safe_member_path(directory: str, relative_path: str) -> str:
    """把资产内相对路径安全地挂到目标目录下，拒绝绝对路径与上层穿越。"""
    rel = PurePosixPath(relative_path.replace("\\", "/"))
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"非法的模型文件相对路径: {relative_path!r}")
    root = PurePosixPath(directory)
    return root.joinpath(rel).as_posix()


# ─────────────────────────────────────────────────────────────
# $INCLUDE / $INSERT 路径重写（导出给 C# 用）
# ─────────────────────────────────────────────────────────────


def target_include_path(
    filename: str, relative_dir: str, *, root: str = ATP_ROOT_DEFAULT
) -> str:
    """拼出 C# 机器上的绝对引用路径：``{root}\\{电压}\\{塔型}\\{场景}\\{措施}\\{文件名}``。

    ``relative_dir`` 用 POSIX 风格（与 zip 内目录一致），输出统一反斜杠。
    """
    segments = [seg for seg in relative_dir.replace("\\", "/").split("/") if seg]
    return "\\".join([root.rstrip("\\"), *segments, filename])


def _basename(value: str) -> str:
    """取路径最后一段文件名，兼容 ``\\`` 与 ``/`` 两种分隔符。"""
    return value.replace("/", "\\").rsplit("\\", 1)[-1].strip()


def _split_trailing_note(field: str) -> tuple[str, str]:
    """拆出 ATP 卡片的行尾 ``$$`` 注释，返回 ``(字段值, 含前导空格的注释)``。

    与 ``fl_analysis_external._split_atp_trailing_note`` 同口径：
    ``$INCLUDE, C:\\ATP60work\\batch\\110_guxing_fanji\\dahao.lib $$`` 这类
    不带节点参数的卡片，若不先剥注释，basename 会得到 ``dahao.lib $$``，
    后缀判定失效 → 该行不会被改写。
    """
    idx = field.find("$$")
    if idx < 0:
        return field.strip(), ""
    return field[:idx].strip(), " " + field[idx:].strip()


def rewrite_atp_include_paths(
    text: str,
    relative_dir: str,
    *,
    root: str = ATP_ROOT_DEFAULT,
) -> dict[str, Any]:
    """把 ``work.atp`` 里 ``$INCLUDE *.lib`` / ``$INSERT *.pch`` 的目录重写为目标目录。

    只信任文件名（与运行时链路一致），原路径是 ``C:\\ATP6\\...``、
    ``C:\\ATP60work\\...``、``D:\\ATP\\...`` 还是相对写法都能纠正。
    保留原行尾（CRLF/LF）与节点参数、行尾注释。

    返回 ``{"text": 新文本, "changed": 改写行数, "rewritten": [...], "warnings": [...]}``；
    已指向目标路径的行按幂等处理，不重复改写、不计数。

    列宽：ATP 卡片硬限 80 列，超列会在引擎侧 KILL=79。超限行仍会写入
    （原路径必然不可用，保留原路径只会更难排查），但记入 ``warnings`` 供导出清单暴露。
    """
    changed = 0
    rewritten: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    out_lines: list[str] = []

    for line_no, raw_line in enumerate(text.splitlines(keepends=True), start=1):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        stripped_upper = line.strip().upper()

        kind: str | None = None
        suffix = ""
        if stripped_upper.startswith("$INSERT") and ".pch" in line.lower():
            kind, suffix = "$INSERT", ".pch"
        elif stripped_upper.startswith("$INCLUDE") and ".lib" in line.lower():
            kind, suffix = "$INCLUDE", ".lib"
        if kind is None:
            out_lines.append(raw_line)
            continue

        head, sep, rest = line.partition(",")
        if not sep:
            out_lines.append(raw_line)
            continue

        # $INSERT 只有一个路径参数；$INCLUDE 后面还有节点名，需原样保留。
        first, sep2, tail = rest.partition(",")
        value, note = _split_trailing_note(first)
        filename = _basename(value)
        if not filename.lower().endswith(suffix):
            out_lines.append(raw_line)
            continue

        target = target_include_path(filename, relative_dir, root=root)
        # 已指向目标路径（大小写/分隔符差异视为同一路径）时保持原行，避免重复导出
        # 反复改写、也避免无意义的格式变化。
        already_target = (
            value.strip().replace("/", "\\").rstrip("\\").lower() == target.lower()
        )
        if already_target:
            out_lines.append(raw_line)
            continue

        new_line = f"{head},{target}{note}"
        if kind == "$INCLUDE" and sep2:
            new_line += f",{tail}"

        columns = len(new_line.encode("gbk", errors="replace"))
        if columns > ATP_CARD_MAX_COLUMNS:
            warnings.append(
                {
                    "line": line_no,
                    "kind": kind,
                    "path": target,
                    "columns": columns,
                    "reason": f"改写后 {columns} 列超过 ATP 80 列上限，引擎可能报 KILL=79",
                }
            )

        if new_line != line:
            changed += 1
            rewritten.append(
                {
                    "line": line_no,
                    "kind": kind,
                    "from": value,
                    "to": target,
                    "columns": columns,
                }
            )
        out_lines.append(new_line + ending)

    return {
        "text": "".join(out_lines),
        "changed": changed,
        "rewritten": rewritten,
        "warnings": warnings,
    }


def rewrite_atp_model_bytes(
    content: bytes,
    relative_dir: str,
    *,
    root: str = ATP_ROOT_DEFAULT,
) -> tuple[bytes, dict[str, Any]]:
    """对 ``.atp`` 文件字节做引用路径改写，返回 ``(新字节, 诊断信息)``。

    编码策略：先试 UTF-8（严格），失败再试 GBK；两者都要求
    ``decode → encode`` 字节完全一致才动文本，避免把注释里的中文改坏。
    都无法无损解码（或含二进制内容）时原样返回，并给出 warning，
    由导出清单提示人工核对。
    """
    for encoding in ("utf-8", "gbk"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.encode(encoding) != content:
            # 该编码有损（例如 GBK 误读 UTF-8 文本），换下一个候选。
            continue
        result = rewrite_atp_include_paths(text, relative_dir, root=root)
        return result["text"].encode(encoding), result

    return content, {
        "text": "",
        "changed": 0,
        "rewritten": [],
        "warnings": [
            {
                "kind": "encoding",
                "reason": "文件无法按 UTF-8/GBK 无损解码，未改写 $INCLUDE 路径，需人工核对",
            }
        ],
    }
