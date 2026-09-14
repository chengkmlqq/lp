"""ATP 导线几何管线：按塔改写 4 个 .dat → 跑 LCC 出 .pch → 生成 .lib。

2026-09-13：Web 原先从不做这两步，直接用导入资产里的静态几何（属于别的塔），
导致 .lib（线路模型）几何错误 → 仿真/多相数值系统性偏差。

流程（每塔一次，几何与雷电流无关，二分期间可复用）：
  1. rewrite_dat_text：用塔几何改写 long/short/dahao/xiaohao.dat
  2. tpbig LCC：`both <name>.dat s -r` → <name>.pch
  3. pch_to_lib：<name>.pch → <name>.lib

已逐字节对齐 C# 验证：.dat（500/110）、.lib（6/6 样本）。
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from app.services.atp_dat_writer import (
    build_values,
    pch_to_lib,
    resolve_section,
    rewrite_dat_text,
)

logger = logging.getLogger(__name__)

_DAT_NAMES = ("long", "short", "dahao", "xiaohao")
# LCC 运行必需的引擎文件（缺任一 ATP 会停在交互提示、产不出 .pch）
_ENGINE_FILES = ("startup", "graphics", "graphics.aux", "graphics.std", "listsize.big", "listsize.dat")
_ENGINE_SRC = Path("/app/data/wine/ATP/atpmingw")


def _ensure_engine_files(engine_dir: Path) -> None:
    """把 ATP 引擎必需文件拷到运行目录（幂等）。"""
    for name in _ENGINE_FILES:
        src = _ENGINE_SRC / name
        dst = engine_dir / name
        if src.exists() and not dst.exists():
            try:
                dst.write_bytes(src.read_bytes())
            except OSError:  # pragma: no cover
                logger.warning("[ATP] 引擎文件复制失败：%s", name, exc_info=True)


def _num(params: dict[str, str], name: str) -> float | None:
    # work.atp 的 $PARAMETER 键名带下划线填充（REHC1_____ / REHG______ / RELE09）
    raw = params.get(name)
    if raw is None:
        wanted = name.rstrip("_")
        for key, value in params.items():
            if str(key).rstrip("_") == wanted:
                raw = value
                break
    if raw is None:
        return None
    try:
        return abs(float(str(raw).strip().rstrip(".")))
    except (TypeError, ValueError):
        return None


def _voltage_offset(voltage_kv) -> float:
    """C# 平均高度扣减量 K（:1855-1872 / :2016-2048）。"""
    try:
        v = int(voltage_kv or 0)
    except (TypeError, ValueError):
        return 0.0
    return {35: 10.0 / 3.0, 66: 1.5, 110: 10.0 / 3.0, 220: 14.0 / 3.0,
            330: 14.0 / 3.0, 500: 8.0, 750: 14.0 / 3.0, 1000: 0.0}.get(v, 0.0)


