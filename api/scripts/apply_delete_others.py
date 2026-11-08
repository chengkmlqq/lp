"""严格按 C# `1 delete_others.py` 的逻辑处理模型：删掉 `$PARAMETER` 与 `RER001=RER001I` 之间的变量替换段。

C# 原脚本（桌面 `1 delete_others.py`）就三步：
    pos_start = content.find("$PARAMETER") + 10
    pos_end   = content.find("RER001=RER001I")
    content   = content[:pos_start] + "\\n" + content[pos_end:]

本脚本逐字节照做，只加两处护栏（都不改变「删段」这一语义）：
1. 编码：work.atp 是 GBK，按 utf-8 → gbk 依次尝试解码，原编码写回，避免中文注释变问号。
2. 非 `$$` 行保护：个别模型（如 115/maotou/raoji1）在该区间里混了 `ZRE01_=ZRE01I` 这类
   **不带 `$$`** 的参数行，它们不是「变量替换装饰」而是被卡片引用的真实参数。硬删会让
   引擎报未定义变量，故这类行保留并按其定义烘焙成数值（`ZRE01_=150.`）。
   纯 `$$` 行照脚本原样删除，一个不留。

其余行为与脚本一致：段落之外逐字节不动，`RER001=RER001I` 及其后的别名块整体保留。

【安全 / 幂等】
- 默认 dry-run，`--apply` 才写；写前备份（tar.gz + json）。
- `--restore-from <tar>`：先从备份里取回原始 work.atp 再处理（用于回退上一次「烘焙」的结果）。
- 已处理过的文件（区间内已无 `$$`）会跳过，可重复执行。
- 写完重跑 `inspect_package`，把 model_format / format_check_json 落库。

【用法】
    python apply_delete_others.py --restore-from /app/data/backup_atp_cleanup/atp_param_bake_20261108_124846.tar.gz
    python apply_delete_others.py --restore-from ... --apply
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import sys
import tarfile
import time
from datetime import datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.atp_asset import AtpAsset
from app.services.atp_asset_service import (
    _build_driver_or_400,
    _resolve_asset_file_location,
    _resolve_mount,
    _walk_storage_tree,
    collect_check_members_from_storage,
)
from app.services.atp_model_format import (
    _format_number,
    inspect_package,
    parse_parameter_section,
    resolve_param_values,
)

BACKUP_DIR = "/app/data/backup_atp_cleanup"
ANCHOR = "RER001=RER001I"
MARKER = "$PARAMETER"
PARAM_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(\S*)\s*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按 1 delete_others.py 的逻辑删参数替换段")
    parser.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    parser.add_argument("--prefix", default="ATP115,ATP230", help="资产 code 前缀，逗号分隔")
    parser.add_argument("--restore-from", default="", help="先从这个备份 tar 取回原始 work.atp")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=不限）")
    parser.add_argument("--show", type=int, default=10, help="打印多少条明细")
    return parser.parse_args()


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def delete_others(text: str) -> tuple[str, dict]:
    """C# 逻辑 + 非 `$$` 行保护。返回 (新文本, 统计)。"""
    pos = text.find(MARKER)
    anchor = text.find(ANCHOR)
    if pos < 0 or anchor < 0 or anchor < pos:
        return text, {"skipped": "no_marker"}
    start = pos + len(MARKER)          # C#: pos + 10
    region = text[start:anchor]
    if "$$" not in region:
        return text, {"skipped": "no_dollar"}

    section = parse_parameter_section(text)
    resolved = resolve_param_values(section)
    intermediates = section.intermediates

    keep: list[str] = []
    kept_alias: list[str] = []
    for raw in region.splitlines():
        stripped = raw.strip()
        if not stripped or "$$" in stripped:
            continue
        match = PARAM_LINE_RE.match(stripped)
        if not match:
            keep.append(stripped)
            continue
        name, value = match.group(1), match.group(2)
        if value in resolved:
            keep.append(f"{name}={_format_number(resolved[value])}")
            kept_alias.append(name)
        elif value in intermediates:
            keep.append(f"{name}={_format_number(intermediates[value])}")
            kept_alias.append(name)
        else:
            keep.append(stripped)

    kept_block = "".join(f"{line}\n" for line in keep)
    new_text = text[:start] + "\n" + kept_block + text[anchor:]
    return new_text, {
        "removed_dollar_lines": sum(1 for ln in region.splitlines() if "$$" in ln),
        "kept_lines": len(keep),
        "kept_alias": kept_alias,
    }


