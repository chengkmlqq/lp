"""ATP 模型 .atp 文件解析 → 3D 场景 JSON（供前端 Three.js 绘制电路拓扑）。

设计目标（2026-09-30 新增，配合 web 端 atp-scene-viewer.tsx）：
- 把 ATP 输入卡（定长 ASCII）解析成一张可绘制的「节点-支路」图：
  节点命名、支路（R/L/C）、开关、电源、$PARAMETER 参数表、
  $INCLUDE 引用的 .lib 线路段（作为「宏块」节点展示）。
- 纯离线解析，不依赖 wine/ATP 引擎；GBK 中文注释用 _decode_text_file 处理。
- 输出 schema ``lp.atp.scene/1``：{nodes, branches, switches, sources,
  parameters, includes, stats, sections}，前端据此做 3D 布局与渲染。
- 解析失败的容忍策略：任何段解析异常只记入 warnings，不整体失败——
  前端总是能画出「尽力而为」的拓扑，而不是一个白屏错误。
"""

from __future__ import annotations

import re
from typing import Any

# =============================== 段标记 ====================================
_SECTION_MARKERS = {
    "$PARAMETER": "parameter",
    "/TACS": "tacs",
    "/BRANCH": "branch",
    "/SWITCH": "switch",
    "/SOURCE": "source",
    "/OUTPUT": "output",
}
# 段结束标记：BLANK <SECTION> 或 BLANK $PARAMETER
_BLANK_END_RE = re.compile(r"^\s*BLANK\s+(.+?)\s*$", re.IGNORECASE)

# 定长卡类型前缀：ATPDRAW 卡的第一个字母/数字决定类型
#  - 1x 支路/元件（10=普通支路, 11=TACS信号, 12=非线性, 13=开关, 14=电压源, 15=电流源）
#  - 99 类型线路段/非线性电阻等
#  - -1 输出标志 + 支路（负数前缀表示该支路要输出）
#
# ATP 卡行首布局（ATPDRAW 生成）：
#   列0-1 可选标志（-1 / 13 / 14 / 99 / 15 等），随后 n1、n2 各 6 字符节点名
#   例：-1XX0117XX0001（标志 -1 + XX0117 + XX0001）
#      13XXJUE1LINE1A（标志 13 + XXJUE1 + LINE1A）
#      14XXSS2A  89814.6（标志 14 + XXSS2A + 幅值）
#      99XX0077XX0078（标志 99 + XX0077 + XX0078）
#   节点名规则：字母开头，1-6 个字符（字母/数字）。
_CARD_NODES_RE = re.compile(
    r"^\s*(?:-?\d{1,2})?\s*"
    r"([A-Za-z][A-Za-z0-9]{0,5})"       # n1
    r"(?:\s*([A-Za-z][A-Za-z0-9]{0,5}))?"  # n2（可选）
)
# $INCLUDE 端口节点名提取（路径之后的端口列表）
_NODE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,5}")


