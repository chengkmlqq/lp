# -*- coding: utf-8 -*-
"""按模型自带 long.dat 重建测试线路几何（数值校准，保证改写真幂等）。

核心思路：
  1. 解析资产 long.dat 的 LINE CONSTANTS 导体坐标（相导线按行序 = 上/中/下相，地线行 = 避雷线）。
  2. 造一条「内存中的测试线路」走生产快照装配 → 解析器算参数 → build_dat_values
     → rewrite_dat_text 原地改写该资产 dat。
  3. 比较改写结果与原始 dat 的逐行高度，按差值迭代修正测试线路的相高/避雷线高度，
     直到两者一致（容差 6cm）。这样平台改写 .dat 变成幂等操作，
     测试跑的就是「模型自带几何」，与 C# 侧口径一致。

用法：
  python rebuild_tl2.py --dry-run
  python rebuild_tl2.py --apply [--voltages 110,220]
"""
import os
import sys

sys.path.insert(0, "/app")

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.atp_test_line import AtpTestLine, AtpTestLineCircuit  # noqa: E402
from app.schemas.atp_test_line import AtpTestLineCircuitPayload, AtpTestLineCreateRequest  # noqa: E402
from app.services.atp_dat_writer import rewrite_dat_text  # noqa: E402
from app.services.atp_geometry_pipeline import (  # noqa: E402
    _voltage_offset,
    build_dat_values,
    resolve_section,
)
from app.services.atp_line_snapshot import assemble_from_test_line  # noqa: E402
from app.services.atp_param_config import compute_params_detailed_from_runtime  # noqa: E402
from app.services.atp_test_line_service import _BUILTIN_VOLTAGE_REFERENCE, create_test_line  # noqa: E402

VFS = "/app/data/vfs/atp-assets"
APPLY = "--apply" in sys.argv
TOL = 0.06


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


VOLTS = [v.strip() for v in (arg("--voltages") or "35,66,110,220,330,500,750,1000").split(",") if v.strip()]


def parse_rows(text_dat):
    """返回 (phases, shields)，每项为 (x, y)。"""
    lines = text_dat.replace("\r\n", "\n").split("\n")
    start = None
    for i, line in enumerate(lines):
        if "LINE CONSTANTS" in line.upper():
            start = i + 2
            break
    if start is None:
        return None, None
    phases, shields = [], []
    for line in lines[start:]:
        u = line.strip().upper()
        if u.startswith("BLANK"):
            break
        if not line.strip() or u.startswith("C "):
            continue
        tk = line.split()
        if len(tk) < 11:
            continue
        try:
            x, y, last = float(tk[5]), float(tk[6]), int(float(tk[10]))
        except (ValueError, IndexError):
            continue
        (phases if last != 0 else shields).append((x, y))
    if len(phases) < 3:
        return None, None
    return phases, shields