def _load_backup(tar_path: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith("/work.atp"):
                continue
            code = member.name.split("/", 1)[0]
            out[code] = tar.extractfile(member).read()
    return out


def main() -> int:
    args = parse_args()
    prefixes = tuple(p.strip() for p in args.prefix.split(",") if p.strip())
    backup = _load_backup(args.restore_from) if args.restore_from else {}
    if args.restore_from:
        print(f"restore-from {args.restore_from}: {len(backup)} 个原始 work.atp", flush=True)

    db = SessionLocal()
    assets = [
        a for a in db.scalars(select(AtpAsset).order_by(AtpAsset.code)).all()
        if (a.code or "").startswith(prefixes)
    ]
    if args.limit:
        assets = assets[: args.limit]

    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} prefix={prefixes} candidates={len(assets)}", flush=True)

    counter: collections.Counter[str] = collections.Counter()
    plans = []
    skipped: list[tuple[str, str]] = []
    started = time.time()

    for index, asset in enumerate(assets, start=1):
        try:
            mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
            driver = _build_driver_or_400(_resolve_mount(db, mount_code))
        except Exception as exc:  # noqa: BLE001
            counter["mount_error"] += 1
            skipped.append((asset.code, str(exc)[:100]))
            continue

        atp_path = f"{storage_root_path.rstrip('/')}/work.atp"
        raw = backup.get(asset.code)
        if raw is None:
            try:
                raw = driver.read_file(atp_path).content
            except Exception as exc:  # noqa: BLE001
                counter["no_work_atp"] += 1
                skipped.append((asset.code, f"读 work.atp 失败: {exc}"[:100]))
                continue

        text, encoding = _decode(raw)
        new_text, info = delete_others(text)
        if info.get("skipped") == "no_marker":
            counter["no_marker"] += 1
            skipped.append((asset.code, "找不到 $PARAMETER 或 RER001=RER001I"))
            continue
        if info.get("skipped") == "no_dollar":
            counter["already_done"] += 1
            continue

        counter["rewritten"] += 1
        counter["dollar_lines_removed"] += info["removed_dollar_lines"]
        if info["kept_lines"]:
            counter["assets_with_kept_lines"] += 1

        plans.append({"asset": asset, "driver": driver, "path": atp_path, "raw": raw,
                      "encoding": encoding, "new_text": new_text, "info": info})

        if len(plans) <= args.show:
            print(f"\n  [{index}/{len(assets)}] {asset.code} ({encoding})", flush=True)
            print(f"    删 $$ 行 {info['removed_dollar_lines']}，保留非 $$ 行 {info['kept_lines']}"
                  f"{'（' + ','.join(info['kept_alias']) + '）' if info['kept_alias'] else ''}")
            head = [ln for ln in new_text.split(MARKER, 1)[1].splitlines()[:4]]
            print(f"    段首: {' | '.join(h.strip() for h in head)}")

    print(f"\nscan: {dict(counter)} plans={len(plans)}", flush=True)
    for code, message in skipped[: args.show]:
        print(f"  skip {code}: {message}", flush=True)

    if not args.apply:
        print("dry-run 结束（未写盘）。加 --apply 执行。", flush=True)
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tar_path = os.path.join(BACKUP_DIR, f"atp_delete_others_{stamp}.tar.gz")
    manifest_path = os.path.join(BACKUP_DIR, f"atp_delete_others_{stamp}.json")
    items = []
    with tarfile.open(tar_path, "w:gz") as tar:
        for plan in plans:
            tmp = f"/tmp/do_{plan['asset'].code}_work.atp"
            with open(tmp, "wb") as fp:
                fp.write(plan["raw"])
            tar.add(tmp, arcname=f"{plan['asset'].code}/work.atp")
            os.remove(tmp)
            items.append({
                "code": plan["asset"].code,
                "path": plan["path"],
                "removed_dollar_lines": plan["info"]["removed_dollar_lines"],
                "kept_lines": plan["info"]["kept_lines"],
            })
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(items, fp, ensure_ascii=False, indent=2)
    print(f"backup: {tar_path}\nmanifest: {manifest_path}", flush=True)

    written = 0
    for plan in plans:
        plan["driver"].write_file(plan["path"], content=plan["new_text"].encode(plan["encoding"], "replace"))
        tree = _walk_storage_tree(plan["driver"], plan["asset"].storage_root_path)
        members = collect_check_members_from_storage(plan["driver"], plan["asset"].storage_root_path, tree)
        report = inspect_package(members)
        plan["asset"].model_format = report.model_format
        plan["asset"].format_check_json = report.as_dict()
        written += 1
        if written % 10 == 0:
            db.commit()
            print(f"  ... written {written}/{len(plans)}", flush=True)
    db.commit()
    print(f"\ndone written={written} elapsed={time.time() - started:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
