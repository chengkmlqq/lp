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

from ..core.config import get_settings
from . import egm_native

logger = logging.getLogger(__name__)

# ── C# 权威：塔型 → EGM 程序（rjEGM_Type）映射（2026-09-15 按 tzl_model.txt + MyParamClass.cs 实现）
# 塔型名数组顺序照抄 MyParamClass.cs:121-137 mNames_GanTa；程序/类型/电压支持集照抄
# LP/LP/bin/Debug/SettingTxtFile/tzl_model.txt（行格式：电压#..#exe名#..#rjEGM_Type#类型）：
#   shangzi/menxing/ganzi/maotou/jiubei → rjtzl_egm1.exe（type 1，单回 5 圆）
#   guxing/guxingd                       → rjtzl_egm2.exe（type 2，双回 8 圆）
#   sihuita                              → rjtzl_egm3.exe（type 3，四回 14 圆）
#   ky                                   → rjtzl_egm4.exe（type 4，直流跨越）
#   nz                                   → rjtzl_egmDC.exe（type 5，直流耐张）
#   zj/zx/zxj                            → rjtzl_egmDC.exe（type 6，直流转角/直线）
#   zhiliu/vzhiliu                       → rjtzl_egm_zhiliu.exe（type 6，直流）
_TOWER_NAMES_C_ORDER: tuple[str, ...] = (
    "maotou", "jiubei", "menxing", "ganzi", "guxing", "guxingd", "shangzi",
    "sihuita", "zj", "zx", "zxj", "ky", "nz", "zhiliu", "vzhiliu",
)

# 塔型名 → (rjEGM_Type, exe 名, 期望回路数, 是否直流/特型)
_TOWER_TO_EGM: dict[str, tuple[int, str, int | None, bool]] = {
    "maotou": (1, "rjtzl_egm1.exe", 1, False),
    "jiubei": (1, "rjtzl_egm1.exe", 1, False),
    "menxing": (1, "rjtzl_egm1.exe", 1, False),
    "ganzi": (1, "rjtzl_egm1.exe", 1, False),
    "shangzi": (1, "rjtzl_egm1.exe", 1, False),
    "guxing": (2, "rjtzl_egm2.exe", 2, False),
    "guxingd": (2, "rjtzl_egm2.exe", 2, False),
    "sihuita": (3, "rjtzl_egm3.exe", 4, False),
    "ky": (4, "rjtzl_egm4.exe", None, True),
    "nz": (5, "rjtzl_egmDC.exe", None, True),
    "zj": (6, "rjtzl_egmDC.exe", None, True),
    "zx": (6, "rjtzl_egmDC.exe", None, True),
    "zxj": (6, "rjtzl_egmDC.exe", None, True),
    "zhiliu": (6, "rjtzl_egm_zhiliu.exe", None, True),
    "vzhiliu": (6, "rjtzl_egm_zhiliu.exe", None, True),
}

# 塔型 → tzl_model.txt 里配置了 EGM 行的电压集合（C# 只在这些电压下跑该塔型的 EGM）
_TOWER_EGM_VOLTAGES: dict[str, set[int]] = {
    "maotou": {35, 66, 110, 220, 330, 500, 750, 1000},
    "jiubei": {35, 66, 110, 220, 330, 500, 750, 1000},
    "menxing": {110, 220, 500, 1000},
    "ganzi": {35, 66, 110, 220, 330, 500, 750, 1000},
    "shangzi": {35, 66, 110, 220, 330, 500, 750, 1000},
    "guxing": {35, 66, 110, 220, 330, 500, 750, 1000},
    "guxingd": {35, 66, 110, 220, 330, 500, 750, 1000},
    "sihuita": {35, 110, 220, 500},
    "ky": {500, 800},
    "nz": {500, 800},
    "zj": {500, 800},
    "zx": {500, 800},
    "zxj": {500, 800},
    "zhiliu": {500, 800},
    "vzhiliu": {500, 800},
}

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


