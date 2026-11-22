"""风电场计算 golden 对拍（LP-79）。

fixture 是桌面原始样例的**原样副本**（五个输入文件 + 原始 ``file_out.txt``），
见 ``fixtures/wind_farm_calc/manifest.json``。对拍口径：

- 输入：``file_1.txt``~``file_4.txt`` + ``P0.abc``，不做数据准备、不裁剪、不改 N；
- 引擎：原始 ``FengLiFangLei-10.exe``（MD5 见 manifest），Wine 下原样运行；
- 输出：``file_out.txt``（GBK）逐台比对经度/纬度/计算值 V/风险等级/停运建议。

两档用例：

1. ``test_golden_output_reparses_to_same_risk_and_suggestion`` —— 纯 Python，
   把原始 golden 走一遍 ``parse_file_out``，确认 LP 的风险重算与建议归一化在
   原始数据上零偏差（无需 Wine/exe，CI 常跑）；
2. ``test_golden_matches_original_file_out`` —— ``@pytest.mark.golden``，真的调起
   Wine 跑 exe。exe 或 wine 不可用时 skip，用环境变量指定：

   - ``WIND_FARM_CALC_GOLDEN_EXE``：exe 绝对路径（缺省尝试 ``wine_allowed_root/wind_farm``）；
   - ``WIND_FARM_CALC_GOLDEN_TIMEOUT``：超时秒数（默认 3600，本样例实测约 25 分钟）。

原始样例有一处已知差异：``file_1`` 的 N=50，而 ``file_2``/``file_3``/``file_4``
各有 58 行；核心 exe 只处理前 50 台。LP 的 ``preflight()`` 已放宽为「行数 ≥ N、
只校验前 N 行」（LP-82），``test_golden_fixture_passes_preflight`` 验证这批原始
文件现在可通过预检。golden 对拍用例本身仍**不经预检**直接调用 exe，保持
「输入原样、不改 N、不截断」的对拍约定。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import wind_farm_calc as calc

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "wind_farm_calc"
INPUT_DIR = FIXTURE_DIR / "inputs"
GOLDEN_PATH = FIXTURE_DIR / "file_out.txt"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))

N = int(MANIFEST["n"])
S = float(MANIFEST["s"])
VALUE_TOLERANCE = 1e-6


def _golden_bytes() -> bytes:
    return GOLDEN_PATH.read_bytes()


def _fixture_inputs() -> dict[str, bytes]:
    return {name: (INPUT_DIR / name).read_bytes() for name in calc.INPUT_FILE_NAMES}


def _resolve_engine_exe() -> Path | None:
    override = os.environ.get("WIND_FARM_CALC_GOLDEN_EXE")
    candidates = []
    if override:
        candidates.append(Path(override))
    try:
        from app.core.config import get_settings

        settings = get_settings()
        candidates.append(
            Path(settings.wine_allowed_root) / settings.wind_farm_calc_executable
        )
    except Exception:  # noqa: BLE001 - 配置不可读时只靠环境变量
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _wine_binary() -> str:
    return os.environ.get("WINE_BINARY_PATH") or shutil.which("wine") or ""


def _compare_rows(
    golden: calc.FileOutParseResult, actual: calc.FileOutParseResult
) -> list[str]:
    """逐台比对，返回差异描述（空列表表示完全一致）。"""
    diff: list[str] = []
    if len(actual.rows) != len(golden.rows):
        diff.append(f"结果行数不一致：golden={len(golden.rows)}，实际={len(actual.rows)}")
    for expected_row, actual_row in zip(golden.rows, actual.rows):
        seq = expected_row.seq
        if actual_row.seq != seq:
            diff.append(f"第 {seq} 行序号不一致：golden={seq}，实际={actual_row.seq}")
            continue
        if (actual_row.lon, actual_row.lat) != (expected_row.lon, expected_row.lat):
            diff.append(
                f"第 {seq} 行经纬度不一致：golden=({expected_row.lon}, {expected_row.lat})，"
                f"实际=({actual_row.lon}, {actual_row.lat})"
            )
        delta = abs(actual_row.value_v - expected_row.value_v)
        if delta > VALUE_TOLERANCE:
            diff.append(
                f"第 {seq} 行 V 超差：golden={expected_row.value_v:.6f}，"
                f"实际={actual_row.value_v:.6f}，差值={delta:.9f}"
            )
        if actual_row.risk_level != expected_row.risk_level:
            diff.append(
                f"第 {seq} 行风险等级不一致：golden={calc.RISK_LABELS[expected_row.risk_level]}，"
                f"实际={calc.RISK_LABELS[actual_row.risk_level]}"
            )
        if actual_row.suggestion_code != expected_row.suggestion_code:
            diff.append(
                f"第 {seq} 行停运建议不一致：golden={expected_row.suggestion_code}"
                f"({expected_row.suggestion_text})，实际={actual_row.suggestion_code}"
                f"({actual_row.suggestion_text})"
            )
    return diff


# ---------------------------------------------------------------------------
# 1) 原始 golden 的解析侧零偏差（无需 Wine）
# ---------------------------------------------------------------------------
def test_golden_output_reparses_to_same_risk_and_suggestion() -> None:
    parsed = calc.parse_file_out(_golden_bytes(), s=S, expected_n=N)
    assert len(parsed.rows) == N
    assert parsed.risk_mismatch_count == 0, "原始 golden 的风险等级与 LP 重算规则不一致"

    golden = [line.split() for line in calc.decode_file_out(_golden_bytes()).splitlines() if line.strip()]
    assert len(golden) == N
    for row, columns in zip(parsed.rows, golden):
        assert row.seq == int(columns[0])
        assert calc.parse_risk_level(columns[4]) == row.risk_level
        assert calc.classify_suggestion(columns[5]) == row.suggestion_code
        # golden 的 V 是 6 位小数，回读后不应再有换算误差
        assert float(columns[3]) == row.value_v

    # 边界样例：第 24 台 V=1.230600 落在 0.5S=1.25 以内（I 级），第 22 台为唯一 IV 级
    by_seq = {row.seq: row for row in parsed.rows}
    assert by_seq[24].risk_level == 1
    assert by_seq[22].risk_level == 4
    assert {row.risk_level for row in parsed.rows} == {1, 2, 3, 4}


def test_golden_fixture_passes_preflight() -> None:
    """原始样例 58 行 > N=50：预检通过，grid_rows 按 N 计，多余行只提示不阻断。"""
    assert MANIFEST["rows_in_file_2_3_4"] > N
    report = calc.preflight(_fixture_inputs())
    assert report.ok is True, report.errors
    assert report.params is not None and report.params.n == N
    assert report.grid_rows == N
    assert not report.errors
    assert sum(1 for c in report.checks if c.get("level") == "warning") == 3


def test_golden_fixture_matches_manifest_md5() -> None:
    import hashlib

    for rel_path, expected in MANIFEST["md5"].items():
        digest = hashlib.md5((FIXTURE_DIR / rel_path).read_bytes()).hexdigest()
        assert digest == expected, f"{rel_path} 与 manifest 记录不一致"


# ---------------------------------------------------------------------------
# 2) 真跑核心 exe 的 golden 对拍（需要 Wine + 原始 exe）
# ---------------------------------------------------------------------------
@pytest.mark.golden
def test_golden_matches_original_file_out(tmp_path: Path) -> None:
    exe = _resolve_engine_exe()
    if exe is None:
        pytest.skip(
            "未找到核心 exe：设置 WIND_FARM_CALC_GOLDEN_EXE 或部署 wine_allowed_root/wind_farm/FengLiFangLei-10.exe"
        )
    wine = _wine_binary()
    if not wine:
        pytest.skip("未找到 wine：设置 WINE_BINARY_PATH 或安装 wine")

    workdir = tmp_path / "run"
    workdir.mkdir()
    for name, content in _fixture_inputs().items():
        (workdir / name).write_bytes(content)
    shutil.copy2(exe, workdir / exe.name)

    env = {**os.environ}
    env.setdefault("WINEDLLOVERRIDES", "winemenubuilder.exe=d")
    env.setdefault("DISPLAY", "")
    timeout = int(os.environ.get("WIND_FARM_CALC_GOLDEN_TIMEOUT", "3600"))

    completed = subprocess.run(
        [wine, exe.name],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=timeout,
        start_new_session=True,
    )
    assert completed.returncode == 0, (
        "核心程序退出码非 0：\n"
        + completed.stdout.decode("utf-8", errors="replace")[-2000:]
    )

    output_path = workdir / "file_out.txt"
    assert output_path.is_file() and output_path.stat().st_size > 0, "核心程序未产出 file_out.txt"

    golden = calc.parse_file_out(_golden_bytes(), s=S, expected_n=N)
    actual = calc.parse_file_out(output_path.read_bytes(), s=S, expected_n=N)

    diff = _compare_rows(golden, actual)
    assert not diff, "核心 exe 输出与原始 golden 不一致：\n" + "\n".join(diff[:50])
