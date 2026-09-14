"""绕击跳闸率（EGM 电气几何模型）计算——对齐 C# rjtzl_AC_GroundAngle2。

C# 流程（ComputeLightningProtection.cs rjtzl_AC_GroundAngle2 / rjtzl_egm*.exe）：
  1. turn=1：写 param_main_Ic.txt（第 2 行=地面倾角1）+ param_main_cic.txt(几何)
     → 写 name_egm<N>.txt（三文件名清单）→ 跑 rjtzl_egm<N>.exe → 读 result_main.txt
  2. turn=2：第 2 行=-1*地面倾角2 → 再跑一次
  3. 按 rjEGM_Type 取分量求和：
       type1(egm1 单回)：turn1 取 [2][3]，turn2 取 [4]
       type2(egm2 双回)：turn1 取 [2][4][6]，turn2 取 [3][5][7]
       type3(egm3 四回)：turn1 取 index{2,3,4,8,9,10}，turn2 取 {5,6,7,11,12,13}
  4. 塔型修正：鼓型(guxing/guxingd) ÷2；四回(sihui) ÷4

文件格式（16 参数 = 双回 egm2 的 cic）：
  左避雷中距, 右避雷中距, 上相左, 右, 中相左, 右, 下相左, 右,
  避雷线高, 避雷线高, 上相高, 上相高, 中相高, 中相高, 下相高, 下相高
Ic 文件 7 行：Ng, 地面倾角, 雷电流幅值a, 雷电流幅值b, Ic_left, Ic_right, 建弧率e

⚠️ 已用 C# 0913 运行留下的 08_* 中间文件逐位验证：
   cic=-12.4,12.4,-12,12,-12,12,-12,12,73.5,73.5,65.5,65.5,53,53,42,42
   Ic=2.8,0,25.109,3.62,22,22,1  →  result=0.614380 0.614416 0.142943 ...
   (0.142943+0.232238+0.032163 + 0.142820+0.230866+0.032104)/2 = 0.406567 ✓
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 电路数 → rjEGM_Type（C# rjEGM_Type：1 单回 / 2 双回 / 3 四回）
_CIRCUITS_TO_EGM_TYPE = {1: 1, 2: 2, 4: 3}

# rjEGM_Type → 结果分量下标（C# rjtzl_AC_GroundAngle2）
_INDEX_TURN1 = {1: (2, 3), 2: (2, 4, 6), 3: (2, 3, 4, 8, 9, 10)}
_INDEX_TURN2 = {1: (4,), 2: (3, 5, 7), 3: (5, 6, 7, 11, 12, 13)}


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _fmt(value: float) -> str:
    """C# double.ToString() 风格（尽量短，去尾零）。"""
    text = repr(float(value))
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _insulator_offset_m(profile: dict[str, Any]) -> float:
    """直线塔：相高需减去绝缘子串长；耐张塔不减（对齐 C#）。"""
    kind = str(profile.get("structure_kind") or "")
    if "直线" in kind:
        length_mm = _num(profile.get("insulator_length_m"))
        if length_mm:
            return length_mm / 1000.0
    return 0.0


def _circuit_geometry(base_tower: dict[str, Any]) -> list[dict[str, Any]]:
    """取有效回路的几何（按 I/II/III/IV 顺序）。"""
    raw = base_tower.get("circuit_geometry_json") or {}
    out: list[dict[str, Any]] = []
    for key in ("I", "II", "III", "IV"):
        item = raw.get(key) or {}
        spacing = item.get("phase_spacing_m") or {}
        height = item.get("phase_height_m") or {}
        if all(_num(spacing.get(k)) is not None for k in ("upper", "middle", "lower")) and all(
            _num(height.get(k)) is not None for k in ("upper", "middle", "lower")
        ):
            out.append({"spacing": spacing, "height": height})
    return out


def _lightning_wire(profile: dict[str, Any]) -> dict[str, float | None]:
    lw = profile.get("lightning_wire") or {}
    if not lw:
        for key in ("extra_profile_json", "geometry_layers_json"):
            layer = profile.get(key) or {}
            if isinstance(layer, dict) and layer.get("lightning_wire"):
                lw = layer["lightning_wire"]
                break
    return {
        "left": _num(lw.get("left_mid_distance_m")),
        "right": _num(lw.get("right_mid_distance_m")),
        "height": _num(lw.get("height_m")),
    }


