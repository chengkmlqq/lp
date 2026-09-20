"""回路相序 → 物理上/中/下相 的映射（对齐 C#）。

C# 权威依据（win-csharp 从 MyParamClass.cs 挖出并给出行号）：
  双回 1595-1716 / 四回 1403-1485：
    · 台账「上/中/下相中距（相高度）」三列承载的是 **A/B/C 三相**的值
      （C# 内部字段名就是「1回路A相中距m / B相中距m / C相中距m」）；
    · 每个回路有一个「相序」串（例：guxing = "BCA"，shangzi = "CBA"）；
    · 串的**位置 0/1/2 对应物理上/中/下相**，串上的**字母**指向读哪个相字段：
        if (strXiangXu[idHuiLu].ElementAt(0)=='B' && 名=="1回路B相中距m") m上相中距sh_m[..]=值;
        if (strXiangXu[idHuiLu].ElementAt(2)=='A' && 名=="1回路A相中距m") m下相中距sh_m[..]=值;
    ⇒ 物理上/中/下 = 台账列[字母]，字母 A→上列、B→中列、C→下列。

    例：guxing 相序 BCA ⇒ 物理上←中列、物理中←下列、物理下←上列。

LP 此前**直接按 上/中/下 位置**取用，忽略相序 → 相序非 ABC 的塔型整体错位。
只有 guxing 暴露：ganzi/jiubei 相序 ABC（恒等）、shangzi/maotou 相序 CBA 但 A≡C
（中距 7/7、高度 17/17）→ 字母映射与位置映射结果相同，bug 被掩盖。
"""

from typing import Any, Mapping

_POS = ("upper", "middle", "lower")
_COL_OF = {"A": "upper", "B": "middle", "C": "lower"}
_CIRCUIT_INDEX = {"I": 1, "II": 2, "III": 3, "IV": 4}


def phase_sequence(profile: Mapping[str, Any] | None, circuit_index: int = 1) -> list[str]:
    """取某回路的相序串（缺省 ABC = 恒等，与 C# 默认语义一致）。"""
    raw = str((profile or {}).get(f"phase_sequence_{circuit_index}") or "").strip().upper()
    seq = [c for c in raw if c in ("A", "B", "C")]
    return seq if len(seq) >= 3 else ["A", "B", "C"]


def permute_layer(layer: Mapping[str, Any] | None, seq: list[str]) -> dict[str, Any]:
    """把单回路的「A/B/C 三列」按相序重排为「物理上/中/下」。返回新 dict。"""
    out: dict[str, Any] = {}
    for key, group in (layer or {}).items():
        if not isinstance(group, dict):
            out[key] = group
            continue
        out[key] = {pos: group.get(_COL_OF[seq[i]]) for i, pos in enumerate(_POS)}
    return out


def permute_circuit_geometry(cg: Mapping[str, Any] | None,
                             profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """对整个 circuit_geometry_json 逐回路应用相序映射。返回新 dict。"""
    out: dict[str, Any] = {}
    for cid, layer in (cg or {}).items():
        idx = _CIRCUIT_INDEX.get(str(cid))
        seq = phase_sequence(profile, idx) if idx else ["A", "B", "C"]
        out[cid] = permute_layer(layer, seq) if isinstance(layer, dict) else layer
    return out
