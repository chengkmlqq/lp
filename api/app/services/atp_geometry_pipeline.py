"""ATP 导线几何管线：按塔改写 4 个 .dat → 跑 LCC 出 .pch → 生成 .lib。

2026-09-13：Web 原先从不做这两步，直接用导入资产里的静态几何（属于别的塔），
导致 .lib（线路模型）几何错误 → 仿真/多相数值系统性偏差。

流程（每塔一次，几何与雷电流无关，二分期间可复用）：
  1. rewrite_dat_text：用塔几何改写 long/short/dahao/xiaohao.dat
  2. ATP LCC：`both <name>.dat s -r` → <name>.pch
     （引擎取 settings.atp_tpbig_executable，2026-11-02 起为 mytpbig.exe 大表版；
      LCC 输出与 tpbig.exe 仅末位浮点有效数字不同，量级 <1e-15，数值等价）
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

# C# `switch(mDYDJ)` 的电压等级档位（ComputeLightningProtection.cs）。
VOLTAGE_GRADES = (35.0, 66.0, 110.0, 220.0, 330.0, 500.0, 750.0, 1000.0)


def voltage_grade_kv(voltage_kv: Any) -> float:
    """把线路标称/设备电压归并到 C# 的电压等级档位。

    115kV / 230kV 是 110kV / 220kV 系统的设备额定电压（不是独立档位）。
    C# switch 只有 35/66/110/220/330/500/750/1000，直接按「上界」比较会把
    115 判成 220 档、230 判成 330 档，呼高/相高/避雷线高修正量差 1~3 倍
    （115 实测 REHG 修正 2.0 → 10/3、RELE01 8.6 → 8.5 走错分支）。
    这里按「就近下档 + 8% 上浮容差」归并：115→110、230→220，其余不变。
    """
    try:
        v = float(voltage_kv or 0)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:
        return 0.0
    for grade in VOLTAGE_GRADES:
        if v <= grade * 1.08:
            return grade
    return VOLTAGE_GRADES[-1]


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
    v = int(voltage_grade_kv(voltage_kv))
    return {35: 10.0 / 3.0, 66: 1.5, 110: 10.0 / 3.0, 220: 14.0 / 3.0,
            330: 14.0 / 3.0, 500: 8.0, 750: 14.0 / 3.0, 1000: 0.0}.get(v, 0.0)


def _insulator_m(profile: dict) -> float:
    raw = (profile or {}).get("insulator_length_m")
    try:
        return float(raw or 0.0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def _opt_float(value: Any) -> float | None:
    """宽松转 float；无法转换返回 None。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    def need_any(*names: str) -> float:
        """按序取第一个存在的槽位（直流塔避雷线高度槽位是 HG 而非 REHG）。"""
        for name in names:
            v = _num(params, name)
            if v is not None:
                return v
        raise RuntimeError(f"缺少 {'/'.join(names)}，无法改写 .dat 几何")

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
    # ⚠️ 2026-11-06 修复（220kV 承福甲线 252 塔 C#/Web 对拍）：**不再按相序置换**。
    # C# 桌面版（台账普通计算）走 MyFunction.cs:2483 AllCall_CS(101, ...) →
    # Method.cs:127 `if (_type > 100) mWith_ShangZhongXia = true` →
    # MyParamClass.shCheckThreePhaseAndSetPhase 走 3532 起的「上/中/下直读」分支：
    # 台账「上/中/下相中距(高度)」三列就是**物理位置**，按列名直配
    # （"1回路A相中距m" 槽位收到的就是 CSV 的 I回上相中距，见 MyFunction.cs:2436
    # guxing 参数拼接顺序 1ZJ_Shang,2ZJ_Shang,1ZJ_Zhong,... 与
    # shSetDefault_GanTa_Param 注册序 14="1回路A相中距m" 一一对应）。
    # 相序串只用于输出闪络相命名，不参与几何重排。
    # 此前的 permute_circuit_geometry 对齐的是 C# mode<100 的 A/B/C 相命名入口
    # （智洋对接等），对桌面 101 入口是错的：ACB/CBA/BAC 塔的中/下相几何互换，
    # 反击耐雷系统性偏低 ~24%（0.77×）。d35shangzi 12 塔验证未暴露该 bug，
    # 因其相序 CBA 且 A≡C（中距 7/7、高度 17/17），置换恰为恒等。
    _cg = dict((base_tower or {}).get("circuit_geometry_json") or {})

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
        first = _cg.get("I") or (next(iter(_cg.values())) if _cg else None)
        val = ((first or {}).get("phase_spacing_m") or {}).get(key)
        if val is not None:
            return abs(float(val))
        v = _num(params, rele)
        if v is not None:
            return v
        raise RuntimeError(
            f"缺少杆塔几何 phase_spacing_m.{key} 且模板无 {rele}，无法改写 .dat 几何"
        )

    dc_kinds = {"zj", "zx", "zxj", "ky", "nz", "zhiliu", "vzhiliu"}
    kind = section.split("-", 1)[0]
    is_dc = kind in dc_kinds

    return build_values(
        section,
        # ⚠️ 2026-09-20：shangzi 分支的「避雷线平均高度」用**原始避雷线高度**（C#
        # ComputeLightningProtection.cs:4105 `averageHeightBLX = m避雷线高度_m; -1.2`），
        # 不是 work.atp 的 REHG（REHG 已含电压分级修正）。传入原始值供 _shangzi 使用。
        shield_h=_opt_float(profile.get("shield_wire_height_m")),
        sp_upper=_spacing("upper", "RELE09"),
        sp_middle=_spacing("middle", "RELE06"),
        sp_lower=_spacing("lower", "RELE03"),
        lw_left=abs(float(lw_left)),
        lw_right=abs(float(lw_right)),
        rehc1=0.0 if is_dc else need("REHC1"),
        rehc2=0.0 if is_dc else need("REHC2"),
        rehc3=0.0 if is_dc else need("REHC3"),
        # 直流塔模板避雷线高度槽位是 HG________（RELE 体系之外的直流专用槽）；
        # 交流塔是 REHG______。need_any 按序兼容两种模板，直流塔不再因缺 REHG 而炸。
        rehg=need_any("REHG", "HG") if is_dc else need_any("REHG", "HG"),
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


def _has_positive_values(group: Any) -> bool:
    """分组里的上/中/下三相，至少有一个是正数（None/0/空串都算缺失）。"""
    if isinstance(group, dict):
        values = group.values()
    elif isinstance(group, (list, tuple)):
        values = group
    else:
        return False
    for v in values:
        try:
            if v is not None and float(v) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def has_phase_geometry(profile: dict[str, Any], base_tower: dict[str, Any] | None) -> bool:
    """快照是否带真实相导线几何（上/中/下相中距 + 相高）。

    缺这两组数据时 build_dat_values 只能靠 RELE 槽位兜底、相高按均分缺省，
    会把模型自带的三相同高/水平排列改写成"三层垂直排列 + 等间距"——
    几何整体错位，反击耐雷水平可以差一个量级（2026-11-06 115kV ganzi：
    模型自带相高 27.3m / 间距 6.8m，被改写成 18.7/14.7/10.7m / 8m，
    二分收敛到 1039.9kA，而 110kV 同塔型老模型是 125.8kA）。
    缺几何时宁可不改写、保留 ATPDraw 模型自带几何。

    ⚠️ 2026-11-06 修复：`_build_circuit_geometry_from_row()` 是**固定键**输出，
    即使台账上回路几何全为空，也会产出 `{"upper": None, "middle": None, ...}`。
    旧实现只判 `dict` 非空 → 全 None 也被当成"有几何"，随后 build_dat_values
    把 RELE 中距写成 0、相高按均分兜底，LCC 直接不产出 pch：
        35kV shangzi 实测 `RELE09: 2.7 -> 0.` / `RELE10: 1.8 -> 0.`
        → `long.dat 的 LCC 运行未产出 .pch`，任务整体失败。
    现改为**必须存在正数**才算有几何，与"缺几何就不改写"的原意一致。
    """
    for src in (
        (base_tower or {}).get("circuit_geometry_json"),
        (profile or {}).get("geometry_layers_json"),
    ):
        if not isinstance(src, dict):
            continue
        for key in ("I", "II", "III", "IV"):
            layer = src.get(key)
            if not isinstance(layer, dict):
                continue
            spacing = layer.get("phase_spacing_m") or layer.get("spacing")
            height = layer.get("phase_height_m") or layer.get("height")
            if _has_positive_values(spacing) and _has_positive_values(height):
                return True
    return False


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
    layouts: dict[str, dict] | None = None,
) -> list[str]:
    """改写 4 个 .dat 并重生成 .lib。返回处理过的文件名（供日志）。

    layouts: 资产扫描缓存的几何坐标 {name: geometry_dict}，提供时
    rewrite_dat_text 优先用缓存行号（不再现场推导）；缺失时现场推导兜底。
    """
    section = resolve_section(tower_kind, voltage_kv)
    # ⚠️ 缺相几何时**不改写 .dat**：build_dat_values 只能用 RELE 槽位兜底 +
    # 相高均分缺省，把模型自带几何（三相同高/水平排列）改成三层垂直排列，
    # 塔身支路长度与绝缘子受力全变，耐雷水平失真一个量级且不报错。
    if not has_phase_geometry(profile, base_tower):
        print(
            "[ATP] 快照缺相导线几何（phase_spacing_m/phase_height_m 均为空），"
            "跳过 .dat 改写与 LCC 重生成，保留 ATPDraw 模型自带几何",
            file=sys.stdout, flush=True,
        )
        return []
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
            layout=(layouts or {}).get(name),
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