def _parse_parameter_block(lines: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """解析 $PARAMETER 段：NAME=VALUE 行，直到 BLANK $PARAMETER。"""
    params: list[dict[str, str]] = []
    warnings: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("BLANK"):
            continue
        if "=" in stripped:
            name, _, value = stripped.partition("=")
            params.append({"name": name.strip(), "value": value.strip()})
    return params, warnings


def _split_card_nodes(line: str) -> tuple[str | None, str | None]:
    """从定宽卡行提取 n1/n2 节点名（各 6 字符）。

    ATPDRAW 定宽布局：列0 类型/标志，列1-6 n1，列7-12 n2。
    兼容紧凑/宽松两种写法：先试定宽切片，失败再试正则。
    """
    # 去掉行首的类型/标志字符（-1 / 13 / 14 / 99 等，非字母开头的最多 2 字符）
    stripped = line.lstrip()
    if not stripped:
        return None, None
    return _split_card_nodes_impl(stripped)


def _split_card_nodes_impl(line: str) -> tuple[str | None, str | None]:
    match = _CARD_NODES_RE.match(line)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _collect_nodes_from_cards(cards: list[tuple[str | None, str | None]]) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for n1, n2 in cards:
        for node in (n1, n2):
            if node and node not in seen_set:
                seen.append(node)
                seen_set.add(node)
    return seen


def parse_atp_scene(
    atp_text: str,
    *,
    source_file: str = "work.atp",
) -> dict[str, Any]:
    """解析 .atp 文本为场景 JSON（schema ``lp.atp.scene/1``）。

    返回结构：
    {
      "schema": "lp.atp.scene/1",
      "source_file": ...,
      "parameters": [{"name","value"}],
      "includes": [{"path","ports":[node,...]}],
      "nodes": [{"id","kind"}],            # kind: branch|switch|source|ground|include
      "branches": [{"n1","n2","r","l","c"}],
      "switches": [{"n1","n2","control","type"}],
      "sources": [{"node","kind","amplitude","freq","phase"}],
      "stats": {"node_count","branch_count","switch_count","source_count","include_count","param_count","warnings"},
      "warnings": [...],
    }
    """
    warnings: list[str] = []
    parameters: list[dict[str, str]] = []
    includes: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    # 预扫描段边界
    section_order: list[str] = []
    section_lines: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in atp_text.splitlines():
        line = raw_line.rstrip()
        upper = line.upper().strip()

        # 段开始
        started = False
        for marker, key in _SECTION_MARKERS.items():
            if upper.startswith(marker):
                current_section = key
                section_order.append(key)
                section_lines.setdefault(key, [])
                started = True
                break
        if started:
            continue

        # 段结束（BLANK <SECTION>）
        blank_end = _BLANK_END_RE.match(line)
        if blank_end:
            current_section = None
            continue

        if current_section:
            section_lines.setdefault(current_section, []).append(line)
        # $INCLUDE 出现在 BRANCH 段中间，单独收集（支持续行：行首是逗号的端口延续）
        if upper.startswith("$INCLUDE"):
            match = re.match(
                r"\$INCLUDE\s*,\s*([^,]+)\s*,\s*(.*?)\s*\$\$",
                line,
                re.IGNORECASE,
            )
            if match:
                path = match.group(1).strip()
                ports = [
                    p.strip()
                    for p in _NODE_NAME_RE.findall(match.group(2))
                ]
                includes.append({"path": path, "ports": ports})
        elif includes and upper.startswith(","):
            # 续行：端口列表延续到下一行（如 ", XX0126, XX0141, X0142A..."）
            includes[-1]["ports"].extend(
                p.strip() for p in _NODE_NAME_RE.findall(line)
            )

    # ---- $PARAMETER ----
    if "parameter" in section_lines:
        parameters, pwarn = _parse_parameter_block(section_lines["parameter"])
        warnings.extend(pwarn)

    # ---- /BRANCH ----
    branch_cards: list[tuple[str | None, str | None, str]] = []
    for line in section_lines.get("branch", []):
        upper = line.strip().upper()
        if not upper or upper.startswith("C ") or upper.startswith("*"):
            continue
        if upper.startswith("$INCLUDE"):
            continue  # 已在上面收集
        n1, n2 = _split_card_nodes(line)
        if not n1:
            continue
        if n2:
            branch_cards.append((n1, n2, line))
            branches.append(_parse_branch_line(line, n1, n2))
        else:
            # 单节点卡：一端接地（R/C 对地支路），以 n1 为节点
            branch_cards.append((n1, None, line))
            branches.append(_parse_branch_line(line, n1, None))

    # ---- /SWITCH ----
    switch_cards: list[tuple[str | None, str | None]] = []
    for line in section_lines.get("switch", []):
        upper = line.strip().upper()
        if not upper or upper.startswith("C ") or upper.startswith("*"):
            continue
        n1, n2 = _split_card_nodes(line)
        if n1 and n2:
            switch_cards.append((n1, n2))
            switches.append(_parse_switch_line(line, n1, n2))

    # ---- /SOURCE ----
    source_cards: list[str] = []
    for line in section_lines.get("source", []):
        upper = line.strip().upper()
        if not upper or upper.startswith("C ") or upper.startswith("*"):
            continue
        n1, n2 = _split_card_nodes(line)
        source_cards.append(line)
        sources.append(_parse_source_line(line, n1, n2))

    # ---- 节点归类 ----
    all_cards: list[tuple[str | None, str | None]] = [
        *[(n1, n2) for n1, n2, _line in branch_cards],
        *switch_cards,
        *[(src.get("node"), None) for src in sources],
    ]
    node_ids = _collect_nodes_from_cards(all_cards)
    include_nodes = [port for inc in includes for port in inc["ports"]]
    for port in include_nodes:
        if port not in node_ids:
            node_ids.append(port)

    nodes = [
        {
            "id": node_id,
            "kind": _classify_node(node_id, include_nodes),
        }
        for node_id in node_ids
    ]

    stats = {
        "node_count": len(nodes),
        "branch_count": len(branches),
        "switch_count": len(switches),
        "source_count": len(sources),
        "include_count": len(includes),
        "param_count": len(parameters),
        "warnings": len(warnings),
    }

    return {
        "schema": "lp.atp.scene/1",
        "source_file": source_file,
        "parameters": parameters[:200],  # 防止超长参数表撑爆前端
        "includes": includes,
        "nodes": nodes,
        "branches": branches,
        "switches": switches,
        "sources": sources,
        "stats": stats,
        "warnings": warnings,
    }


def _strip_card_prefix(line: str) -> str:
    """去掉 ATP 卡行首的类型标志（-1 / 13 / 14 / 99 等），返回剩余部分。"""
    match = re.match(r"^\s*(?:-?\d{1,2})\s*", line)
    if match:
        return line[match.end():]
    return line.lstrip()


def _parse_branch_line(line: str, n1: str, n2: str | None) -> dict[str, Any]:
    """从支路卡行提取 R/L/C 值（尽力而为：取行内前 3 个浮点数）。"""
    rest = _strip_card_prefix(line)
    for node in (n1, n2):
        if node:
            rest = rest.replace(node, " ", 1)
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", rest)
    values = numbers[:3]
    branch: dict[str, Any] = {"n1": n1, "n2": n2 or "GROUND"}
    if len(values) > 0:
        branch["r"] = values[0]
    if len(values) > 1:
        branch["l"] = values[1]
    if len(values) > 2:
        branch["c"] = values[2]
    branch["raw"] = line.strip()[:80]
    return branch


def _parse_switch_line(line: str, n1: str, n2: str) -> dict[str, Any]:
    rest = _strip_card_prefix(line)
    for node in (n1, n2):
        rest = rest.replace(node, " ", 1)
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", rest)
    switch: dict[str, Any] = {"n1": n1, "n2": n2}
    # 开关卡末尾的数字是类型码（0=普通开关 2=闪络 等）；前面可能有控制量数字
    if numbers:
        switch["type"] = numbers[-1]
    control = _NODE_NAME_RE.search(rest)
    if control:
        switch["control"] = control.group(0)
    switch["raw"] = line.strip()[:80]
    return switch


def _parse_source_line(line: str, n1: str | None, n2: str | None) -> dict[str, Any]:
    node = n1 or n2 or "UNKNOWN"
    rest = _strip_card_prefix(line)
    if n1:
        rest = rest.replace(n1, " ", 1)
    numbers = re.findall(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?", rest)
    source: dict[str, Any] = {"node": node}
    if len(numbers) > 0:
        source["amplitude"] = numbers[0]
    if len(numbers) > 1:
        source["freq"] = numbers[1]
    if len(numbers) > 2:
        source["phase"] = numbers[2]
    source["raw"] = line.strip()[:80]
    return source


def _classify_node(node_id: str, include_nodes: list[str]) -> str:
    upper = node_id.upper()
    if node_id in include_nodes:
        return "include"
    if upper.startswith("SW"):
        return "switch"
    if upper.startswith("LINE") or "LINE" in upper:
        return "line"
    if upper.startswith("X") or upper.startswith("XX"):
        return "internal"
    return "other"