def build_cic(*, base_tower: dict[str, Any], profile: dict[str, Any], egm_type: int) -> str:
    """组装 param_main_cic.txt（几何注入文件）。"""
    circuits = _circuit_geometry(base_tower)
    if not circuits:
        raise ValueError("缺少回路几何（circuit_geometry_json），无法计算绕击跳闸率")
    lw = _lightning_wire(profile)
    missing = [k for k in ("left", "right", "height") if lw[k] is None]
    if missing:
        raise ValueError(f"缺少避雷线几何 {missing}，无法计算绕击跳闸率")

    off = _insulator_offset_m(profile)
    phase = circuits[0]
    up_h = float(_num(phase["height"]["upper"]) or 0.0) - off
    mid_h = float(_num(phase["height"]["middle"]) or 0.0) - off
    low_h = float(_num(phase["height"]["lower"]) or 0.0) - off
    up_x = float(_num(phase["spacing"]["upper"]) or 0.0)
    mid_x = float(_num(phase["spacing"]["middle"]) or 0.0)
    low_x = float(_num(phase["spacing"]["lower"]) or 0.0)
    sh_h = float(lw["height"] or 0.0)

    if egm_type == 1:
        # 单回 egm1（10 参数）：左/右避雷中距, 左相中距, 中相中距, 右相中距,
        #                        避雷线高×2, 左相高, 中相高, 右相高
        rows = [
            -abs(lw["left"] or 0.0), abs(lw["right"] or 0.0),
            -up_x, mid_x, low_x,
            sh_h, sh_h, up_h, mid_h, low_h,
        ]
    else:
        # 双回/四回 egm2/egm3（每回 16 参数）：避雷线左右, 上/中/下相左右, 高度成对
        rows = [
            -abs(lw["left"] or 0.0), abs(lw["right"] or 0.0),
            -up_x, up_x, -mid_x, mid_x, -low_x, low_x,
            sh_h, sh_h, up_h, up_h, mid_h, mid_h, low_h, low_h,
        ]
    return "\n".join(_fmt(v) for v in rows) + "\n"


def build_ic(
    *,
    base_tower: dict[str, Any],
    profile: dict[str, Any],
    voltage_kv: float | None,
    slope_deg: float,
    raoji_withstand_ka: float,
) -> str:
    """组装 param_main_Ic.txt（耐雷/分布参数注入文件，7 行）。"""
    density = _num(base_tower.get("lightning_density"))
    if density is None:
        raise ValueError("缺少地闪密度，无法计算绕击跳闸率")
    params = base_tower.get("line_lightning_param_json") or {}
    a = _num(profile.get("current_a")) or _num(params.get("雷电流幅值a"))
    b = _num(profile.get("current_b")) or _num(params.get("雷电流幅值b"))
    if not a or not b:
        raise ValueError("缺少雷电流幅值 a/b，无法计算绕击跳闸率")
    # 建弧率 e：110→0.85，220→0.918，≥500→1（对齐 C#）
    v = voltage_kv or 500
    e = 0.85 if v == 110 else (0.918 if v == 220 else 1)
    ic = int(raoji_withstand_ka)  # C#: (int)mRaojiCurrent
    rows = [density, slope_deg, a, b, ic, ic, e]
    return "\n".join(_fmt(x) for x in rows) + "\n"


def egm_type_for_circuits(circuit_count: int) -> int:
    return _CIRCUITS_TO_EGM_TYPE.get(circuit_count, 2)


def _parse_result(text: str) -> list[float]:
    out: list[float] = []
    for token in text.replace("\r", " ").replace("\n", " ").split():
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def _extract(egm_type: int, values: list[float], *, turn: int) -> float:
    """取该轮（turn=1/2）对应的分量求和（对齐 C# indexArrayTurn1/Turn2）。"""
    indexes = _INDEX_TURN1.get(egm_type, ()) if turn == 1 else _INDEX_TURN2.get(egm_type, ())
    total = 0.0
    for idx in indexes:
        if idx < len(values):
            total += values[idx]
    return total


def _tower_divisor(tower_type: str) -> float:
    """C# 塔型修正：四回 ÷4；鼓型/鼓型d ÷2。"""
    code = "".join(ch for ch in (tower_type or "").lower() if ch.isalnum())
    if "guxing" in code:
        return 2.0
    if "sihui" in code:
        return 4.0
    return 1.0