def _insulator_length_m(profile: dict[str, Any]) -> float:
    """绝缘子串长（米）。四回塔 C# 无条件减（不分直线/耐张，见 ComputeLightningProtection.cs case 3）。"""
    length_mm = _num(profile.get("insulator_length_m"))
    return (length_mm or 0.0) / 1000.0


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
    """组装 param_main_cic.txt（几何注入文件）。

    对齐 C# `ComputeLightningProtection.cs:3054-3140`（switch rjEGM_Type）：
      case 1（单回 egm1）：10 个值 = 5 个圆的 (x, y)
      case 2（双回 egm2）：16 个值 = 8 个圆；相中距按「上/中/下」成对（左负右正）；
                           相高按 直线→减绝缘子串长、耐张/其它→不减
      case 3（四回 egm3）：28 个值 = 14 个圆；相中距按**回路**分组（每回 上/中/下，
                           回路 I/III 取负、II/IV 取正）；相高**一律减绝缘子串长**（不分直线耐张）
    文件格式：前 n_circle 个值是各圆 x，后 n_circle 个值是各圆 y（exe 按 2×n_circle 读）。
    """
    circuits = _circuit_geometry(base_tower)
    if not circuits:
        raise ValueError("缺少回路几何（circuit_geometry_json），无法计算绕击跳闸率")
    lw = _lightning_wire(profile)
    missing = [k for k in ("left", "right", "height") if lw[k] is None]
    if missing:
        raise ValueError(f"缺少避雷线几何 {missing}，无法计算绕击跳闸率")

    off = _insulator_offset_m(profile)
    sh_h = float(lw["height"] or 0.0)

    if egm_type == 1:
        # 单回 egm1（10 参数）：左/右避雷中距, 左相中距, 中相中距, 右相中距,
        #                        避雷线高×2, 左相高, 中相高, 右相高
        phase = circuits[0]
        up_h = float(_num(phase["height"]["upper"]) or 0.0) - off
        mid_h = float(_num(phase["height"]["middle"]) or 0.0) - off
        low_h = float(_num(phase["height"]["lower"]) or 0.0) - off
        up_x = float(_num(phase["spacing"]["upper"]) or 0.0)
        mid_x = float(_num(phase["spacing"]["middle"]) or 0.0)
        low_x = float(_num(phase["spacing"]["lower"]) or 0.0)
        rows = [
            -abs(lw["left"] or 0.0), abs(lw["right"] or 0.0),
            -up_x, mid_x, low_x,
            sh_h, sh_h, up_h, mid_h, low_h,
        ]
    elif egm_type == 2:
        # 双回/四回 egm2/egm3（每回 16 参数）：避雷线左右, 上/中/下相左右, 高度成对
        phase = circuits[0]
        up_h = float(_num(phase["height"]["upper"]) or 0.0) - off
        mid_h = float(_num(phase["height"]["middle"]) or 0.0) - off
        low_h = float(_num(phase["height"]["lower"]) or 0.0) - off
        up_x = float(_num(phase["spacing"]["upper"]) or 0.0)
        mid_x = float(_num(phase["spacing"]["middle"]) or 0.0)
        low_x = float(_num(phase["spacing"]["lower"]) or 0.0)
        rows = [
            -abs(lw["left"] or 0.0), abs(lw["right"] or 0.0),
            -up_x, up_x, -mid_x, mid_x, -low_x, low_x,
            sh_h, sh_h, up_h, up_h, mid_h, mid_h, low_h, low_h,
        ]
    elif egm_type == 3:
        # 四回 egm3（28 参数 = 14 圆）：2 避雷线 + 4 回×(上/中/下)
        if len(circuits) < 4:
            raise ValueError(
                f"四回塔（egm3）需要 4 个回路的几何，实际只解析到 {len(circuits)} 个"
                "（circuit_geometry_json 的 I/II/III/IV 需齐全）"
            )
        off4 = _insulator_length_m(profile)      # 四回：无条件减绝缘子串长
        xs: list[float] = [-abs(lw["left"] or 0.0), abs(lw["right"] or 0.0)]
        heights: list[float] = [sh_h, sh_h]
        for idx, circuit in enumerate(circuits[:4]):
            sign = -1.0 if idx % 2 == 0 else 1.0     # 回路 I/III 取负、II/IV 取正
            for key in ("upper", "middle", "lower"):
                xs.append(sign * abs(float(_num(circuit["spacing"][key]) or 0.0)))
            for key in ("upper", "middle", "lower"):
                heights.append(float(_num(circuit["height"][key]) or 0.0) - off4)
        rows = xs + heights
    else:
        raise ValueError(f"不支持的 egm_type={egm_type}（只实现 1/2/3；egm4/egm5/直流未移植）")
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


