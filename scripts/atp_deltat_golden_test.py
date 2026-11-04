"""dT 自适应适配器金测：用 35kV 塔 2 真实场景（RELE04=0.8m）驱动。

用法（仓库根目录）：python scripts/atp_deltat_golden_test.py
样本：D:/ATP/35/shangzi/raoji2/M123/work.atp（模板 RELE0x=500 默认值），
另构造 RELE04=0.8 的渲染后形态复现 KILL=29 场景。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.services.atp_deltat_adapter import (  # noqa: E402
    AtpDataError,
    adapt_deltat,
    analyze_distributed_lines,
)

SAMPLE = Path("D:/ATP/35/shangzi/raoji2/M123/work.atp")


def dt_of(text: str) -> str:
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if "C  dT  >< Tmax >" in l:
            return lines[i + 1].split()[0]
    raise AssertionError("找不到 dT 行")


def main() -> int:
    text = SAMPLE.read_text(encoding="gbk", errors="replace")
    failures: list[str] = []

    # 用例 1：模板默认值（RELE0x=500 → 行程 2μs）→ 不改写
    r1 = adapt_deltat(text)
    print(f"[1] 模板默认值：changed={r1.changed} dT={dt_of(r1.atp_text)}")
    print(f"    支路数={len(r1.lines)} notes={r1.notes}")
    if r1.changed:
        failures.append("用例1 不应改写")

    # 用例 2：塔 2 真实场景 RELE04=0.8 → 行程 3.2ns，期望 dT 收窄至 1.6ns
    text2 = text.replace("RELE04=500.", "RELE04=0.8")
    r2 = adapt_deltat(text2)
    short = [l for l in r2.lines if l.length_source == "param:RELE04"]
    print(f"[2] RELE04=0.8：changed={r2.changed} dT={dt_of(r2.atp_text)} "
          f"t_min={r2.t_min * 1e9 if r2.t_min else None:.2f}ns"
          if r2.t_min else "[2] t_min 缺失")
    print(f"    最短支路={short[0].node_a}-{short[0].node_b} L={short[0].length} "
          f"v={short[0].velocity:g} t={short[0].travel_time * 1e9:.2f}ns")
    print(f"    改后数值行：{r2.atp_text.splitlines()[[i for i,l in enumerate(r2.atp_text.splitlines()) if 'C  dT' in l][0] + 1]!r}")
    if not r2.changed:
        failures.append("用例2 应改写")
    elif abs(r2.new_dt - 1.6e-9) > 1e-12:
        failures.append(f"用例2 dT 期望 1.6e-9，实际 {r2.new_dt}")

    # 用例 3：幂等——对已收窄的文本再跑一次不再变化
    r3 = adapt_deltat(r2.atp_text)
    print(f"[3] 幂等重跑：changed={r3.changed} dT={dt_of(r3.atp_text)}")
    if r3.changed:
        failures.append("用例3 应幂等")

    # 用例 4：病态短支路（0.05m → 行程 0.2ns → dT=0.1ns < 0.2ns 下限）→ 报错
    text4 = text.replace("RELE04=500.", "RELE04=0.05")
    try:
        adapt_deltat(text4)
        failures.append("用例4 应抛 AtpDataError")
    except AtpDataError as exc:
        print(f"[4] 病态支路报错：{exc}")

    # 用例 5：数值直写长度（支路行 RELE05 换成字面量 0.4）
    text5 = re.sub(
        r"(2\.5E8)RELE05", r"\g<1>0.4",
        text.replace("RELE05=500.", "RELE05=0.4"),
    )
    r5 = adapt_deltat(text5)
    lit = [l for l in r5.lines if l.length_source == "literal"]
    print(f"[5] 数值直写：literal 支路数={len(lit)} changed={r5.changed} "
          f"dT={dt_of(r5.atp_text)}")
    if not lit:
        failures.append("用例5 未识别字面量长度")

    # 用例 6：Tmax/后续列不被破坏
    row2 = r2.atp_text.splitlines()
    for i, l in enumerate(row2):
        if "C  dT  >< Tmax >" in l:
            tail = row2[i + 1][8:]
            orig_tail = text.splitlines()[text.splitlines().index(
                next(x for x in text.splitlines() if "C  dT" in x)) + 1][8:]
            print(f"[6] dT 行第 8 列之后保持不变：{tail!r}")
            if tail != orig_tail:
                failures.append("用例6 后续列被破坏")
            break

    print()
    if failures:
        print("FAIL：")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
