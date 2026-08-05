"""ATP 模型电路拓扑在线预览解析器。

核心设计：不解析 ATP 复杂元件行格式（TACS / BRANCH / SWITCH / SOURCE），
只解析 `$PARAMETER` 参数块，再用 LP 域映射表把参数名映射为带语义的电路节点。
LP 所有 ATPDraw 模板变体共享同一套参数命名规则（只改数值），故无需改解析逻辑。

真实模板（GBK/混合编码）示例（deploy/dev-deploy/data/app/wine/ATP/templates/.../work.atp）：:

    $PARAMETER
    RER001=15.
    RELENS____=1.31
    REIGAN____=65.83
    REHG______=28.8
    REHC1_____=19.35
    REHC2_____=22.85
    REHC3_____=19.35
    REBB______=-384615.4
    REAA1_____=0.0000026
    BLANK $PARAMETER

拓扑组装为固定结构：大地(gnd) → 接地电阻(rg) → 塔身(tower) → 绝缘子(ins)
→ 雷电流源(source) 注入；塔身分接 A/B/C 三相横担(tower_arm) → 三相线路节点(line)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# $PARAMETER 块内参数行：`RER001=15.` / `REIAMP____=-65831.6` / `REAA1_____=0.0000026`
_PARAM_LINE_RE = re.compile(r"^\s*([A-Za-z_][\w]*)\s*=\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*$")

# 参数块定界
_PARAM_BEGIN_MARKERS = ("$PARAMETER", "$PARAMETERS")
_PARAM_END_MARKERS = ("BLANK $PARAMETER", "BLANK $PARAMETERS", "$ENDBLOCK", "$ENDBLOCKS")

# 编码探测顺序：真实模板为 GBK 编码（含中文注释），但也要兼容 utf-8 / latin-1
_DECODE_ORDER = ("utf-8", "gbk", "latin-1")


@dataclass(slots=True)
class AtpNode:
    """电路节点。

    params 结构：
    - 语义节点（如接地电阻/绝缘子）：``{"param": 参数名, "value": 数值, "unit": 单位, "desc": 描述}``
    - 无参数节点（如大地/线路）：``{}``
    """

    id: str
    label: str
    node_type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AtpEdge:
    """电路连接边。"""

    id: str
    source: str
    target: str
    label: str = ""
    edge_type: str = "link"


@dataclass(slots=True)
class AtpTopology:
    """解析后的电路拓扑。"""

    nodes: list[AtpNode]
    edges: list[AtpEdge]
    parameters: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


# LP 域映射：ATPDraw 模板参数名 → 语义化电路元件
# node_type 取值：source / insulator / tower_body / tower_arm / impedance / resistor / parameter
LP_ELEMENT_MAP: dict[str, dict[str, Any]] = {
    "REHG____": {
        "key": "tower_body",
        "label": "塔身",
        "node_type": "tower_body",
        "unit": "m",
        "desc": "塔高",
    },
    "REHC1_____": {
        "key": "tower_arm",
        "label": "A相横担",
        "node_type": "tower_arm",
        "unit": "m",
        "desc": "A相横担高",
    },
    "REHC2_____": {
        "key": "tower_arm",
        "label": "B相横担",
        "node_type": "tower_arm",
        "unit": "m",
        "desc": "B相横担高",
    },
    "REHC3_____": {
        "key": "tower_arm",
        "label": "C相横担",
        "node_type": "tower_arm",
        "unit": "m",
        "desc": "C相横担高",
    },
    "REBB______": {
        "key": "impedance",
        "label": "杆塔波阻抗",
        "node_type": "impedance",
        "unit": "Ω",
        "desc": "杆塔波阻抗",
    },
    "REAA1_____": {
        "key": "parameter",
        "label": "衰减系数",
        "node_type": "parameter",
        "unit": "",
        "desc": "衰减系数",
    },
    "RER001": {
        "key": "resistor",
        "label": "接地电阻",
        "node_type": "resistor",
        "unit": "Ω",
        "desc": "接地电阻",
    },
    "RELENS____": {
        "key": "insulator",
        "label": "绝缘子串",
        "node_type": "insulator",
        "unit": "m",
        "desc": "绝缘子串长度",
    },
    "REIGAN____": {
        "key": "source",
        "label": "雷电流源",
        "node_type": "source",
        "unit": "kA",
        "desc": "雷电流幅值",
    },
}

# 未在映射表中的参数，仍可作为普通参数透出，但不再生成节点
_NODE_ORDER: tuple[str, ...] = ("gnd", "rg", "tower", "ins", "source")
_ARM_NODES = ("arm_a", "arm_b", "arm_c")
_LINE_NODES = ("line_a", "line_b", "line_c")


def decode_atp_bytes(content: bytes) -> str:
    """按 utf-8 → gbk → latin-1 顺序自动解码 .atp 内容。

    Args:
        content: .atp 文件原始字节。

    Returns:
        解码后的文本。

    Raises:
        UnicodeDecodeError: 三种编码均无法解码时抛出。
    """
    last_error: UnicodeDecodeError | None = None
    for encoding in _DECODE_ORDER:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


def _extract_parameters(text: str) -> dict[str, float]:
    """解析 `$PARAMETER` 块，返回 {参数名: 数值}。

    仅匹配 `NAME=number` 形式；行内尾随注释、空行、非数值行均被跳过。
    """
    parameters: dict[str, float] = {}
    in_parameter_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if not in_parameter_block:
            if any(upper.startswith(marker) for marker in _PARAM_BEGIN_MARKERS):
                in_parameter_block = True
            continue
        if any(upper.startswith(marker) for marker in _PARAM_END_MARKERS):
            break
        match = _PARAM_LINE_RE.match(line)
        if not match:
            continue
        name, value_str = match.group(1), match.group(2)
        try:
            parameters[name] = float(value_str)
        except ValueError:
            continue
    return parameters


def _normalize_param_name(name: str) -> str:
    """去掉尾部下划线，得到参数基础名。

    LP 各 ATPDraw 模板对同一种参数的下划线数量存在细微差异
    （如 `REHG____` vs `REHG______`），通过尾部下划线归一化保证映射表精确匹配。
    """
    return name.rstrip("_")


def _find_parameter(parameters: dict[str, float], map_key: str) -> float | None:
    """在已解析参数中查找映射表键对应的数值，兼容尾部下划线数量差异。"""
    exact = parameters.get(map_key)
    if exact is not None:
        return exact
    normalized = _normalize_param_name(map_key)
    for name, value in parameters.items():
        if _normalize_param_name(name) == normalized:
            return value
    return None


def _build_topology(parameters: dict[str, float]) -> AtpTopology:
    """根据 LP 固定拓扑组装节点与边。

    拓扑结构：:

        source(雷电流源) -- ins(绝缘子) -- tower(塔身) -- rg(接地电阻) -- gnd(大地)
                                             │
                           ┌─────────────────┼─────────────────┐
                        arm_a              arm_b             arm_c
                           │                 │                 │
                        line_a            line_b            line_c

    三相横担/线路按模板是否出现对应 REHC1/2/3 参数动态裁剪，
    但大地/接地电阻/塔身/绝缘子/雷电流源 5 个主节点始终存在。
    """
    nodes: list[AtpNode] = []
    edges: list[AtpEdge] = []

    def _param(name: str) -> float | None:
        return _find_parameter(parameters, name)

    def _push_node(node_id: str, label: str, node_type: str, param_name: str | None = None) -> str:
        node_params: dict[str, Any] = {}
        if param_name and _param(param_name) is not None:
            mapping = LP_ELEMENT_MAP.get(param_name, {})
            node_params["param"] = param_name
            node_params["value"] = _param(param_name)
            node_params["unit"] = mapping.get("unit", "")
            node_params["desc"] = mapping.get("desc", "")
        nodes.append(AtpNode(id=node_id, label=label, node_type=node_type, params=node_params))
        return node_id

    def _push_edge(source: str, target: str, label: str = "", edge_type: str = "link") -> str:
        edge_id = f"e_{source}->{target}"
        edges.append(AtpEdge(id=edge_id, source=source, target=target, label=label, edge_type=edge_type))
        return edge_id

    # 主链路：大地 → 接地电阻 → 塔身 → 绝缘子 → 雷电流源
    gnd_id = _push_node("gnd", "大地", "ground")
    rg_id = _push_node("rg", "接地电阻", "resistor", "RER001")
    tower_id = _push_node("tower", "塔身", "tower_body", "REHG____")
    ins_id = _push_node("ins", "绝缘子串", "insulator", "RELENS____")
    source_id = _push_node("source", "雷电流源", "source", "REIGAN____")

    _push_edge(gnd_id, rg_id, label="接地", edge_type="link")
    _push_edge(rg_id, tower_id, label="", edge_type="link")
    _push_edge(tower_id, ins_id, label="", edge_type="link")
    _push_edge(ins_id, source_id, label="注入", edge_type="link")

    # 塔身分接三相横担 → 三相线路
    arm_param_map = {
        "arm_a": "REHC1_____",
        "arm_b": "REHC2_____",
        "arm_c": "REHC3_____",
    }
    for arm_id in _ARM_NODES:
        param_name = arm_param_map[arm_id]
        if _param(param_name) is None:
            continue
        phase = arm_id.split("_")[-1].upper()
        arm_node_id = _push_node(arm_id, f"{phase}相横担", "tower_arm", param_name)
        line_node_id = _push_node(f"line_{arm_id.split('_')[-1]}", f"{phase}相线路", "line")
        _push_edge(tower_id, arm_node_id, label=f"{phase}相", edge_type="branch")
        _push_edge(arm_node_id, line_node_id, label="", edge_type="link")

    # 拓扑 metadata：主节点/参数汇总信息
    metadata: dict[str, Any] = {
        "source_parameter": "REIGAN____",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "tower_phases": [arm_id.split("_")[-1].upper() for arm_id in _ARM_NODES if _param(arm_param_map[arm_id]) is not None],
    }
    return AtpTopology(nodes=nodes, edges=edges, parameters=parameters, metadata=metadata)


def parse_atp_topology(atp_content: str) -> AtpTopology:
    """从 .atp 文本内容解析电路拓扑。

    Args:
        atp_content: 已解码的 .atp 文本。

    Returns:
        AtpTopology，包含 nodes / edges / parameters / metadata。
    """
    parameters = _extract_parameters(atp_content)
    return _build_topology(parameters)


def parse_atp_topology_from_bytes(content: bytes) -> AtpTopology:
    """从 .atp 原始字节解析电路拓扑（自动探测编码）。

    Args:
        content: .atp 文件原始字节。

    Returns:
        AtpTopology。
    """
    text = decode_atp_bytes(content)
    topology = parse_atp_topology(text)
    topology.metadata["encoding"] = _detect_encoding(content)
    return topology


def _detect_encoding(content: bytes) -> str:
    """探测实际使用的解码编码（供 metadata 展示）。"""
    for encoding in _DECODE_ORDER:
        try:
            content.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "unknown"
