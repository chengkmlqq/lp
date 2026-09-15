"""EGM 绕击跳闸率 —— 原生（numpy）实现，替代 wine 调用 rjtzl_egm*.exe。

来源：`rjtzl_egm*.exe` 是 MATLAB Coder 3.2 由 `.m` 生成的 C 代码（TDM-GCC 编译），
源码可从 C# 发行包 `V1_C_TZL_500_800/TZL<电压>egm<N>-*/` 取到。本模块是把该 C 代码
（main → single_tongdao → EGM_double_x → get_EGM_expose_arc_section_dan →
b_single_circle_line_crosspoint / point_shadow_on_x）直译成 numpy。

对齐证据（2026-09-15）：
  * 与 exe 目录中 C# 运行时留下的 `<NN>_param_main_{cic,Ic,result}.txt` 黄金样本对拍，
    输出 `%f`（6 位小数）**逐位一致**；
  * 覆盖组合见 `EGM_PARAMS` 的 `verified` 标记：未验证的组合一律抛错（禁止静默降级）。

关键实现要点（照抄 exe，否则结果静默出错）：
  1. 读文件契约：cic 取**文件前 2*n_circle 个值**（前 n 个是各圆 x、后 n 个是各圆 y），
     n_circle 写死在 exe 里（egm1=5 / egm2=8 / egm3=14 / 直流=4）；
  2. 电流档：`mtmp = min(Ic_left, Ic_right)` 起，步长 1，到 `Im`（写死 350）；
  3. 入射角：179 档，`Phi = (1+P)/180*pi`（从 1° 起，不含 0°/180°）；`Phi==pi/2` 时
     `point_shadow_on_x` 特判（直接取点的 x）；
  4. 清 0 判据按「层级下标 `int(b_I)-1`」写 0（`If` 写死在 exe 里：见参数表）；
  5. 输出 `y[i] = Ratio*e*Ng*ave[i]/1000*100`，i<2 用 `Ratiof`、i>=2 用 `Ratior`。
"""
from __future__ import annotations

import math
import os

import numpy as np

N_ANGLE = 179
_HALF_PI = math.pi / 2.0


class EgmNotImplemented(RuntimeError):
    """该（电压, 程序类型）组合没有经过黄金样本验证的原生实现 → 明确报错，不静默降级。"""


