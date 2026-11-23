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

该模块只负责字段到路径段的翻译，不依赖 ORM / 存储驱动，便于单测。
"""

ATP_TREE_LAYOUT = "atp_tree"
LEGACY_LAYOUT = "legacy"
SUPPORTED_EXPORT_LAYOUTS = frozenset({LEGACY_LAYOUT, ATP_TREE_LAYOUT})

_SHIELD_SUFFIXES: dict[str, str] = {
    "single": "d",
    "none": "no",
    "no": "no",
    "without": "no",
    "无": "no",
    "无避雷线": "no",
}

_UNSAFE_SEGMENT_RE = re.compile(r"[\\/\x00-\x1f]+")


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


def atp_tree_relative_dir(source: Any) -> str:
    """返回相对 ATP 根目录的 POSIX 风格目录，如 ``500/ganzi/fanji/noM``。

    ``source`` 可以是 ORM 对象、dict 或任意带同名字段的对象。
    """
    voltage = _clean_segment(_field(source, "voltage_level"), "voltage_level")
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
