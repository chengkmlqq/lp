from __future__ import annotations

from pathlib import Path

import pytest

from app.services.atp_topology_parser import (
    AtpNode,
    parse_atp_topology,
    parse_atp_topology_from_bytes,
    decode_atp_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FANJI_TEMPLATE = REPO_ROOT / "deploy" / "dev-deploy" / "data" / "app" / "wine" / "ATP" / "templates" / "fanji" / "work.atp"
RAOJI1_TEMPLATE = REPO_ROOT / "deploy" / "dev-deploy" / "data" / "app" / "wine" / "ATP" / "templates" / "raoji1" / "work.atp"


def test_decode_gbk_template() -> None:
    """真实模板为 GBK 编码，应能被自动解码。"""
    raw = FANJI_TEMPLATE.read_bytes()
    text = decode_atp_bytes(raw)
    assert "RER001=15." in text
    assert "REIGAN____=65.83" in text


def test_parse_parameters_from_real_fanji_template() -> None:
    """解析真实 fanji 模板，断言关键参数被正确提取。"""
    raw = FANJI_TEMPLATE.read_bytes()
    topology = parse_atp_topology_from_bytes(raw)
    params = topology.parameters
    assert params["RER001"] == pytest.approx(15.0)
    assert params["RELENS____"] == pytest.approx(1.31)
    assert params["REIGAN____"] == pytest.approx(65.83)
    assert params["REHC1_____"] == pytest.approx(19.35)
    # 尾部下划线数量差异的键也能归一化匹配
    assert params.get("REHG______") == pytest.approx(28.8)


def test_parse_topology_from_real_fanji_template() -> None:
    """解析真实 fanji 模板，断言节点数 ≥ 7、拓扑结构正确。"""
    raw = FANJI_TEMPLATE.read_bytes()
    topology = parse_atp_topology_from_bytes(raw)
    assert len(topology.nodes) >= 7
    assert len(topology.edges) >= 8

    node_types = {node.node_type for node in topology.nodes}
    assert {"ground", "resistor", "tower_body", "insulator", "source"} <= node_types
    assert {"tower_arm", "line"} <= node_types

    # 主链路：大地 → 接地电阻 → 塔身 → 绝缘子 → 雷电流源
    edge_pairs = {(edge.source, edge.target) for edge in topology.edges}
    assert ("gnd", "rg") in edge_pairs
    assert ("rg", "tower") in edge_pairs
    assert ("tower", "ins") in edge_pairs
    assert ("ins", "source") in edge_pairs
    # 塔身分接三相横担
    for arm in ("arm_a", "arm_b", "arm_c"):
        assert ("tower", arm) in edge_pairs


def test_parse_topology_from_raoji1_template() -> None:
    """raoji1 模板共享同一参数命名规则，应得到同样的拓扑形状。"""
    raw = RAOJI1_TEMPLATE.read_bytes()
    topology = parse_atp_topology_from_bytes(raw)
    assert len(topology.nodes) >= 7
    assert topology.parameters["REIGAN____"] == pytest.approx(4.07)
    node_ids = {node.id for node in topology.nodes}
    assert {"gnd", "rg", "tower", "ins", "source"} <= node_ids


def test_encoding_compatibility() -> None:
    """utf-8 / gbk / latin-1 三种编码的 .atp 均可解析。"""
    raw = FANJI_TEMPLATE.read_bytes()
    text = decode_atp_bytes(raw)

    # gbk 原文
    gbk_topology = parse_atp_topology_from_bytes(raw)
    # utf-8 变体（去掉中文注释避免 latin-1 编码失败）
    ascii_lines = [line for line in text.splitlines() if not line.strip().startswith("C")]
    ascii_text = "\n".join(ascii_lines)
    utf8_topology = parse_atp_topology_from_bytes(ascii_text.encode("utf-8"))
    latin1_topology = parse_atp_topology_from_bytes(ascii_text.encode("latin-1"))

    for topology in (gbk_topology, utf8_topology, latin1_topology):
        assert len(topology.nodes) >= 7
        assert topology.parameters["RER001"] == pytest.approx(15.0)


def test_parse_atp_topology_from_text() -> None:
    """从纯文本解析，应跳过参数块外的内容。"""
    content = "\n".join(
        [
            "BEGIN NEW DATA CASE",
            "C 测试注释",
            "$PARAMETER",
            "RER001=15.",
            "REIGAN____=65.83",
            "REHG______=28.8",
            "BLANK $PARAMETER",
            "/TACS",
            "C 块外不解析",
        ]
    )
    topology = parse_atp_topology(content)
    assert topology.parameters["RER001"] == pytest.approx(15.0)
    assert "RER001" in topology.parameters
    assert len(topology.nodes) >= 5


def test_node_params_semantics() -> None:
    """语义节点携带 value/unit/desc 信息，供前端详情面板展示。"""
    raw = FANJI_TEMPLATE.read_bytes()
    topology = parse_atp_topology_from_bytes(raw)
    node_by_id = {node.id: node for node in topology.nodes}
    rg = node_by_id["rg"]
    assert rg.node_type == "resistor"
    assert rg.params["value"] == pytest.approx(15.0)
    assert rg.params["unit"] == "Ω"
    source = node_by_id["source"]
    assert source.params["desc"] == "雷电流幅值"


def test_parse_returns_atpnode_instances() -> None:
    """nodes 元素是 AtpNode dataclass 实例。"""
    topology = parse_atp_topology("$PARAMETER\nRER001=15.\nBLANK $PARAMETER")
    assert all(isinstance(node, AtpNode) for node in topology.nodes)
