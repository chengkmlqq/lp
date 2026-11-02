"""ATPDraw 模型形态识别 + 上传包预检 + 7.3 参数段规范化。

## 为什么需要这个模块

老版 ATPDraw（6.x / 7.0 / 7.1）产物用 DBM 形态，几何通过 `.lib` 间接引用：

    $INCLUDE, D:\\ATP\\110\\ganzi\\fanji\\M123\\long.lib, X0245A, X0245B, X0245C $$

节点名写在 work.atp 里，`.lib` 内部是占位名 `IN___A`，LP 每轮
`dat → LCC → pch → pch_to_lib → lib` 重算几何，链路完整。

新版 ATPDraw（7.2+）产物用 `$INSERT` 形态，几何通过序号 pch 直接引用：

    $INSERT, D:\\ATP\\work\\results\\long3.pch

没有参数位、不排序，**节点名的唯一载体是 pch 脚卡**（前 24 列）。pch 由
ATPDraw 内置 LCC 生成，LP 无法命令行复现，因此几何只能随包上传、不能重算。

## 依据（2026-11-02 实测）

- `D:\\ATP` 全量 1101 个模型：618 个 `$INCLUDE + .lib`，483 个 `$INSERT + 序号 pch`
- 483 个里有 204 个跑不起来（pch 缺失 / 参数段残缺 / pch 被其他工程覆盖）
- 7.3 的 `$PARAMETER` 段有三处引擎不兼容：行尾 `$$`、整数无小数点、
  中间变量引用数超 `List31=10`；三处规范化后 `rc=0`、`pl4` 有波形
- **`$INSERT` 引用的 pch 缺失时引擎仍返回 rc=0、pl4=0 字节**，只在 `.lis` 里留
  `Failure to connect disk file in CIMAGE. Halt.` —— 所以 pch 完整性必须在上传口校验

## 模块职责边界

本模块只做「识别 + 检查 + 文本变换」，**不读数据库、不碰存储、不调引擎**。
调用方拿到 `PackageInspection` 后自行决定拒收（`has_error`）还是落库展示。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# ── 形态常量 ────────────────────────────────────────────────────────────
FORMAT_LEGACY = "legacy"      # 6.x/7.0/7.1：$INCLUDE + .lib（DBM），几何可重算
FORMAT_INSERT = "insert"      # 7.2+：$INSERT + 序号 .pch，几何随包
FORMAT_EMBED = "embed"        # 7.2+ Enbed：几何直接内嵌进 work.atp，节点名烧死
FORMAT_PLAIN = "plain"        # 无 LCC 的纯 RLC 工程 / 手写文件

FORMAT_LABELS: dict[str, str] = {
    FORMAT_LEGACY: "老版（$INCLUDE + .lib）",
    FORMAT_INSERT: "新版（$INSERT + .pch）",
    FORMAT_EMBED: "新版内嵌（几何烧死）",
    FORMAT_PLAIN: "无线路模型",
}

# 引擎代差说明：LP 用的 tpbig/mytpbig 均为 2003-09-19 源码，不认 ATPDraw 7.2+
# 引入的 `$$` 行尾注释语法，也不认 $PARAMETER 段里的整数写法。
ENGINE_NOTE = "LP 引擎（tpbig/mytpbig，2003-09-19 源码）不认 ATPDraw 7.2+ 的 `$$` 注释语法"

# ── 正则 ────────────────────────────────────────────────────────────────
# $INSERT 卡：`$INSERT, D:\ATP\work\results\long3.pch`（逗号可有可无）
_INSERT_RE = re.compile(r"(?mi)^[ \t]*\$INSERT[ \t]*[,]?[ \t]*([^\s,]*)")

# $INCLUDE 卡引用 .lib（DBM 形态）
_INCLUDE_LIB_RE = re.compile(r"(?mi)^[ \t]*\$INCLUDE[ \t]*[,]?[^\n]*?\.lib\b")

# pch 分支头脚卡：`-1X0133AXXSS2A`（7.3 真实名）/ `-1IN___AOUT__A`（老式占位名）
# 编号 ≥10 时无负号（`10IN___JOUT__J`），故负号可选。
# 尾部要求至少 4 个 [A-Z0-9_]，避免把 `2E5` 这类数值行误判成脚卡。
_PCH_HEAD_RE = re.compile(r"^-?\d+[A-Z][A-Z0-9_]{3,}")

# $PARAMETER 段一行：`NAME =VALUE $$` / `NAME =NAME_I` / `NAME=VALUE`
_PARAM_LINE_RE = re.compile(
    r"^[ \t]*([A-Za-z][A-Za-z0-9_]*)[ \t]*=[ \t]*([^\s$]*)[ \t]*(?:\$\$.*)?$"
)
# 数值：必须接受尾点写法（老模型实测有 `RER001=5.` / `RELE10=7.`），
# 否则会被当成「别名引用标识符」而误报 E013。
_NUMERIC_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")

# 四个标准几何源（LP 的 dat 命名约定）
STANDARD_DAT_NAMES: tuple[str, ...] = ("long", "short", "dahao", "xiaohao")
ENTRY_ATP_NAME = "work.atp"

# 中间变量命名：7.3 用 `NAMEI`（如 `U2I` / `REIAMPI` / `PHAGAI`），
# 别名则用下划线填充到固定宽度（如 `PHAGA_____` / `REHG______`）。
# 因此判据是「以 I 结尾且不以 _ 结尾」，不能简单用 `_I` 后缀（实测对不上）。
# 兜底再加一条「带行尾 $$」——7.3 的中间变量全部带 $$，别名全不带。
def _is_intermediate_name(name: str, line: str) -> bool:
    if "$$" in line:
        return True
    upper = name.upper()
    return upper.endswith("I") and not upper.endswith("_")


# ── 数据结构 ────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Issue:
    """一条校验结论。level=error 拒收；level=warning 放行但列入待办。"""

    code: str
    level: str          # "error" | "warning"
    message: str        # 一句话说清"哪里不对"
    fix_hint: str       # 人工怎么改（必须可执行，不能是"请检查模型"）
    file: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "message": self.message,
            "fix_hint": self.fix_hint,
            "file": self.file,
        }


@dataclass(slots=True)
class ParamSection:
    """$PARAMETER 段解析结果。"""

    intermediates: dict[str, str] = field(default_factory=dict)   # NAME_I → 原始值
    aliases: dict[str, str] = field(default_factory=dict)         # NAME → 值或中间变量名
    unresolved: list[tuple[str, str]] = field(default_factory=list)  # (别名, 引用名)
    dollar_lines: int = 0        # 带行尾 $$ 的行数
    bare_int_values: int = 0     # 无小数点的整数值条数

    @property
    def count(self) -> int:
        return len(self.intermediates) + len(self.aliases)


@dataclass(slots=True)
class PackageInspection:
    """上传包预检结果（可直接序列化进 atp_asset.format_check_json）。"""

    model_format: str
    entry_path: str | None = None
    insert_refs: list[str] = field(default_factory=list)
    include_refs: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def has_error(self) -> bool:
        return any(issue.level == "error" for issue in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    def add(self, code: str, level: str, message: str, fix_hint: str, file: str | None = None) -> None:
        self.issues.append(Issue(code=code, level=level, message=message, fix_hint=fix_hint, file=file))

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_format": self.model_format,
            "format_label": FORMAT_LABELS.get(self.model_format, self.model_format),
            "entry_path": self.entry_path,
            "insert_refs": list(self.insert_refs),
            "include_refs": list(self.include_refs),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.as_dict() for i in self.issues],
            "stats": dict(self.stats),
        }

    def error_summary(self, limit: int = 6) -> str:
        """给 HTTPException.detail 用的一句话摘要（含修复提示）。"""
        errs = self.errors
        head = "；".join(f"[{i.code}] {i.message} → {i.fix_hint}" for i in errs[:limit])
        tail = f"（另有 {len(errs) - limit} 条）" if len(errs) > limit else ""
        return head + tail


# ── 形态识别 ────────────────────────────────────────────────────────────
def _decode(content: bytes) -> str:
    """work.atp 含 GBK 中文注释，按 UTF-8 → GBK 依次尝试。"""
    for encoding in ("utf-8", "gbk"):
        try:
            return content.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("gbk", errors="replace")


def insert_pch_refs(text: str) -> list[str]:
    """抽出 $INSERT 引用的 pch 文件名（只取 basename，去重保序）。

    只取文件名是刻意的：ATPDraw 把 pch 写到全局共享目录
    `ATPDraw.ini [Directories] ATP=C:\\ATP\\work\\results\\`，所有工程共用同 8 个
    文件名，最后写入者赢。LP 物化时按文件名在同级目录查找，不看原始路径。
    """
    names: list[str] = []
    for match in _INSERT_RE.finditer(text):
        raw = (match.group(1) or "").strip().strip('"')
        if not raw:
            continue
        name = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if name.lower().endswith(".pch") and name not in names:
            names.append(name)
    return names


def include_lib_refs(text: str) -> list[str]:
    names: list[str] = []
    for match in _INCLUDE_LIB_RE.finditer(text):
        line = match.group(0)
        name = line.replace("\\", "/").rsplit("/", 1)[-1].strip()
        name = re.sub(r"(?i)[^a-z0-9_.\-].*$", "", name)
        if name and name not in names:
            names.append(name)
    return names


def detect_model_format(text: str) -> str:
    """判定 work.atp 的几何引用形态。

    判据按**引用形态**而非版本指纹大小写 —— 版本指纹的大小写对应的是 ATPDraw
    6.x/7.x 两代输出模板，而 DBM 被移除发生在 7.2：7.1 会写出混合大小写指纹
    但仍是 `$INCLUDE + .lib` 形态。
    """
    has_insert = bool(_INSERT_RE.search(text))
    has_include_lib = bool(_INCLUDE_LIB_RE.search(text))
    if has_insert and has_include_lib:
        return FORMAT_INSERT  # 混合形态，由 inspect 侧报 E012
    if has_insert:
        return FORMAT_INSERT
    if has_include_lib:
        return FORMAT_LEGACY
    # 两者都没有：7.x 指纹 → Enbed 形态（几何烧死）；否则视为无 LCC 工程
    head = "\n".join(text.splitlines()[:10])
    if "Generated by ATPDraw" in head:
        return FORMAT_EMBED
    return FORMAT_PLAIN


# ── $PARAMETER 段解析 ───────────────────────────────────────────────────
def parse_parameter_section(text: str) -> ParamSection:
    """解析 $PARAMETER 段。

    7.3 的段由两类行组成：55 条中间变量（`U2I =500 $$`）+ 29 条别名
    （`PHAGA_____=PHAGAI`）。**必须按此顺序理解**：别名引用中间变量，若先解别名
    拿到的是 `REIAMPI` 这样的名字，再当数值用会产出 `REAA1I.` 这类坏值。
    老模型则是单层 `RER001=5.`（右侧直接是数值，无中间变量）。
    """
    section = ParamSection()
    in_params = False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if stripped.upper() == "$PARAMETER":
            in_params = True
            continue
        if not in_params:
            continue
        if stripped.upper().startswith("BLANK $PARAMETER") or stripped.upper() in ("$ENDBR", "BLANK"):
            break
        if not stripped:
            continue
        if "$$" in stripped:
            section.dollar_lines += 1
        match = _PARAM_LINE_RE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if not value:
            continue
        if _NUMERIC_RE.match(value) and "." not in value and "e" not in value.lower():
            section.bare_int_values += 1
        if _is_intermediate_name(name, stripped):
            section.intermediates[name] = value
        else:
            section.aliases[name] = value
    # 解析别名引用：右侧不是数字 → 视为对中间变量的引用
    for name, value in list(section.aliases.items()):
        if _NUMERIC_RE.match(value):
            continue
        if value in section.intermediates:
            continue
        section.unresolved.append((name, value))
    return section


def resolve_param_values(section: ParamSection) -> dict[str, str]:
    """把别名解成最终数值。未解析的引用保留原值（由校验层报 E013）。"""
    out: dict[str, str] = {}
    for name, value in section.aliases.items():
        if _NUMERIC_RE.match(value):
            out[name] = value
            continue
        resolved = section.intermediates.get(value)
        if resolved is not None and _NUMERIC_RE.match(resolved):
            out[name] = resolved
    return out


# ── 参数段规范化（7.3 → 引擎可解析形态）────────────────────────────────
def _format_number(value: str) -> str:
    """规范化数值：整数补小数点、整值浮点去掉多余零。

    `1000` → `1000.`（不补点会被按整数格式解析，报 `KONST = N`）。
    """
    text = value.strip()
    if not text:
        return text
    if not _NUMERIC_RE.match(text):
        return text
    if "." in text or "e" in text.lower():
        return text
    return text + "."


def normalize_parameter_section(text: str) -> tuple[str, dict[str, Any]]:
    """把 $PARAMETER 段重写成引擎可解析形态，其余段落逐字节保留。

    三步（顺序不可换）：
      ① 解析 55 条中间变量 → 值表
      ② 把 29 条别名的右值内联成 ① 的数值
      ③ 整体重写为 `NAME=值`，值带小数点、无 `$$`

    为什么必须内联：引用型变量数超过 `List31=10` 会触发 CIDEAL 报错；
    实测 84 行 → 29 行后通过。

    返回 (新文本, 诊断)。诊断里的 `unresolved` 非空表示模板残缺，
    调用方应中止而不是硬跑（否则 TACS 会报 `XXX` 找不到）。
    """
    lines = text.splitlines(keepends=True)
    section = parse_parameter_section(text)
    values = resolve_param_values(section)

    diagnostics: dict[str, Any] = {
        "intermediates": len(section.intermediates),
        "aliases": len(section.aliases),
        "resolved": len(values),
        "unresolved": [{"name": n, "ref": r} for n, r in section.unresolved],
        "dollar_lines": section.dollar_lines,
        "bare_int_values": section.bare_int_values,
        "rewritten": False,
    }
    if not section.intermediates:
        # 没有中间变量 → 老式 `NAME=值` 模板，原样返回。
        # 重写只会改变行尾/空行，对引擎无收益，反而破坏与 C# 产物的逐字节一致性。
        return text, diagnostics
    if section.unresolved:
        # 残缺模板：不产出半成品（半成品会让 TACS 在更靠后的位置失败，更难定位）
        return text, diagnostics

    out: list[str] = []
    inserted = False
    in_params = False
    for raw in lines:
        line = raw.rstrip("\r\n")
        ending = raw[len(line):]
        stripped = line.strip()
        if stripped.upper() == "$PARAMETER":
            in_params = True
            out.append(raw)
            continue
        if in_params and (stripped.upper().startswith("BLANK $PARAMETER")
                          or stripped.upper() in ("$ENDBR", "BLANK")):
            if not inserted:
                # 段落末尾统一写出（保持原段落位置，不打乱后续段）
                out.extend(f"{name}={_format_number(value)}\n" for name, value in values.items())
                inserted = True
            in_params = False
            out.append(raw)
            continue
        if in_params:
            if not stripped:
                continue  # 段内空行丢弃（重写后不需要）
            continue      # 段内旧行一律丢弃，由块尾统一写出
        out.append(raw)

    if in_params and not inserted:  # 段尾没有 BLANK 标记的容错分支
        out.extend(f"{name}={_format_number(value)}\n" for name, value in values.items())
        inserted = True

    diagnostics["rewritten"] = inserted
    return "".join(out), diagnostics


# ── 上传包预检 ──────────────────────────────────────────────────────────
def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _lower_index(names: Iterable[str]) -> dict[str, str]:
    return {name.lower(): name for name in names}


def inspect_package(
    members: dict[str, bytes],
    *,
    entry_name: str = ENTRY_ATP_NAME,
) -> PackageInspection:
    """校验一个上传包（已在内存里的 相对路径 → 内容）。

    members 的 key 用相对路径、value 用原始字节。函数只读，不写盘。

    错误级（拒收，人工改完再传）：
      E001 缺入口 work.atp
      E010 `$INSERT` 引用的 pch 不在包内
      E011 pch 是残包（无分支头脚卡）
      E012 混合形态（$INSERT + $INCLUDE .lib 同时存在）
      E013 $PARAMETER 段有别名引用不到中间变量（TACS 必报找不到）
      E014 Enbed 形态（几何烧死，无法按塔重算）
      E002 legacy 形态缺标准 .dat

    警告级（放行，但会展示给人工）：
      W001 行尾带 `$$`（LP 会规范化）
      W002 整数值无小数点（LP 会补点）
      W003 中间变量超过 List31 上限（LP 会内联）
      W010 包内带 .pch 但形态是 legacy（多余文件，仿真不使用）
      W011 work.atp 引用的 pch 路径目录与包内不一致（LP 按文件名物化）
    """
    lower_map = _lower_index(members.keys())
    entry_key = lower_map.get(entry_name.lower())
    if entry_key is None:
        atps = [p for p in members if p.lower().endswith(".atp")]
        if len(atps) == 1:
            entry_key = atps[0]
        else:
            result = PackageInspection(model_format=FORMAT_PLAIN)
            result.add(
                "E001", "error",
                f"包内没有 {entry_name}，且 .atp 文件数为 {len(atps)}（必须恰好一个）",
                f"把仿真入口重命名为 {entry_name} 后重新打包",
            )
            return result

    text = _decode(members[entry_key])
    model_format = detect_model_format(text)
    insert_refs = insert_pch_refs(text)
    include_refs = include_lib_refs(text)

    result = PackageInspection(
        model_format=model_format,
        entry_path=entry_key,
        insert_refs=insert_refs,
        include_refs=include_refs,
    )

    pch_members = {_basename(p).lower(): p for p in members if p.lower().endswith(".pch")}
    dat_members = {_basename(p).lower(): p for p in members if p.lower().endswith(".dat")}
    section = parse_parameter_section(text)

    result.stats.update({
        "atp_bytes": len(members[entry_key]),
        "atp_lines": len(text.splitlines()),
        "param_intermediates": len(section.intermediates),
        "param_aliases": len(section.aliases),
        "param_dollar_lines": section.dollar_lines,
        "param_bare_int_values": section.bare_int_values,
        "pch_files": len(pch_members),
        "dat_files": len(dat_members),
    })

    # ── E012 混合形态 ──
    if insert_refs and include_refs:
        result.add(
            "E012", "error",
            f"同时存在 $INSERT（{len(insert_refs)} 条）与 $INCLUDE .lib（{len(include_refs)} 条）",
            "同一个工程里两种几何引用只能留一种：删掉多余的 $INSERT 段或 $INCLUDE 段后重新导出",
            entry_key,
        )

    # ── E014 Enbed 形态 ──
    if model_format == FORMAT_EMBED:
        result.add(
            "E014", "error",
            "work.atp 由 ATPDraw 7.x 生成，但既无 $INSERT 也无 $INCLUDE .lib（几何已内嵌烧死）",
            "用 ATPDraw 以 DBM/INCLUDE 方式重新导出（6.x/7.0/7.1），"
            "或用 7.2+ 的 $INSERT 方式导出（几何随 pch 上传）",
            entry_key,
        )

    # ── E010 / E011 $INSERT 引用的 pch 校验 ──
    if insert_refs:
        missing = [name for name in insert_refs if name.lower() not in pch_members]
        if missing:
            result.add(
                "E010", "error",
                f"$INSERT 引用的 {len(missing)} 个 pch 未随包上传：{', '.join(missing[:8])}",
                "ATPDraw 把 pch 写到全局共享目录（ATPDraw.ini 的 [Directories] ATP=），"
                "需从该目录把这些 pch 一起打进模型包；缺 pch 时引擎返回 rc=0 但不出波形，"
                "只在 .lis 里留 'Failure to connect disk file in CIMAGE'",
                entry_key,
            )
        for name in insert_refs:
            member = pch_members.get(name.lower())
            if member is None:
                continue
            body = _decode(members[member])
            heads = [ln for ln in body.splitlines() if _PCH_HEAD_RE.match(ln)]
            if not heads:
                result.add(
                    "E011", "error",
                    f"{name} 里没有任何分支头脚卡（0 行），是半截文件",
                    "该 pch 没有写完就打包了。重新在 ATPDraw 里执行一次 RunATP 生成 pch 后再打包",
                    member,
                )
                continue
            result.stats.setdefault("pch_heads", {})[name] = len(heads)
        # W011：引用路径目录与包内结构不一致（只提示，不影响物化）
        dirs = set()
        for match in _INSERT_RE.finditer(text):
            raw = (match.group(1) or "").strip().strip('"')
            if raw and "\\" in raw:
                dirs.add(raw.replace("\\", "/").rsplit("/", 1)[0])
        if len(dirs) > 1:
            result.add(
                "W011", "warning",
                f"$INSERT 的 pch 来自 {len(dirs)} 个不同目录：{', '.join(sorted(dirs)[:3])}",
                "不同目录的 pch 可能是别的工程留下的。LP 只按文件名物化，"
                "请确认这些 pch 确实属于本工程（对比导体数和坐标）",
                entry_key,
            )

    # ── E002 legacy 形态缺标准 .dat ──
    if model_format == FORMAT_LEGACY:
        missing_dat = [n for n in STANDARD_DAT_NAMES if f"{n}.dat" not in dat_members]
        if missing_dat:
            result.add(
                "E002", "error",
                "老版模型缺少几何源：" + ", ".join(f"{n}.dat" for n in missing_dat),
                "老版模型每轮要从 .dat 重算几何，四个 .dat 必须齐全（long/short/dahao/xiaohao）",
                entry_key,
            )

    # ── E013 / W001 / W002 / W003 参数段 ──
    if section.unresolved:
        preview = "；".join(f"{n} ← 缺 {r}" for n, r in section.unresolved[:6])
        result.add(
            "E013", "error",
            f"$PARAMETER 段有 {len(section.unresolved)} 个别名引用不到中间变量：{preview}",
            "模板里只留下了 `NAME =NAME_I` 别名，没有对应的 `NAME_I =值` 定义行。"
            "需要在 ATPDraw 里重新导出完整参数段，或手工补齐被引用的中间变量",
            entry_key,
        )
    if section.dollar_lines:
        result.add(
            "W001", "warning",
            f"$PARAMETER 段有 {section.dollar_lines} 行带行尾 `$$`（7.2+ 新增的注释语法）",
            f"{ENGINE_NOTE}，带 `$$` 会报 FMT 错误。LP 仿真时会自动去掉，无需人工修改",
            entry_key,
        )
    if section.bare_int_values:
        result.add(
            "W002", "warning",
            f"$PARAMETER 段有 {section.bare_int_values} 个整数值没写小数点",
            "无小数点会被引擎按整数格式解析并报 `KONST = N`。LP 仿真时会自动补点，"
            "但若其他工具也用这份模型，建议在源模板里补成 `1000.`",
            entry_key,
        )
    if len(section.intermediates) > 10:
        result.add(
            "W003", "warning",
            f"$PARAMETER 段有 {len(section.intermediates)} 条中间变量（引擎 List31 上限 10）",
            "LP 仿真时会把中间变量内联进别名后再写盘，不会触发 CIDEAL；无需人工处理",
            entry_key,
        )

    # ── W010 老版模型带了 .pch ──
    if model_format == FORMAT_LEGACY and pch_members:
        result.add(
            "W010", "warning",
            f"老版模型包内带了 {len(pch_members)} 个 .pch（中间产物）",
            "老版链路每轮从 .dat 重算 pch，包内的 pch 不会被使用，可删除以减小包体",
            entry_key,
        )

    return result


# ── 仿真前依赖检查 ──────────────────────────────────────────────────────
def missing_dependencies(
    entry_text: str,
    available_pch: Iterable[str],
) -> list[str]:
    """物化之后、调引擎之前，检查 $INSERT 引用的 pch 是否都落到了运行目录。

    ⚠️ 这一步不能省：pch 缺失时引擎返回 rc=0、pl4 为 0 字节，只在 .lis 里
    留一行 `Failure to connect disk file in CIMAGE. Halt.`。只看返回码必漏判。
    """
    available = {_basename(n).lower() for n in available_pch}
    return [name for name in insert_pch_refs(entry_text) if name.lower() not in available]