def relens(work_atp):
    try:
        txt = open(work_atp, "rb").read().decode("latin-1")
    except OSError:
        return None
    for line in txt.splitlines():
        u = line.upper().replace(" ", "")
        if u.startswith("RELENS") and "=" in u:
            try:
                return float(u.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def tower_raw(tower, shield):
    if shield == "none":
        return tower + "no"
    if shield == "single":
        return tower + "d"
    return tower


def find_dir(volt, tower, shield):
    base = os.path.join(VFS, str(volt), tower_raw(tower, shield))
    for scene in ("fanji", "raoji1", "raoji2", "raoji3"):
        for arr in ("noM", "M123"):
            cand = os.path.join(base, scene, arr)
            if os.path.isfile(os.path.join(cand, "work.atp")):
                return cand
    return None


def draft_row(geo, ins, volt, tower, shield):
    row = AtpTestLine(
        code=f"TL-{volt}-{tower}-{shield}",
        name=f"{volt}kV {tower} {shield} 测试线路",
        voltage_level=str(volt), tower_type=tower, shield_wire=shield,
        circuit_count=1, span_small_m=350.0, span_large_m=450.0,
        ground_resistance_ohm=10.0, lightning_density=2.85,
        call_height_m=max(geo["hu"], geo["hm"], geo["hl"]),
        insulator_length_m=ins,
        shield_wire_height_m=geo["lw_h"],
        shield_wire_left_mid_m=geo["lw_mid"],
        shield_wire_right_mid_m=geo["lw_mid"],
    )
    row.circuits = [AtpTestLineCircuit(
        circuit_no=1, phase_sequence="ABC",
        spacing_upper_m=geo["spu"], spacing_middle_m=geo["spm"], spacing_lower_m=geo["spl"],
        height_upper_m=geo["hu"], height_middle_m=geo["hm"], height_lower_m=geo["hl"],
    )]
    return row


def compute_out(geo, ins, volt, tower, shield, dat_text):
    """生产链路：装配 → 参数 → dat 取值 → 原地改写，返回改写后的导体行。"""
    base_tower, profile = assemble_from_test_line(draft_row(geo, ins, volt, tower, shield))
    det = compute_params_detailed_from_runtime(
        base_tower=dict(base_tower), profile=dict(profile),
        execution_options={"tower_kind": tower, "line_voltage_kv": int(volt),
                           "scene_type": "fanji", "arrester_config": "noM"},
    )
    params = det.as_dict() if det else {}
    sec = resolve_section(tower, int(volt))
    vals = build_dat_values(section=sec, params=params, profile=profile,
                            base_tower=base_tower, voltage_kv=volt)
    out = rewrite_dat_text(dat_text, sec, vals)
    ph, sh = parse_rows(out)
    return ph, sh, sec


def calibrate(geo, ins, volt, tower, shield, dat_text, target_ph, target_sh):
    geo = dict(geo)
    last = ""
    prev = None
    for _ in range(10):
        try:
            ph, sh, sec = compute_out(geo, ins, volt, tower, shield, dat_text)
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {str(exc)[:120]}"
        if not ph or len(ph) < 3:
            return None, "改写出不来导体行"
        d = [target_ph[i][1] - ph[i][1] for i in range(3)]
        d_lw = (target_sh[0][1] - sh[0][1]) if (sh and target_sh) else 0.0
        last = f"d=({d[0]:+.2f},{d[1]:+.2f},{d[2]:+.2f}) dlw={d_lw:+.2f}"
        if all(abs(x) < TOL for x in d) and abs(d_lw) < TOL:
            return geo, sec
        # 该槽位对相高不敏感（解析器走了别的分支）→ 无法收敛，接受当前值并记录残差
        if prev is not None and all(abs(d[i] - prev[i]) < 0.005 for i in range(3)) and abs(d_lw - prev[3]) < 0.005:
            return geo, f"{sec}(残差 {last})"
        prev = (d[0], d[1], d[2], d_lw)
        geo["hu"] += d[0]
        geo["hm"] += d[1]
        geo["hl"] += d[2]
        geo["lw_h"] += d_lw
    return None, f"校准不收敛（{last}）"


def main():
    db = SessionLocal()
    volt_in = ",".join(f"'{v}'" for v in VOLTS)
    groups = db.execute(text(
        f"select voltage_level v, tower_type t, shield_wire w from atp_asset "
        f"where is_published=1 and voltage_level in ({volt_in}) "
        f"group by 1,2,3 order by 1+0,1,2,3"
    )).mappings().all()
    print(f"维度组 {len(groups)} 个")

    ok = fail = degraded = 0
    for g in groups:
        volt, tower, shield = g["v"], g["t"], g["w"]
        src = find_dir(volt, tower, shield)
        if not src:
            print(f"  SKIP {volt}/{tower}/{shield} 找不到目录")
            fail += 1
            continue
        dat_text = open(os.path.join(src, "long.dat"), "rb").read().decode("gbk", errors="replace")
        phases, shields = parse_rows(dat_text)
        ins = relens(os.path.join(src, "work.atp"))
        ref = _BUILTIN_VOLTAGE_REFERENCE.get(str(volt), {})
        ins_src = "model"
        if not ins:
            ins = ref.get("insulator_length_m")
            ins_src = "builtin"

        degraded_note = ""
        if not phases or not shields:
            # 无导体坐标 / 无避雷线导体行：无法反推，退回内置参考几何并标可疑
            spacing = ref.get("spacing") or (8.0, 10.0, 8.0)
            height = ref.get("height") or (20.0, 26.0, 20.0)
            geo = {"spu": spacing[0], "spm": spacing[1], "spl": spacing[2],
                   "hu": height[0], "hm": height[1], "hl": height[2],
                   "lw_h": ref.get("shield_h") or (max(height) + 5),
                   "lw_mid": (max(spacing) / 2) if spacing else 4.0}
            degraded += 1
            degraded_note = "；dat 缺导体坐标或避雷线导体，用电网参考几何"
            print(f"  {volt}/{tower}/{shield}: 降级内置几何 "
                  f"{geo['hu']}/{geo['hm']}/{geo['hl']}（该模型按可疑对待）")
        else:
            K = _voltage_offset(float(volt))
            geo = {
                "spu": abs(phases[0][0]), "spm": abs(phases[1][0]), "spl": abs(phases[2][0]),
                "hu": phases[0][1] + float(ins or 0.0) + K,
                "hm": phases[1][1] + float(ins or 0.0) + K,
                "hl": phases[2][1] + float(ins or 0.0) + K,
                "lw_h": (max(s[1] for s in shields) if shields else phases[0][1] + float(ins or 0.0) + K),
                "lw_mid": (max(abs(s[0]) for s in shields) if shields else 0.0),
            }
            geo, sec = calibrate(geo, ins, volt, tower, shield, dat_text, phases, shields)
            if not geo:
                print(f"  FAIL {volt}/{tower}/{shield} 校准失败：{sec}")
                fail += 1
                continue
            ph_out, sh_out, _ = compute_out(geo, ins, volt, tower, shield, dat_text)
            print(f"  {volt}/{tower}/{shield}: 相高 {geo['hu']:.2f}/{geo['hm']:.2f}/{geo['hl']:.2f} "
                  f"间距 {geo['spu']:.2f}/{geo['spm']:.2f}/{geo['spl']:.2f} "
                  f"地线 {geo['lw_h']:.2f}@{geo['lw_mid']:.2f} ins={ins}({ins_src}) "
                  f"→ dat {[round(p[1], 2) for p in ph_out[:3]]} vs 原 {[round(p[1], 2) for p in phases[:3]]}")

        if not APPLY:
            ok += 1
            continue

        code = f"TL-{volt}-{tower}-{shield}"
        old = db.execute(text("select id from atp_test_line where code=:c"), {"c": code}).mappings().first()
        if old:
            db.execute(text("delete from atp_test_line_circuit where test_line_id=:i"), {"i": old["id"]})
            db.execute(text("delete from atp_test_line where id=:i"), {"i": old["id"]})
            db.commit()
        payload = AtpTestLineCreateRequest(
            code=code, name=f"{volt}kV {tower} {shield} 测试线路",
            description=f"按资产 {src.replace('/app/data/vfs/', '')} 的 long.dat 反推校准{degraded_note}",
            voltage_level=str(volt), tower_type=tower, shield_wire=shield, circuit_count=1,
            span_small_m=350.0, span_large_m=450.0, ground_resistance_ohm=10.0,
            lightning_density=2.85,
            call_height_m=max(geo["hu"], geo["hm"], geo["hl"]),
            insulator_length_m=ins,
            shield_wire_height_m=geo["lw_h"],
            shield_wire_left_mid_m=geo["lw_mid"], shield_wire_right_mid_m=geo["lw_mid"],
            circuits=[AtpTestLineCircuitPayload(
                circuit_no=1, phase_sequence="ABC",
                spacing_upper_m=geo["spu"], spacing_middle_m=geo["spm"], spacing_lower_m=geo["spl"],
                height_upper_m=geo["hu"], height_middle_m=geo["hm"], height_lower_m=geo["hl"],
            )],
        )
        try:
            create_test_line(db, payload=payload, actor_user_id="admin", allow_warnings=True)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    -> 创建失败 {str(exc)[:180]}")
            fail += 1

    print(f"完成：成功 {ok}（其中降级几何 {degraded}），失败 {fail}")


if __name__ == "__main__":
    main()