def parse_tower_name(tower_type: str) -> str | None:
    """按 C# 后缀规则从模型串解析塔型名（MyParamClass.cs:2831-2841）。

    C# 匹配五种后缀模式：`0<名>` / `5<名>` / `66<名>` / `:<名>500` / `:<名>800`，
    按 mNames_GanTa 顺序逐个试；全部失败返回 None（对应 C# mIndexOfGanTaName=-1）。
    例：s500guxing → guxing（结尾 "0guxing"）；d500shangzi → shangzi。
    """
    s = (tower_type or "").strip()
    for name in _TOWER_NAMES_C_ORDER:
        if (s.endswith("0" + name) or s.endswith("5" + name) or s.endswith("66" + name)
                or s.endswith(":" + name + "500") or s.endswith(":" + name + "800")):
            return name
    return None


def _parse_tower_name_loose(tower_type: str) -> str | None:
    """宽松兜底：模型串里出现塔型名子串时取最长命中（guxingd 优先于 guxing）。

    仅当 C# 严格后缀规则解析失败时用（如纯 "guxing"/"guxingd" 这类 Web 塔型编码）；
    多个等长命中（真歧义）返回 None → 上层抛错，不做猜测。
    """
    s = (tower_type or "").lower()
    hits = [name for name in _TOWER_NAMES_C_ORDER if name in s]
    if not hits:
        return None
    best = max(hits, key=len)
    if sum(1 for h in hits if len(h) == len(best)) > 1:
        return None
    return best


def egm_type_for_tower(tower_type: str, circuit_count: int, voltage_kv: float | None = None) -> int:
    """完全对齐 C#：按塔型选 EGM 程序（rjEGM_Type）+ 一致性校验，不符即抛错。

    校验顺序（任一不过即抛，禁止静默降级 / 禁止按回路数猜测程序）：
      1. 塔型名解析失败 → ValueError（C# 同样因 mIndexOfGanTaName=-1 拒绝该塔）
      2. 直流/特型塔型（egm4/egmDC/egm_zhiliu，native 未移植）→ NotImplementedError
      3. 电压不在该塔型 tzl_model 配置集 → ValueError（C# 该电压下无 EGM 行）
      4. 几何回路数 ≠ 塔型期望回路数 → ValueError（信息含塔型/期望/实际）
    """
    name = parse_tower_name(tower_type)
    if name is None:
        name = _parse_tower_name_loose(tower_type)
    if name is None:
        raise ValueError(
            f"无法从塔型「{tower_type or '(空)'}」解析出 C# 塔型名（15 种："
            + "/".join(_TOWER_NAMES_C_ORDER)
            + "），无法确定 EGM 程序（禁止按回路数猜测）"
        )
    egm_type, exe, expected_circuits, is_dc = _TOWER_TO_EGM[name]
    if is_dc or egm_type not in (1, 2, 3):
        raise NotImplementedError(
            f"塔型 {name}（模型串「{tower_type}」）对应 {exe}（rjEGM_Type={egm_type}，"
            "直流/特型塔），EGM 原生引擎尚未移植该程序"
        )
    if voltage_kv:
        v = int(voltage_kv)
        if v not in _TOWER_EGM_VOLTAGES[name]:
            raise ValueError(
                f"C# tzl_model 未配置 {v}kV × 塔型 {name} 的 EGM 程序"
                f"（该塔型仅支持 {sorted(_TOWER_EGM_VOLTAGES[name])}kV），拒绝计算"
            )
    if expected_circuits is not None and circuit_count != expected_circuits:
        raise ValueError(
            f"塔型 {name}（模型串「{tower_type}」）的 EGM 程序 {exe} 期望 {expected_circuits} 回路，"
            f"但塔几何实际只有 {circuit_count} 回路 —— 塔型与几何不一致，拒绝静默计算"
        )
    return egm_type