def _default_threads() -> int:
    """电流档并行线程数（LP_EGM_THREADS 覆盖）。实测多线程无收益（每块数组较小、
    内存带宽/分配开销占主导），故默认单线程。"""
    raw = os.environ.get("LP_EGM_THREADS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 1


# ---------------------------------------------------------------------------
# 各 exe 的写死参数（从 C# 发行包源码 main.c 提取 + 黄金样本对拍验证）
#   n_circle  ：击距圆个数（= result 文件值的个数）= egm1:5 / egm2:8 / egm3:14
#   If        ：反击耐雷水平（写死在 exe 里，用于绕击耐雷水平~反击耐雷水平之间的避雷线弧清 0）
#   Im        ：电流档上限（写死 350）
#   Ratiof/Ratior：避雷线圆 / 导线圆的系数（0.167 / 1）
#   另有 u_type（0=交流）、u_jixing（0）、u_voltage（交流分支不使用）
# ---------------------------------------------------------------------------
def _p(n_circle: int, If: float, verified: bool, source: str,
       wire_formula: str = "ieee") -> dict:
    return {"n_circle": n_circle, "If": If, "Im": 350.0, "Ratiof": 0.167,
            "Ratior": 1.0, "u_type": 0.0, "u_jixing": 0.0, "u_voltage": 0.0,
            "wire_formula": wire_formula,
            "verified": verified, "source": source}


EGM_PARAMS: dict[tuple[int, int], dict] = {
    # ---- 单回（egm1，5 圆）----
    (35, 1): _p(5, 40.0, True, "TZL35egm1-dan-20250328/main.c"),
    (66, 1): _p(5, 40.0, True, "TZL66egm1-dan-20251021/main.c"),
    (110, 1): _p(5, 40.0, True, "TZL110egm1-dan-20220331/main.c"),
    (220, 1): _p(5, 139.0, True, "TZL220egm1-dan-20220331/main.c"),
    (330, 1): _p(5, 40.0, True, "无源码；用部署 exe 重跑 2 个样本标定 If∈[40,41)"),
    (500, 1): _p(5, 129.0, True, "TZL500egm1-dan-20220331/main.c"),
    # ---- 双回（egm2，8 圆）----
    (35, 2): _p(8, 300.0, True, "TZL35egm2-shuang-20250328/main.c"),
    (66, 2): _p(8, 60.0, True, "TZL66egm2-shuang-20251021/main.c"),
    (110, 2): _p(8, 51.0, True, "TZL110egm2-shuang-20220331/main.c"),
    (220, 2): _p(8, 123.0, True, "TZL220egm2-shuang-20220331/main.c"),
    (330, 2): _p(8, 51.0, True, "无源码；用部署 exe 重跑 1 个样本标定 If∈[51,52)"),
    (500, 2): _p(8, 51.0, True, "TZL500egm2-shuang-20220331/main.c"),
    # ---- 四回（egm3，14 圆）----
    # 35egm3 实测用的是**旧版导线击距**（r=10·I^0.65），110/220egm3 用 IEEE 式 → 逐 exe 记 formula
    (35, 3): _p(14, 96.89, True, "C# 无样本；用 Web build_cic 输出喂部署 35egm3.exe 重跑逐位一致"
                                 "（旧版导线击距）", wire_formula="legacy"),
    (110, 3): _p(14, 200.0, True, "用 Web build_cic 输出喂部署 110egm3.exe 重跑逐位一致"),
    (220, 3): _p(14, 200.0, True, "用 Web build_cic 输出喂部署 220egm3.exe 重跑逐位一致"),
    # 500egm3.exe 属于另一套代码族（EGM_double_x + 非 _dan 版 expose，实测只输出 1 个值）→ 不支持
    (500, 3): _p(14, 200.0, False, "TZL500egm3(sihui)/main.c（500egm3.exe 是另一代码族，未移植）"),
    # 330egm3.exe 虽在磁盘上，但 C# tzl_model.txt 的 <sihuita> 段没有 330 → C# 本身不支持，故不进表
    # 注（2026-09-15 实测）：
    #   1) 1000egm1/egm2 属于另一套代码族（EGMd1_x/EGMcircle_d1、get_EGM_expose_arc_section
    #      非 _dan 版），未移植 → 不在表内，用 native 会明确抛错。
    #   2) egm3（四回，14 圆）没有与部署 exe 对齐的校验样本，且现状 build_cic 只写 16 个几何值
    #      （egm3 要读 28 个）→ 标为未验证，不会静默出数。
    #   3) 800/750 只有 egm4/egm5/egmDC（特型塔/直流），未移植。
    #   4) 330 的遗留黄金样本与部署 exe 不符（实测 exe 重跑 ≠ 遗留 result），
    #      其 If 用「exe 重跑」重新标定。
}


def supported(voltage: int, egm_type: int) -> bool:
    """该组合是否有「已验证」的原生实现。"""
    item = EGM_PARAMS.get((int(voltage), int(egm_type)))
    return bool(item and item.get("verified"))


def _rol_and_r(I_val: float, n_circle: int, u_type: float, u_voltage: float,
               u_jixing: float, wire_formula: str = "ieee") -> tuple[float, np.ndarray]:
    """C: get_EGM_expose_arc_section_dan 开头的击距圆半径数组（cic_rol3）。

    wire_formula：导线击距半径的版本差异（**逐 exe 不同，实测确认**）
      "ieee"  ：1.63·(5.015·I^0.578)^1.125（TZL 对接版 2022-03-31 起：66/110/220/330/500）
      "legacy"：r = 10·I^0.65（旧版；实测 35egm3 用的就是这个）
    """
    r = 10.0 * (I_val ** 0.65)
    rol = np.zeros(n_circle, dtype=float)
    if u_type != 1.0:
        rol[0] = r
        rol[1] = r
        for i in range(int(n_circle - 2.0)):
            if u_type == 0.0:
                if wire_formula == "legacy":
                    rol[i + 2] = r
                else:
                    rol[i + 2] = 1.63 * ((5.015 * (I_val ** 0.578)) ** 1.125)
            else:
                if 3.0 + i != float(n_circle):
                    if u_jixing == 0.0:
                        rol[i + 2] = 1.63 * ((5.015 * (I_val ** 0.578) + u_voltage) ** 1.125)
                        rol[int((3.0 + i) + 1.0) - 1] = 1.63 * ((5.015 * (I_val ** 0.578) - u_voltage) ** 1.125)
                    else:
                        rol[i + 2] = 1.63 * ((5.015 * (I_val ** 0.578) - u_voltage) ** 1.125)
                        rol[int((3.0 + i) + 1.0) - 1] = 1.63 * ((5.015 * (I_val ** 0.578) + u_voltage) ** 1.125)
    else:
        rol[:] = r
    return r, rol


def segments_for_I(I_val: float, cic: np.ndarray, n_circle: int, u_type: float,
                   u_voltage: float, u_jixing: float, thetaslop: float,
                   p_chunk: int = 8, wire_formula: str = "ieee") -> np.ndarray:
    """单个雷电流 I_val、179 个入射角下，各圆暴露弧在 x 轴投影的端点。

    返回 (179, n_circle, 2) 的 [首端, 末端]（未被扫到为 0）
    —— 对应 C 的 x_shadow_section_two_terminal。
    """
    xs = cic[:, 0]
    ys = cic[:, 1]
    r, rol = _rol_and_r(I_val, n_circle, u_type, u_voltage, u_jixing, wire_formula)
    ht = float(cic[0, 1])                        # 第一个圆（避雷线）高 → 地面击距系数
    kg = 0.36 + 0.17 * math.log(43.0 - ht) if ht < 40.0 else 0.55
    rg = kg * r                                  # 地面击距

    Phi = (1.0 + np.arange(N_ANGLE, dtype=float)) / 180.0 * math.pi
    sin_p = np.sin(Phi)
    cos_p = np.cos(Phi)
    step = 1.0 / sin_p                           # C: 变量 r 复用为扫描步长
    at_90 = Phi == _HALF_PI                      # C: point_shadow_on_x 对 pi/2 特判
    cot = np.where(at_90, 0.0, cos_p / sin_p)

    x_l0 = float(xs.min()) - r - 1.0
    x_r0 = float(xs.max()) + r + 1.0
    y_b0 = float(ys.min()) - r - 1.0
    y_t0 = float(ys.max()) + r + 1.0
    lo = Phi < _HALF_PI
    x_l = np.where(at_90, x_l0, np.where(lo, x_l0 - y_t0 * cot, x_l0 - y_b0 * cot))
    x_r = np.where(at_90, x_r0, np.where(lo, x_r0 - y_b0 * cot, x_r0 - y_t0 * cot))
    n_scan = np.trunc((x_r + (step - x_l)) / step).astype(np.int64)

    seg = np.zeros((N_ANGLE, n_circle, 2), dtype=float)
    if int(n_scan.max(initial=0)) <= 0:
        return seg

    sin_slope = math.sin(thetaslop / 180.0 * math.pi)
    cos_slope = math.cos(thetaslop / 180.0 * math.pi)
    rol_safe = np.where(rol > 0.0, rol, 1.0)      # 仅 I=0 时 rol 可能为 0
    # 按扫描点数升序分块：块内 a 数组长度 = n_scan 最大值，把填充浪费压到 ~1%
    order = np.argsort(n_scan, kind="stable")
    for s in range(0, N_ANGLE, p_chunk):
        chunk = order[s:s + p_chunk]
        c_nscan = n_scan[chunk]
        a_max = int(c_nscan.max())
        c_phi = Phi[chunk][:, None, None]                     # (c,1,1)
        c_cot = cot[chunk][:, None, None]
        c_step = step[chunk][:, None]                         # (c,1)
        c_xl = x_l[chunk][:, None]
        a_arr = np.arange(a_max, dtype=float)[None, :]
        valid_a = a_arr < c_nscan[:, None]                    # (c,a)
        a_vals = c_xl + a_arr * c_step                        # (c,a) = para_line[1]

        rol_b = rol[None, None, :]
        xs_b = xs[None, None, :]
        ys_b = ys[None, None, :]
        # 圆心到直线 x = cot(phi)*y + a 的有符号距离 d = ((cot*y0 + a) - x0)/sqrt(1+cot^2)
        # 1/sqrt(1+cot^2) 只与入射角有关 → 每块只算 179 个标量
        inv_norm = (1.0 / np.sqrt(1.0 + cot[chunk] ** 2))[:, None, None]
        num = c_cot * ys_b + a_vals[:, :, None] - xs_b        # 与 d 同号（inv_norm > 0）
        # 圆心→直线垂线的方向角（C 按 d 的符号分三支；符号与 num 一致）
        sgn = np.where(num > 0.0, -_HALF_PI, np.where(num == 0.0, 0.0, _HALF_PI))
        tc = c_phi + sgn
        d = num * inv_norm
        ad = np.abs(d)
        hit = ad <= rol_b
        # C 只在有交点时算 acos(ad/rol)；无交点时 alpha 不参与结果（下面用哨兵屏蔽）
        alpha = np.arccos(np.minimum(ad / rol_safe[None, None, :], 1.0))
        u1 = tc - alpha
        u2 = tc + alpha
        # 两交点 y（相切时 ad==rol → alpha=0，与 C 的相切分支等价）
        y1 = ys_b + rol_b * np.sin(u1)
        y2 = ys_b + rol_b * np.sin(u2)
        y1 = np.where(hit, y1, -1000.0)
        y2 = np.where(hit, y2, -1000.0)

        # C：在 2n 个第一/第二交点 y 中取 max（严格大于 → 首个最大，拼接顺序一致）
        yv = np.concatenate([y1, y2], axis=2)
        it = np.argmax(yv, axis=2)
        mtmp_y = np.take_along_axis(yv, it[:, :, None], axis=2)[:, :, 0]
        first = it < n_circle
        ci = np.where(first, it, it - n_circle)
        # 只需胜者的 x（C: kg = cross[itmp][0] 或 cross[itmp][2]）
        u1_sel = np.take_along_axis(u1, ci[:, :, None], axis=2)[:, :, 0]
        u2_sel = np.take_along_axis(u2, ci[:, :, None], axis=2)[:, :, 0]
        kgv = xs[ci] + rol[ci] * np.cos(np.where(first, u1_sel, u2_sel))
        # C 的哨兵判定：胜者圆的第一个交点为 -1000 ⇔ 该圆无交点（两点都是 -1000）
        sentinel = mtmp_y == -1000.0
        # 判据：交点高度（含地面倾角修正）≥ 地面击距
        cond = (~sentinel) & (mtmp_y * cos_slope - kgv * sin_slope >= rg) & valid_a

        # 状态机（照抄 C 的 circle_if_scan / y_bottom / index_last_a 语义）：
        # 同一角度只锁最先扫到的一段暴露弧
        for k in range(len(chunk)):
            p = int(chunk[k])
            av = a_vals[k]
            w = np.flatnonzero(cond[k])
            if w.size == 0:
                continue
            circ = ci[k][w]
            opened = np.zeros(n_circle, dtype=bool)
            closed = np.zeros(n_circle, dtype=bool)
            y_bottom2 = 0
            index_last_a = 0
            for pos, cj in zip(w, circ):
                cj = int(cj)
                if not opened[cj]:
                    opened[cj] = True
                    seg[p, cj, 0] = av[pos]      # C: y[itmp][0] = para_line[1]
                    seg[p, cj, 1] = av[pos]
                    y_bottom2 = cj + 1
                elif not closed[cj]:
                    seg[p, cj, 1] = av[pos]
                    index_last_a = cj + 1
                if y_bottom2 != index_last_a and index_last_a != 0:
                    closed[index_last_a - 1] = True
    return seg


def _phi_grid() -> np.ndarray:
    return (1.0 + np.arange(N_ANGLE, dtype=float)) / 180.0 * math.pi


def egm_double_x(*, cic: np.ndarray, n_circle: int, Im: float, If: float,
                 Ratiof: float, Ratior: float, e: float, Ng: float,
                 thetaslop: float, I_a: float, I_b: float,
                 Ic_left: float, Ic_right: float, u_type: float = 0.0,
                 u_voltage: float = 0.0, u_jixing: float = 0.0,
                 p_chunk: int = 8, threads: int | None = None,
                 wire_formula: str = "ieee") -> np.ndarray:
    """EGM_double_x 主流程（u_type != 1）。返回 y[n_circle]（次/100km·年）。"""
    n_circle = int(n_circle)
    if u_type == 1.0:
        raise EgmNotImplemented("EGM 原生实现未覆盖 u_type==1（双回单侧镜像）分支：无样本可对拍")

    # mtmp = min(Ic_left, Ic_right)（含 C 的 NaN 语义）
    mtmp = Ic_left
    if math.isnan(Ic_left):
        if not math.isnan(Ic_right):
            mtmp = Ic_right
    if Ic_right < mtmp:
        mtmp = Ic_right

    n_I = int(Im + (1.0 - mtmp))
    pphi = 0.75 * np.power(np.cos(_HALF_PI - _phi_grid()), 3.0) * (math.pi / 180.0)

    # 清 0 判据：C 是 `for (I=0; I<levels; I++) { b_I = mtmp+I; W[int(b_I)-1][...] = 0; }`
    # → 被清的行下标区间是 [mtmp-1, mtmp+levels-1)
    def _clear_span(levels: int) -> tuple[int, int]:
        if levels <= 0:
            return 0, 0
        start = int(mtmp) - 1
        stop = int(mtmp) + levels - 1
        return max(start, 0), max(min(stop, int(Im)), 0)

    n_clear_all = n_I if If > Im else 0
    n_clear_lw = int((If - 1.0) + (1.0 - mtmp))
    n_clear_dc_l = int((Ic_left - 1.0) + (1.0 - mtmp)) if u_type == 2.0 else 0
    n_clear_dc_r = int((Ic_right - 1.0) + (1.0 - mtmp)) if u_type == 2.0 else 0
    if u_type == 0.0:
        b_ic_left = Ic_left if (Ic_left <= Ic_right or math.isnan(Ic_right)) else Ic_right
        n_clear_ph = int((b_ic_left - 1.0) + (1.0 - mtmp))
    else:
        n_clear_ph = 0
    hi_lw = _clear_span(max(n_clear_all, n_clear_lw))
    hi_ph = _clear_span(n_clear_ph)
    hi_dc_l = _clear_span(n_clear_dc_l)
    hi_dc_r = _clear_span(n_clear_dc_r)

    def _accumulate(lo: int, hi: int) -> np.ndarray:
        """区间 [lo,hi) 内电流档对 ave 的贡献（C 的 fix_I 累加 + ave 累加两步合一）。"""
        acc = np.zeros(n_circle, dtype=float)
        for I in range(lo, hi):
            b_I = mtmp + float(I)
            bi = int(b_I)
            seg = segments_for_I(b_I, cic, n_circle, u_type, u_voltage, u_jixing,
                                 thetaslop, p_chunk=p_chunk, wire_formula=wire_formula)
            w = seg[:, :, 1] - seg[:, :, 0]
            row = bi - 1
            if hi_lw[0] <= row < hi_lw[1]:
                w[:, 0:2] = 0.0
            if hi_ph[0] <= row < hi_ph[1]:
                w[:, 2:5] = 0.0
            if hi_dc_l[0] <= row < hi_dc_l[1]:
                w[:, 2] = 0.0
            if hi_dc_r[0] <= row < hi_dc_r[1]:
                w[:, 3] = 0.0

            PI = 1.0 + (b_I / I_a) ** I_b
            PI = I_b * ((b_I / I_a) ** (I_b - 1.0)) / (I_a * (PI * PI))
            acc += PI * (w * pphi[:, None]).sum(axis=0)
        return acc

    n_threads = threads if threads is not None else _default_threads()
    n_threads = max(1, min(int(n_threads), 16))
    if n_I >= 64 and n_threads > 1:
        edges = [int(round(n_I * k / n_threads)) for k in range(n_threads + 1)]
        parts = [p for p in ((edges[k], edges[k + 1]) for k in range(n_threads)) if p[0] < p[1]]
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(parts)) as ex:
            results = list(ex.map(lambda rng: _accumulate(*rng), parts))
        ave = np.zeros(n_circle, dtype=float)
        for r in results:                      # 固定顺序汇总 → 结果确定
            ave += r
    else:
        ave = _accumulate(0, n_I)

    y = np.zeros(n_circle, dtype=float)
    y[0:2] = Ratiof * e * Ng * ave[0:2] / 1000.0 * 100.0
    y[2:] = Ratior * e * Ng * ave[2:] / 1000.0 * 100.0
    return y