def _insulator_m(profile: dict) -> float:
    raw = (profile or {}).get("insulator_length_m")
    try:
        return float(raw or 0.0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _circuit_entry(cg, key) -> dict:
    node = (cg or {}).get(key)
    if not isinstance(node, dict):
        return {"spacing": {}, "height": {}}
    return {"spacing": node.get("phase_spacing_m") or {},
            "height": node.get("phase_height_m") or {}}


def _num_or_none(cg, key, group, sub):
    node = (cg or {}).get(key)
    if not isinstance(node, dict):
        return None
    val = (node.get(f"phase_{group}_m") or {}).get(sub)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def build_dat_values(*, section: str, params: dict[str, str],
                     profile: dict[str, Any],
                     base_tower: dict[str, Any] | None = None,
                     voltage_kv: Any = None) -> dict[str, float]:
    """从 work.atp 参数 + 杆塔资料推导 .dat 需要的几何值。"""

    def need(name: str) -> float:
        v = _num(params, name)
        if v is None:
            raise RuntimeError(f"缺少 {name}，无法改写 .dat 几何")
        return v

    lw = dict(profile.get("lightning_wire") or {})
    if not lw:
        # 快照里避雷线数据在 extra_profile_json / geometry_layers_json 下
        for key in ("extra_profile_json", "geometry_layers_json"):
            nested = profile.get(key)
            if isinstance(nested, dict) and isinstance(nested.get("lightning_wire"), dict):
                lw = dict(nested["lightning_wire"])
                break
    lw_left = lw.get("left_mid_distance_m")
    lw_right = lw.get("right_mid_distance_m")
    if lw_left is None or lw_right is None:
        raise RuntimeError("缺少避雷线左/右中距，无法改写 .dat 几何")

    # 杆塔回路几何（I/II/III/IV 回的上/中/下相中距与相高）——单回塔型与四回型都要用
    _cg = (base_tower or {}).get("circuit_geometry_json") or {}

    # 相中距：鼓型等模板由 RELE09/06/03 承载；单回塔型（猫头/酒杯/干字/门型/上子型）
    # 模板没有 RELE09 → 回退到杆塔几何（circuit_geometry_json 的上/中/下相中距）。
    def _spacing(rele: str, key: str) -> float:
        v = _num(params, rele)
        if v is not None:
            return v
        geo = (base_tower or {}).get("circuit_geometry_json") or {}
        first = geo.get("I") or (next(iter(geo.values())) if geo else None)
        val = ((first or {}).get("phase_spacing_m") or {}).get(key)
        if val is None:
            raise RuntimeError(f"缺少 {rele} 且杆塔几何无 phase_spacing_m.{key}，无法改写 .dat 几何")
        return abs(float(val))

    return build_values(
        section,
        sp_upper=_spacing("RELE09", "upper"),
        sp_middle=_spacing("RELE06", "middle"),
        sp_lower=_spacing("RELE03", "lower"),
        lw_left=abs(float(lw_left)),
        lw_right=abs(float(lw_right)),
        rehc1=need("REHC1"),
        rehc2=need("REHC2"),
        rehc3=need("REHC3"),
        rehg=need("REHG"),
        h_upper=_num_or_none(_cg, "I", "height", "upper"),
        h_middle=_num_or_none(_cg, "I", "height", "middle"),
        h_lower=_num_or_none(_cg, "I", "height", "lower"),
        sp_left=_num_or_none(_cg, "I", "spacing", "upper") or abs(float(lw_left)),
        sp_right=_num_or_none(_cg, "I", "spacing", "lower") or abs(float(lw_right)),
        h_left=_num_or_none(_cg, "I", "height", "upper"),
        h_right=_num_or_none(_cg, "I", "height", "lower"),
        insulator=_insulator_m(profile),
        voltage_offset=_voltage_offset(voltage_kv),
        circuits=[_circuit_entry(_cg, k) for k in ("I", "II", "III", "IV")],
    )


def span_km_for(name: str, base_tower: dict[str, Any]) -> float | None:
    """dahao←大号档距、xiaohao←小号档距；long/short 保持模板固定值（对齐 C# 实测）。

    档距在 base_tower_json（span_small_m / span_large_m）。
    """
    span_large = base_tower.get("span_large_m") or base_tower.get("span_large_span_m")
    span_small = base_tower.get("span_small_m") or base_tower.get("span_small_span_m")
    if name == "dahao" and span_large:
        return float(span_large) / 1000.0
    if name == "xiaohao" and span_small:
        return float(span_small) / 1000.0
    return None


_GEOMETRY_LOCK = threading.Lock()


def regenerate_line_models(*args: object, **kwargs: object):
    """带全局线程锁的几何重生成（并行二分时多线程会同时改写同一批 .dat/.lib，必须串行化）。"""
    with _GEOMETRY_LOCK:
        return _regenerate_line_models_unlocked(*args, **kwargs)


def _regenerate_line_models_unlocked(
    *,
    engine_dir: Path,
    tower_kind: str,
    voltage_kv: Any,
    params: dict[str, str],
    profile: dict[str, Any],
    base_tower: dict[str, Any],
    build_command,
    env: dict[str, str],
    timeout_seconds: int,
) -> list[str]:
    """改写 4 个 .dat 并重生成 .lib。返回处理过的文件名（供日志）。"""
    section = resolve_section(tower_kind, voltage_kv)
    values = build_dat_values(section=section, params=params, profile=profile,
                              base_tower=base_tower, voltage_kv=voltage_kv)
    _ensure_engine_files(engine_dir)
    done: list[str] = []
    for name in _DAT_NAMES:
        dat_path = engine_dir / f"{name}.dat"
        if not dat_path.exists():
            continue
        original = dat_path.read_bytes().decode("gbk", errors="replace")
        rewritten = rewrite_dat_text(
            original, section=section, values=values,
            span_km=span_km_for(name, base_tower),
        )
        dat_path.write_bytes(rewritten.encode("gbk", errors="replace"))

        # ⚡ 几何指纹未变 → 复用已生成的 .lib。
        # ⚠️ 必须每轮把缓存的 .lib 写回：_materialize_asset_files 每轮都用资产里的
        # 旧 .lib 覆盖回来，只"跳过 LCC"不写回会导致主仿真仍用旧几何的 .lib。
        geo_key = hashlib.sha1(rewritten.encode("gbk", errors="replace")).hexdigest()[:16]
        marker = engine_dir / f".geo_key_{name}"
        gen_cache = engine_dir / f".gen_lib_{name}"
        if (marker.exists()
                and marker.read_text(encoding="utf-8", errors="replace").strip() == geo_key
                and gen_cache.exists()):
            (engine_dir / f"{name}.lib").write_bytes(gen_cache.read_bytes())
            done.append(name)
            print(f"[ATP] {name} 几何未变({geo_key})，写回缓存 .lib（跳过 LCC）",
                  file=sys.stdout, flush=True)
            continue

        command = build_command(input_path=dat_path)
        result = subprocess.run(command, cwd=str(engine_dir), env=env,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout_seconds, check=False)
        pch_path = engine_dir / f"{name}.pch"
        if not pch_path.exists():
            raise RuntimeError(
                f"{name}.dat 的 LCC 运行未产出 .pch（退出码={result.returncode}）："
                f"{(result.stderr or result.stdout or '')[:400]}"
            )
        lib_text = pch_to_lib(pch_path.read_bytes().decode("gbk", errors="replace"))
        (engine_dir / f"{name}.lib").write_bytes(lib_text.encode("gbk", errors="replace"))
        gen_cache.write_bytes(lib_text.encode("gbk", errors="replace"))
        marker.write_text(geo_key, encoding="utf-8")
        done.append(name)
        print(f"[ATP] 线路模型已重生成：{name}.lib（几何改写 + LCC）", file=sys.stdout, flush=True)
    if not done:
        raise RuntimeError("未找到任何 .dat 文件，无法重生成线路模型")
    logger.info("[ATP] 线路模型重生成完成：%s", ",".join(done))
    return done
