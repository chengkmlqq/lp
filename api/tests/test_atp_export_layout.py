from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.atp_export_layout import (
    ATP_ROOT_DEFAULT,
    atp_tree_relative_dir,
    rewrite_atp_include_paths,
    rewrite_atp_model_bytes,
    safe_member_path,
    target_include_path,
    tower_type_directory,
    voltage_directory,
)


def _asset(voltage="500", tower="ganzi", scene="fanji", measure="noM", shield="with"):
    return SimpleNamespace(
        voltage_level=voltage,
        tower_type=tower,
        scene_type=scene,
        arrester_config=measure,
        shield_wire=shield,
    )


def test_115_and_230_keep_their_own_directories():
    assert atp_tree_relative_dir(_asset(voltage="115")) == "115/ganzi/fanji/noM"
    assert atp_tree_relative_dir(_asset(voltage="230")) == "230/ganzi/fanji/noM"
    assert atp_tree_relative_dir(_asset(voltage="110")) == "110/ganzi/fanji/noM"


def test_shield_wire_suffixes_match_atp_tree():
    assert tower_type_directory("guxing", "single") == "guxingd"
    assert tower_type_directory("ganzi", "none") == "ganzino"
    assert tower_type_directory("ganzi", "with") == "ganzi"
    assert tower_type_directory("ganzino", "none") == "ganzino"


def test_shuzhi_no_m_keeps_separate_measure_directory():
    assert atp_tree_relative_dir(_asset(measure="shuzhi-noM")) == "500/ganzi/fanji/shuzhi-noM"
    assert atp_tree_relative_dir(_asset(measure="noM")) == "500/ganzi/fanji/noM"


def test_missing_dimension_is_rejected():
    with pytest.raises(ValueError, match="arrester_config"):
        atp_tree_relative_dir(_asset(measure=None))


def test_safe_member_path_rejects_traversal():
    assert safe_member_path("500/ganzi/fanji/noM", "work.atp") == "500/ganzi/fanji/noM/work.atp"
    with pytest.raises(ValueError, match="非法"):
        safe_member_path("500/ganzi/fanji/noM", "../work.atp")


def test_voltage_unit_suffix_is_stripped_but_115_230_kept():
    assert voltage_directory("500kV") == "500"
    assert voltage_directory("115kV") == "115"
    assert voltage_directory(230) == "230"
    assert atp_tree_relative_dir(_asset(voltage="500kV")) == "500/ganzi/fanji/noM"


# ── $INCLUDE / $INSERT 路径重写（导出给 C#）─────────────────────


def test_include_path_rewritten_to_csharp_root():
    line = "$INCLUDE, C:\\ATP6\\ATP-EMTP_6_0免安装版\\ATP\\atpdraw\\Atp\\short.lib, X0129A, X0129B, X0129C\n"
    result = rewrite_atp_include_paths(line, "110/ganzi/fanji/M123")
    assert result["changed"] == 1
    assert result["text"] == (
        "$INCLUDE,D:\\ATP\\110\\ganzi\\fanji\\M123\\short.lib, X0129A, X0129B, X0129C\n"
    )
    assert result["warnings"] == []


def test_include_node_parameters_and_trailing_note_are_preserved():
    line = "$INCLUDE, C:\\ATP60work\\batch\\110_guxing_fanji\\dahao.lib $$\r\n"
    result = rewrite_atp_include_paths(line, "110/guxing/fanji/noM")
    assert result["text"] == "$INCLUDE,D:\\ATP\\110\\guxing\\fanji\\noM\\dahao.lib $$\r\n"
    assert result["text"].endswith("\r\n")


def test_insert_pch_path_rewritten():
    line = "$INSERT, C:\\ATP\\work\\results\\short1.pch\n"
    result = rewrite_atp_include_paths(line, "110/ganzino/fanji/noM")
    assert result["text"] == "$INSERT,D:\\ATP\\110\\ganzino\\fanji\\noM\\short1.pch\n"


def test_rewrite_is_idempotent_when_already_pointing_at_target():
    line = "$INCLUDE, D:\\ATP\\500\\ganzi\\fanji\\noM\\short.lib, X0129A\n"
    result = rewrite_atp_include_paths(line, "500/ganzi/fanji/noM")
    assert result["changed"] == 0
    assert result["text"] == line


def test_relative_include_is_also_normalized():
    line = "$INCLUDE, short.lib, X0129A\n"
    result = rewrite_atp_include_paths(line, "500/ganzi/fanji/noM")
    assert result["text"] == "$INCLUDE,D:\\ATP\\500\\ganzi\\fanji\\noM\\short.lib, X0129A\n"


def test_unrelated_lines_are_untouched():
    text = "C 注释行\n$PARAMETER\n  ZRE01_VRE___RELE01 = 300\n"
    result = rewrite_atp_include_paths(text, "500/ganzi/fanji/noM")
    assert result["changed"] == 0
    assert result["text"] == text


def test_long_target_path_warns_about_80_columns():
    line = "$INCLUDE, C:\\ATP6\\short.lib, X0129A, X0129B, X0129C $$\n"
    result = rewrite_atp_include_paths(line, "1000/sihuita/raoji1/shuzhi-noM")
    assert result["changed"] == 1
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["columns"] > 80
    assert "KILL=79" in result["warnings"][0]["reason"]


def test_target_include_path_uses_default_csharp_root():
    assert ATP_ROOT_DEFAULT == "D:\\ATP"
    assert (
        target_include_path("short.lib", "500/ganzi/fanji/noM")
        == "D:\\ATP\\500\\ganzi\\fanji\\noM\\short.lib"
    )


def test_rewrite_model_bytes_keeps_gbk_text_and_crlf():
    original = (
        "C 中文注释\r\n"
        "$INCLUDE, C:\\ATP6\\short.lib, X0129A\r\n"
        "$PARAMETER\r\n"
    ).encode("gbk")
    content, diag = rewrite_atp_model_bytes(original, "110/ganzi/fanji/M123")
    assert diag["changed"] == 1
    decoded = content.decode("gbk")
    assert "C 中文注释\r\n" in decoded
    assert "$INCLUDE,D:\\ATP\\110\\ganzi\\fanji\\M123\\short.lib, X0129A\r\n" in decoded
