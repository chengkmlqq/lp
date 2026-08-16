from __future__ import annotations

from pathlib import Path

import pytest

from app.services.fault_input_discovery import (
    CATEGORY_LIGHTNING,
    CATEGORY_TRAVELING_WAVE,
    CATEGORY_WAVE,
    classify_upload_file,
    InputDiscoveryError,
    discover_one,
    discover_waveforms,
    normalize_input_files,
)


def _touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.touch()
    return path


class TestDiscoverOne:
    def test_match_single_file(self, tmp_path: Path):
        _touch(tmp_path, "1_录波提取.json")
        found = discover_one(tmp_path, "1", {".json", ".txt"}, "录波数据")
        assert found is not None
        assert found.name == "1_录波提取.json"

    def test_match_by_extension(self, tmp_path: Path):
        _touch(tmp_path, "1_录波提取.json")
        found = discover_one(tmp_path, "1", {".json"}, "录波数据")
        assert found is not None

    def test_no_match_returns_none(self, tmp_path: Path):
        _touch(tmp_path, "2_雷电定位.csv")
        found = discover_one(tmp_path, "1", {".json", ".txt"}, "录波数据")
        assert found is None

    def test_extension_mismatch_not_matched(self, tmp_path: Path):
        _touch(tmp_path, "1_录波提取.xlsx")
        found = discover_one(tmp_path, "1", {".json", ".txt"}, "录波数据")
        assert found is None

    def test_multiple_same_category_raises(self, tmp_path: Path):
        _touch(tmp_path, "1_录波提取.json")
        _touch(tmp_path, "1_录波提取2.json")
        with pytest.raises(InputDiscoveryError, match="仅保留一个"):
            discover_one(tmp_path, "1", {".json", ".txt"}, "录波数据")

    def test_subdirectory_files_ignored(self, tmp_path: Path):
        sub = tmp_path / "nested"
        sub.mkdir()
        _touch(sub, "1_录波提取.json")
        found = discover_one(tmp_path, "1", {".json", ".txt"}, "录波数据")
        assert found is None


class TestClassifyUploadFile:
    def test_numbered_prefix_requires_separator(self):
        assert classify_upload_file("1 录波故障信息 雁湖线_fault_info.xlsx") == CATEGORY_WAVE
        assert classify_upload_file("2 雷电定位输入模板.xlsx") == CATEGORY_LIGHTNING
        assert classify_upload_file("1号杆塔A相.txt") == CATEGORY_TRAVELING_WAVE


class TestDiscoverWaveforms:
    def test_collects_txt_and_json(self, tmp_path: Path):
        wave1 = _touch(tmp_path, "A相.txt")
        wave2 = _touch(tmp_path, "B相.json")
        waves = discover_waveforms(tmp_path)
        assert wave1 in waves
        assert wave2 in waves

    def test_excludes_prefix_1_2_3(self, tmp_path: Path):
        _touch(tmp_path, "1_录波提取.txt")
        _touch(tmp_path, "2_雷电定位.json")
        _touch(tmp_path, "3_线路台账.txt")
        waves = discover_waveforms(tmp_path)
        assert all("_" not in p.name for p in waves)
        assert not waves

    def test_excludes_non_txt_json(self, tmp_path: Path):
        _touch(tmp_path, "波形.csv")
        _touch(tmp_path, "波形.bin")
        assert discover_waveforms(tmp_path) == []

    def test_returns_sorted_list(self, tmp_path: Path):
        _touch(tmp_path, "b.txt")
        _touch(tmp_path, "a.txt")
        names = [p.name for p in discover_waveforms(tmp_path)]
        assert names == ["a.txt", "b.txt"]


class TestNormalizeInputFiles:
    def test_single_file_categories_pass(self, tmp_path: Path):
        wave = _touch(tmp_path, "1_录波.json")
        lightning = _touch(tmp_path, "2_雷电.csv")
        normalized = normalize_input_files(
            {CATEGORY_WAVE: [wave], CATEGORY_LIGHTNING: [lightning]}
        )
        assert normalized[CATEGORY_WAVE] == [wave]
        assert normalized[CATEGORY_LIGHTNING] == [lightning]

    def test_multiple_wave_files_raise(self, tmp_path: Path):
        w1 = _touch(tmp_path, "1_录波.json")
        w2 = _touch(tmp_path, "1_录波2.json")
        with pytest.raises(InputDiscoveryError, match="保留一个"):
            normalize_input_files({CATEGORY_WAVE: [w1, w2]})

    def test_traveling_wave_allows_multiple(self, tmp_path: Path):
        t1 = _touch(tmp_path, "A.txt")
        t2 = _touch(tmp_path, "B.txt")
        normalized = normalize_input_files({CATEGORY_TRAVELING_WAVE: [t1, t2]})
        assert len(normalized[CATEGORY_TRAVELING_WAVE]) == 2