def run_egm(cic_vals, ic_vals, *, voltage: int, egm_type: int,
            p_chunk: int = 8, threads: int | None = None) -> list[float]:
    """按 exe 的文件契约跑一次 EGM，返回 y[n_circle]（= result_main.txt 的一行值）。

    cic_vals：cic 文件里的数值（前 2*n_circle 个有效）
    ic_vals ：Ic 文件里的 7 个数值：Ng, 地面倾角, 电流幅值a, 电流幅值b, Ic_left, Ic_right, 建弧率e
    """
    key = (int(voltage), int(egm_type))
    item = EGM_PARAMS.get(key)
    if item is None or not item.get("verified"):
        raise EgmNotImplemented(
            f"EGM 原生引擎未覆盖（或未通过对拍验证）的组合：电压={voltage}kV egm_type={egm_type}。"
            f"已支持：{sorted(k for k, v in EGM_PARAMS.items() if v['verified'])}；"
            f"如需该组合计算，请把 LP_EGM_ENGINE 设为 wine（走 rjtzl_egm*.exe）。"
        )
    n_circle = int(item["n_circle"])
    data = [float(v) for v in cic_vals[: 2 * n_circle]]
    if len(data) < 2 * n_circle:
        raise ValueError(
            f"cic 参数不足：电压={voltage}kV egm_type={egm_type} 需要 {2 * n_circle} 个值，只有 {len(data)} 个"
        )
    cic = np.array(data, dtype=float).reshape(2, n_circle).T
    if len(ic_vals) < 7:
        raise ValueError(f"Ic 参数不足：需要 7 个值（Ng/倾角/a/b/Ic左/Ic右/建弧率），只有 {len(ic_vals)} 个")
    Ng, thetaslop, I_a, I_b, Ic_l, Ic_r, e = [float(v) for v in ic_vals[:7]]
    y = egm_double_x(cic=cic, n_circle=n_circle, Im=item["Im"], If=item["If"],
                     Ratiof=item["Ratiof"], Ratior=item["Ratior"], e=e, Ng=Ng,
                     thetaslop=thetaslop, I_a=I_a, I_b=I_b, Ic_left=Ic_l,
                     Ic_right=Ic_r, u_type=item["u_type"], u_voltage=item["u_voltage"],
                     u_jixing=item["u_jixing"], p_chunk=p_chunk, threads=threads,
                     wire_formula=item.get("wire_formula", "ieee"))
    return [float(v) for v in y]
