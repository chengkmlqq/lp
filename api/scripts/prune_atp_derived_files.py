"""清理 ATP 资产里的派生文件，把防雷计算链路固定为「atp + dat -> LCC -> pch -> lib」。

背景（2026-11-08）：
  旧版（$INCLUDE *.lib）模型的资产目录里同时存着 .lib / .pch。每轮任务开始时
  `_materialize_asset_files` 会把它们原样带进引擎目录，一旦 LCC 没跑成功
  （KILL=84 导线坐标重合、缺几何跳过重算、路径写法导致 ATP 退出……），
  ATP 就直接把上一轮的 pch/lib 当成本轮产物，任务"成功"但几何是旧的。

  实测（110/ganzi/fanji/M123，删掉 pch/lib 后重建）：
    LCC 4×2 秒重算 → 生成的 lib 与原 lib MD5 完全一致，主仿真正常出 pl4。
  说明 dat 是唯一信息源，lib/pch 纯派生，删掉不会丢信息。

保留规则（按 work.atp 形态判定）：
  legacy（$INCLUDE *.lib）: work.atp + long/short/dahao/xiaohao.dat
  insert（$INSERT *.pch）  : work.atp + 被引用的 pch + 4 个标准 dat
  embed/mixed              : work.atp + 4 个标准 dat + 现有 pch（保守，不动 pch）
  work.acp 是 ATPDraw 工程源文件，不参与计算；导入校验已不再接收 .acp，
  存量也一并清掉（KEEP_ACP=1 可保留，用于仍要拿回 ATPDraw 编辑的场合）。

用法（容器内执行）：
  docker exec -w /app -e PYTHONPATH=/app lp-wine-worker \
      python /app/scripts/prune_atp_derived_files.py            # dry-run
  docker exec -w /app -e PYTHONPATH=/app lp-wine-worker \
      python /app/scripts/prune_atp_derived_files.py --apply    # 备份后真删
  SKIP_KV=115,230 可跳过仍有任务在跑的电压等级（脚本幂等，可反复执行）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("ATP_ASSET_ROOT", "/app/data/vfs/atp-assets"))
BACKUP_ROOT = Path(os.environ.get("ATP_BACKUP_ROOT", "/app/data/backup_atp_cleanup"))
APPLY = "--apply" in sys.argv
SKIP = {x for x in os.environ.get("SKIP_KV", "").split(",") if x}
PURGE_ACP = os.environ.get("KEEP_ACP", "") != "1"

INS_RE = re.compile(r"^\s*\$INSERT\s*,?\s*(.+)$", re.I | re.M)
INC_RE = re.compile(r"^\s*\$INCLUDE\s*,?\s*(.+)$", re.I | re.M)
STD_DAT = {"long.dat", "short.dat", "dahao.dat", "xiaohao.dat"}


def detect_and_refs(atp: Path) -> tuple[str, list[str], list[str]]:
    raw = atp.read_bytes().decode("gbk", errors="replace")
    ins = [os.path.basename(x.replace("\\", "/")).strip() for x in INS_RE.findall(raw)]
    inc = [os.path.basename(x.replace("\\", "/")).strip() for x in INC_RE.findall(raw)]
    if ins and not inc:
        fmt = "insert"
    elif inc and not ins:
        fmt = "legacy"
    elif ins and inc:
        fmt = "mixed"
    else:
        fmt = "embed"
    return fmt, ins, inc


def plan() -> list[dict]:
    rows: list[dict] = []
    for d in sorted(ROOT.glob("*/*/*/*")):
        atp = d / "work.atp"
        if not atp.is_file():
            continue
        kv = d.relative_to(ROOT).parts[0]
        files = {f.name for f in d.iterdir() if f.is_file()}
        fmt, ins, _ = detect_and_refs(atp)

        keep = {n for n in files if n.lower().endswith(".atp")} | (files & STD_DAT)
        if fmt == "insert":
            keep |= {n for n in ins if n in files}
        elif fmt in ("mixed", "embed"):
            keep |= {n for n in files if n.lower().endswith(".pch")}
        if not PURGE_ACP:
            keep |= {n for n in files if n.lower().endswith(".acp")}

        drop = sorted(files - keep)
        rows.append({
            "dir": str(d), "kv": kv, "fmt": fmt, "keep": sorted(keep), "drop": drop,
            "bytes": sum((d / n).stat().st_size for n in drop),
            "skipped": kv in SKIP,
        })
    return rows


def main() -> None:
    if not ROOT.is_dir():
        print("资产根目录不存在：%s" % ROOT)
        raise SystemExit(2)

    rows = plan()
    per_kv: dict[str, Counter] = defaultdict(Counter)
    del_files = del_bytes = 0
    for r in rows:
        if r["skipped"]:
            continue
        per_kv[r["kv"]][r["fmt"]] += 1
        del_files += len(r["drop"])
        del_bytes += r["bytes"]

    print("== 形态分布（全部 %d 个资产）==" % len(rows))
    for k, v in Counter(r["fmt"] for r in rows).most_common():
        print("   %-8s %d" % (k, v))

    print("\n== 待清理（SKIP=%s）==" % (sorted(SKIP) or "无"))
    for kv in sorted(per_kv, key=lambda x: (len(x), x)):
        sub = [r for r in rows if r["kv"] == kv and not r["skipped"]]
        print("   %-5s 资产 %3d  删除 %4d 个文件  %7.1f MB  形态=%s" % (
            kv, len(sub), sum(len(r["drop"]) for r in sub),
            sum(r["bytes"] for r in sub) / 1e6, dict(per_kv[kv])))
    print("\n合计：删除 %d 个文件，%.1f MB" % (del_files, del_bytes / 1e6))

    problems = []
    for r in rows:
        if r["skipped"]:
            continue
        names = {Path(x).name for x in r["keep"]}
        if r["fmt"] == "legacy" and not STD_DAT <= names:
            problems.append((r["dir"], "legacy 缺 dat: %s" % sorted(STD_DAT - names)))
    print("\n== 异常资产 %d 个 ==" % len(problems))
    for p in problems[:20]:
        print("   ", p[0].replace(str(ROOT) + "/", ""), "->", p[1])

    if not APPLY:
        print("\n(dry-run，未删除任何文件；加 --apply 执行)")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    tar_path = BACKUP_ROOT / ("atp_assets_pruned_%s.tar.gz" % ts)
    manifest_path = BACKUP_ROOT / ("atp_assets_pruned_%s.json" % ts)
    todo = [r for r in rows if not r["skipped"] and r["drop"]]
    with tarfile.open(tar_path, "w:gz") as tar:
        for r in todo:
            for n in r["drop"]:
                p = Path(r["dir"]) / n
                tar.add(str(p), arcname=str(p.relative_to(ROOT)))
    print("\n备份：%s (%.1f MB)" % (tar_path, tar_path.stat().st_size / 1e6))

    removed = 0
    for r in todo:
        for n in r["drop"]:
            try:
                (Path(r["dir"]) / n).unlink()
                removed += 1
            except FileNotFoundError:
                pass
    manifest_path.write_text(json.dumps(
        {"at": ts, "backup": str(tar_path), "removed": removed,
         "items": [{"dir": r["dir"], "fmt": r["fmt"], "drop": r["drop"]} for r in todo]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("已删除 %d 个文件；清单：%s" % (removed, manifest_path))


if __name__ == "__main__":
    main()