def _parse_numbers(text: str) -> list[float]:
    """从 build_cic/build_ic 生成的文本里取数值（顺序即文件顺序）。"""
    out: list[float] = []
    for token in text.replace("\r", " ").replace("\n", " ").split():
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


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
    engine: str | None = None,
) -> tuple[float, float]:
    """按 C# EGM 流程计算绕击跳闸率。返回 (跳闸率, alpha?)。

    engine：native（默认，原生 numpy 直译）/ wine（跑 rjtzl_egm*.exe）。
    默认取配置 `LP_EGM_ENGINE_MODE`（默认 native）。native 未覆盖的组合会明确抛
    egm_native.EgmNotImplemented（不会静默降级到别的引擎）。
    """
    circuits = _circuit_geometry(base_tower)
    if not circuits:
        raise ValueError("缺少回路几何（circuit_geometry_json），无法计算绕击跳闸率")
    circuit_count = len(circuits)
    egm_type = egm_type_for_tower(tower_type, circuit_count, voltage_kv=voltage_kv)
    voltage = int(voltage_kv or 0)
    mode = (engine or getattr(get_settings(), "egm_engine_mode", "native") or "native").strip().lower()
    if mode not in {"native", "wine"}:
        raise ValueError(f"未知的 EGM 引擎：{mode}（应为 native / wine）")

    cic_text = build_cic(base_tower=base_tower, profile=profile, egm_type=egm_type)
    density = _num(base_tower.get("lightning_density"))
    slope1 = _num(base_tower.get("slope_1")) or 0.0
    slope2 = _num(base_tower.get("slope_2")) or 0.0

    total = 0.0
    # 两轮输入（倾角1 / -倾角2）：wine 单次 ~113s，相同倾角复用同一个结果能省一半时间。
    if mode == "native":
        cic_vals = _parse_numbers(cic_text)
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
            # 直接用页面/快照装配好的 cic/Ic 数值调用原生引擎（与 exe 的文件契约一致）
            values = egm_native.run_egm(
                cic_vals, _parse_numbers(ic_text), voltage=voltage, egm_type=egm_type
            )
            _run_cache[_key] = values
            total += _extract(egm_type, values, turn=turn)
    else:
        exe = atp_root / str(voltage) / f"{voltage}egm" / f"rjtzl_egm{egm_type}.exe"
        if not exe.exists():
            raise FileNotFoundError(f"缺少 EGM 程序：{exe}")
        with tempfile.TemporaryDirectory(prefix="egm_rj_") as tmp:
            work_dir = Path(tmp)
            (work_dir / "param_main_cic.txt").write_text(cic_text, encoding="gbk", errors="replace")
            (work_dir / "name_egm{}.txt".format(egm_type)).write_text(
                "param_main_cic.txt\nparam_main_Ic.txt\nresult_main.txt\n", encoding="gbk", errors="replace"
            )
            _run_cache = {}
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
        "[EGM] 绕击跳闸率（%s 引擎）：egm%d 电压=%s 回路数=%d Ng=%s Ic=%s 合计=%.6f ÷%.0f = %.6f",
        mode, egm_type, voltage, circuit_count, density, raoji_withstand_ka, total, divisor, trip_rate,
    )
    return round(trip_rate, 6), 0.0