def _run_egm(*, exe: Path, work_dir: Path, name_file: str, env: dict[str, str], timeout: int) -> list[float]:
    local_exe = work_dir / exe.name
    if not local_exe.exists():
        shutil.copy2(exe, local_exe)
    # EGM（MATLAB 编译程序）单次约 113 秒且期间无输出 → 带心跳，避免前端看起来卡死。
    from ..core.subprocess_heartbeat import run_with_heartbeat

    proc = run_with_heartbeat(
        ["wine", local_exe.name],
        cwd=str(work_dir),
        env=env,
        timeout=timeout,
        label=f"{exe.name} 绕击跳闸率（EGM）",
    )
    result_path = work_dir / "result_main.txt"
    if not result_path.exists():
        raise RuntimeError(
            f"EGM 程序未产出 result_main.txt（绕击跳闸率计算失败）："
            f"{exe.name} rc={proc.returncode} stderr={proc.stderr[-300:]}"
        )
    return _parse_result(result_path.read_text(encoding="gbk", errors="replace"))


def compute_shielding_trip_rate(
    *,
    atp_root: Path,
    voltage_kv: float | None,
    base_tower: dict[str, Any],
    profile: dict[str, Any],
    tower_type: str,
    raoji_withstand_ka: float,
    env: dict[str, str],
    timeout: int = 600,
) -> tuple[float, float]:
    """按 C# EGM 流程计算绕击跳闸率。返回 (跳闸率, alpha?)。"""
    circuits = _circuit_geometry(base_tower)
    circuit_count = max(len(circuits), 1)
    egm_type = egm_type_for_circuits(circuit_count)
    voltage = int(voltage_kv or 0)
    exe = atp_root / str(voltage) / f"{voltage}egm" / f"rjtzl_egm{egm_type}.exe"
    if not exe.exists():
        raise FileNotFoundError(f"缺少 EGM 程序：{exe}")

    cic_text = build_cic(base_tower=base_tower, profile=profile, egm_type=egm_type)
    density = _num(base_tower.get("lightning_density"))
    slope1 = _num(base_tower.get("slope_1")) or 0.0
    slope2 = _num(base_tower.get("slope_2")) or 0.0

    total = 0.0
    with tempfile.TemporaryDirectory(prefix="egm_rj_") as tmp:
        work_dir = Path(tmp)
        (work_dir / "param_main_cic.txt").write_text(cic_text, encoding="gbk", errors="replace")
        (work_dir / "name_egm{}.txt".format(egm_type)).write_text(
            "param_main_cic.txt\nparam_main_Ic.txt\nresult_main.txt\n", encoding="gbk", errors="replace"
        )
        # 两轮输入（倾角1 / -倾角2）相同时复用同一次 EGM 运行结果——
        # EGM 为 MATLAB 编译程序，单次约 113s，能省一半时间。
        _run_cache: dict[float, list[float]] = {}
        for turn, slope in ((1, slope1), (2, -slope2)):
            _key = round(float(slope), 9)
            if _key in _run_cache:
                total += _extract(egm_type, _run_cache[_key], turn=turn)
                continue
            ic_text = build_ic(
                base_tower=base_tower,
                profile=profile,
                voltage_kv=voltage_kv,
                slope_deg=slope,
                raoji_withstand_ka=raoji_withstand_ka,
            )
            (work_dir / "param_main_Ic.txt").write_text(ic_text, encoding="gbk", errors="replace")
            (work_dir / "result_main.txt").unlink(missing_ok=True)
            values = _run_egm(
                exe=exe, work_dir=work_dir, name_file=f"name_egm{egm_type}.txt", env=env, timeout=timeout
            )
            _run_cache[_key] = values
            total += _extract(egm_type, values, turn=turn)

    divisor = _tower_divisor(tower_type)
    trip_rate = total / divisor if divisor else total
    logger.info(
        "[EGM] 绕击跳闸率：egm%d 电压=%s 回路数=%d Ng=%s Ic=%s 合计=%.6f ÷%.0f = %.6f",
        egm_type, voltage, circuit_count, density, raoji_withstand_ka, total, divisor, trip_rate,
    )
    return round(trip_rate, 6), 0.0
