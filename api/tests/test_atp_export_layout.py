from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.atp_export_layout import atp_tree_relative_dir, safe_member_path, tower_type_directory


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
