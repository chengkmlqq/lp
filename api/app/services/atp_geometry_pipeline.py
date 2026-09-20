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
# ⚠️ 只从 atpmingw 取会在部分环境直接失效：有的部署卷里根本没有 atpmingw 目录
# （2026-09-15 实测 36 环境：atpmingw 不存在 → graphics 没拷进运行目录 →
#  ATP 报 `Attempt to connect disk file named "graphics" has failed` → 不产出 .pch，
#  但退出码仍为 0，表现为"几何重生成失败却看不出原因"）。故改为多源兜底。
_ENGINE_SOURCES = (
    Path("/app/data/wine/ATP/atpmingw"),   # C# 发行包原样目录（若存在）
    Path("/app/data/wine/ATP"),            # 引擎根目录（卷内通常在此）
    Path("/app/static/wine/ATP"),          # 镜像内自带（随镜像分发）
)
# 缺这两个 ATP 一定跑不出 .pch（listsize.dat 可缺，ATP 会自行用最大尺寸）
_ENGINE_REQUIRED = ("startup", "graphics")


def _ensure_engine_files(engine_dir: Path) -> None:
    """把 ATP 引擎必需文件拷到运行目录（幂等，多源兜底）。"""
    missing: list[str] = []
    for name in _ENGINE_FILES:
        dst = engine_dir / name
        if dst.exists():
            continue
        for root in _ENGINE_SOURCES:
            src = root / name
            if not src.is_file():
                continue
            try:
                dst.write_bytes(src.read_bytes())
                break
            except OSError:  # pragma: no cover
                logger.warning("[ATP] 引擎文件复制失败：%s ← %s", name, src, exc_info=True)
        if not dst.exists() and name in _ENGINE_REQUIRED:
            missing.append(name)
    if missing:
        # 环境不满足计算条件 → 明确报错，禁止让 ATP 卡到超时后再伪装成"几何重生成"
        raise RuntimeError(
            f"ATP 引擎必需文件缺失：{missing}（运行目录 {engine_dir}；已查找来源 "
            f"{[str(p) for p in _ENGINE_SOURCES]}）。缺 graphics/startup 时 ATP 不会产出 .pch。"
        )


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

    # 相中距：⚠️ 2026-09-20 修复（与 C# 对拍发现，见中转站消息 #0008）
    # C# 权威口径（ComputeLightningProtection.cs:3843-4483 的 MySetValue）：
    #   .dat 的相中距取**杆塔几何的「上/中/下相中距」**（mParamSet.m上/中/下相中距sh_m[回路]），
    #   与 RELE 槽位无关。此前本函数**优先**取 RELE09/06/03 —— 该假设只对鼓型（双回）成立
    #   （鼓型模板 RELE09/06/03 = |sp_u|/|sp_m|/|sp_l|）；对单回塔型（干字/酒杯/猫头/上字）
    #   RELE09/RELE03 是避雷线中距等其它量 → .dat 几何整体错位。
    #   实测证据：ganzi long.dat 第 1 行 C#=-6.1(=sp_u) vs LP=-4.6(=RELE09)；
    #             第 3 行 C#=+6.5(=sp_l) vs LP=+6.1(=RELE03)。
    # 现改为：**杆塔几何优先，RELE 仅作兜底**（无杆塔几何时保持旧行为，不静默降级为 0）。
    def _spacing(key: str, rele: str) -> float:
        geo = (base_tower or {}).get("circuit_geometry_json") or {}
        first = geo.get("I") or (next(iter(geo.values())) if geo else None)
        val = ((first or {}).get("phase_spacing_m") or {}).get(key)
        if val is not None:
            return abs(float(val))
        v = _num(params, rele)
        if v is not None:
            return v
        raise RuntimeError(
            f"缺少杆塔几何 phase_spacing_m.{key} 且模板无 {rele}，无法改写 .dat 几何"
        )

    return build_values(
        section,
        sp_upper=_spacing("upper", "RELE09"),
        sp_middle=_spacing("middle", "RELE06"),
        sp_lower=_spacing("lower", "RELE03"),
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


GEOMETRY_LOCK = threading.Lock()


def regenerate_line_models(*args: object, **kwargs: object):
    """带全局线程锁的几何重生成（并行二分时多线程会同时改写同一批 .dat/.lib，必须串行化）。"""
    with GEOMETRY_LOCK:
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

        # ⚠️ 必须传**相对文件名**（cwd 已是 engine_dir）——2026-09-15 实测定位：
        # ATP 的 Fortran 代码会把命令行传入的文件名整串**小写化**后在（大小写敏感的）
        # Linux/Wine 上打开。绝对路径含大写段时（/app/data/wine/ATP/500/guxing/fanji/noM/…）
        # 会被小写成 …/atp/… 而打不开，ATP 于是退到交互提示（"EMTP begins… BOTH:>"）
        # 把对话框无限写进 GB 级 <pid>.tmp 并挂到 1800s 超时，且 .pch 不被更新
        # → 几何静默沿用旧 .pch。实测：相对名 0.6 CPU 秒成功出 .pch，绝对路径 rc=3 失败。
        # 记录旧 .pch 时间戳：ATP 调用失败时旧文件仍在，只查 exists() 会**静默沿用旧几何**
        # （2026-09-15 实测：路径写法不对导致 LCC 从未成功，却因旧 .pch 存在而一路"成功"）。
        pch_path = engine_dir / f"{name}.pch"
        stale_mtime = pch_path.stat().st_mtime_ns if pch_path.exists() else None

        command = build_command(input_path=Path(dat_path.name))
        # LCC 几何计算同样是长耗时引擎调用 → 带心跳，避免静默期被误判为卡死。
        from ..core.subprocess_heartbeat import run_with_heartbeat

        result = run_with_heartbeat(
            command,
            cwd=str(engine_dir),
            env=env,
            timeout=timeout_seconds,
            label=f"{name}.dat 线路模型 LCC 重生成",
        )
        pch_path = engine_dir / f"{name}.pch"
        if not pch_path.exists():
            raise RuntimeError(
                f"{name}.dat 的 LCC 运行未产出 .pch（退出码={result.returncode}）："
                f"{(result.stderr or result.stdout or '')[:400]}"
            )
        # 旧 .pch 没被刷新 = ATP 实际没算成功（只是旧文件还在）→ 必须报错，禁止静默沿用旧几何
        if stale_mtime is not None and pch_path.stat().st_mtime_ns == stale_mtime:
            raise RuntimeError(
                f"{name}.dat 的 LCC 未刷新 {name}.pch（仍是旧文件，几何可能未更新）；"
                f"退出码={result.returncode}，输出尾部：{(result.stdout or result.stderr or '')[-400:]}"
            )
        # pch_to_lib：KARD=分支头行号+2、KBEG/KEND=固定6字符（与 C# 样本逐字节一致）。
        # ⚠️ 不可用模板 .lib 头部（模板 KARD 是别的几何的行号，硬套 → ATP fmt 错误 rc=3）。
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
