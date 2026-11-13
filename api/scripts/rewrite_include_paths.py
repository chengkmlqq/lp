"""把 work.atp 的 `$INCLUDE` 路径统一成 D:\\ATP\\<电压>\\<塔形>\\<场景>\\<避雷器>\\<文件名>.lib

【背景】
115/230 这批 C# 迁移模型的 `$INCLUDE` 里保留着原机器的目录，形态混乱：

    C:\\ATP60work\\batch\\110_ganzi_fanji\\dahao.lib
    C:\\Users\\AI\\Desktop\\110、220改no\\115、230无sihuita\\115\\guxing\\fanji\\M123\\dahao.lib

而 220 的标准形态是 `D:\\ATP\\220\\guxing\\raoji1\\M123\\dahao.lib`（电压/塔形/场景/避雷器组合四层）。
本脚本按资产的存储维度（与 storage_root_path 同构）重写目录前缀，文件名、节点参数、
行尾 `$$` 一律原样保留。

【平台侧影响】
无。`include_lib_refs()` 只取文件名做预检；运行期 `_rewrite_includes` 也会把 `$INCLUDE`
按文件名重写到任务私有目录。改路径只为可读性 + 本机 ATPDraw 直接打开时能解析到 lib。

【安全 / 幂等】
- 默认 dry-run，`--apply` 才写；写前备份（tar.gz + json）。
- 目录已正确的文件会被计为 unchanged，可重复执行。

【用法】
    python scripts/rewrite_include_paths.py --voltage 115,230 --show 5
    python scripts/rewrite_include_paths.py --voltage 115,230 --apply
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tarfile
import time
from datetime import datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.atp_asset import AtpAssetVersion
from app.services.atp_asset_service import (
    _build_driver_or_400,
    _resolve_asset_file_location,
    _resolve_mount,
    _walk_storage_tree,
    collect_check_members_from_storage,
)
from app.services.atp_model_format import inspect_package

BACKUP_DIR = "/app/data/backup_atp_cleanup"
INC_LINE_RE = re.compile(r"^[ \t]*\$INCLUDE\b", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="$INCLUDE 路径统一到 D:\\ATP 四层目录")
    parser.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    parser.add_argument("--voltage", default="115,230", help="电压等级，逗号分隔")
    parser.add_argument("--root", default="D:\\ATP", help="根路径（默认 D:\\ATP）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=不限）")
    parser.add_argument("--show", type=int, default=5, help="打印多少条明细")
    return parser.parse_args()


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def _dimensions(asset: AtpAssetVersion, storage_root_path: str) -> tuple[str, str, str, str] | None:
    """返回 (电压, 塔形, 场景, 避雷器组合)。取自存储路径末尾四段，与资产维度互相校验。"""
    segments = [p for p in storage_root_path.replace("\\", "/").split("/") if p]
    if len(segments) < 4:
        return None
    voltage, tower, scene, arrester = segments[-4:]
    if asset.voltage_level and voltage != str(asset.voltage_level):
        return None
    if not (voltage.isdigit() and tower and scene and arrester):
        return None
    return voltage, tower, scene, arrester


def rewrite_includes(text: str, target_dir: str) -> tuple[str, dict]:
    """把每个 `$INCLUDE, <path>, <其余>` 的路径目录换成 target_dir，其余逐字节保留。"""
    changed = 0
    names: list[str] = []
    old_dirs: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        eol = raw[len(body):]
        if not INC_LINE_RE.match(body):
            out.append(raw)
            continue
        parts = body.split(",")
        if len(parts) < 2:
            out.append(raw)
            continue
        field = parts[1]
        clean = field.strip().strip('"')
        base = re.split(r"[\\/]", clean)[-1].strip()
        if not base or "." not in base:
            out.append(raw)
            continue
        lead = field[: len(field) - len(field.lstrip())]
        trail = field[len(field.rstrip()):]
        new_field = f"{lead}{target_dir}\\{base}{trail}"
        if new_field == field:
            out.append(raw)
            continue
        old_dir = clean[: len(clean) - len(base)]
        if old_dir:
            old_dirs.add(old_dir.rstrip("\\/"))
        changed += 1
        if base not in names:
            names.append(base)
        out.append(",".join([parts[0], new_field, *parts[2:]]) + eol)
    return "".join(out), {"changed": changed, "names": names, "old_dirs": old_dirs}


def main() -> int:
    args = parse_args()
    voltages = [v.strip() for v in args.voltage.split(",") if v.strip()]
    root = args.root.rstrip("\\/")

    db = SessionLocal()
    assets = db.scalars(
        select(AtpAssetVersion).where(AtpAssetVersion.voltage_level.in_(voltages)).order_by(AtpAssetVersion.code)
    ).all()
    if args.limit:
        assets = assets[: args.limit]

    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} voltages={voltages} root={root} "
          f"candidates={len(assets)}", flush=True)

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

        dims = _dimensions(asset, storage_root_path)
        if dims is None:
            counter["bad_dimensions"] += 1
            skipped.append((asset.code, f"无法从 {storage_root_path} 解析四层目录"))
            continue
        target_dir = root + "\\" + "\\".join(dims)

        atp_path = f"{storage_root_path.rstrip('/')}/work.atp"
        try:
            raw = driver.read_file(atp_path).content
        except Exception as exc:  # noqa: BLE001
            counter["no_work_atp"] += 1
            skipped.append((asset.code, f"读 work.atp 失败: {exc}"[:100]))
            continue

        text, encoding = _decode(raw)
        new_text, info = rewrite_includes(text, target_dir)
        if not info["changed"]:
            counter["unchanged"] += 1
            continue

        counter["rewritten"] += 1
        counter["lines_changed"] += info["changed"]

        plans.append({
            "asset": asset, "driver": driver, "path": atp_path, "raw": raw,
            "encoding": encoding, "new_text": new_text, "info": info, "target": target_dir,
        })

        if len(plans) <= args.show:
            print(f"\n  [{index}/{len(assets)}] {asset.code} ({encoding}) → {target_dir}", flush=True)
            print(f"    改写 {info['changed']} 条 $INCLUDE，文件: {','.join(info['names'])}")
            print(f"    原目录: {', '.join(sorted(info['old_dirs']))}")

    print(f"\nscan: {dict(counter)} plans={len(plans)}", flush=True)
    for code, message in skipped[: args.show]:
        print(f"  skip {code}: {message}", flush=True)

    if not args.apply:
        print("dry-run 结束（未写盘）。加 --apply 执行。", flush=True)
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tar_path = os.path.join(BACKUP_DIR, f"atp_include_path_{stamp}.tar.gz")
    manifest_path = os.path.join(BACKUP_DIR, f"atp_include_path_{stamp}.json")
    items = []
    with tarfile.open(tar_path, "w:gz") as tar:
        for plan in plans:
            tmp = f"/tmp/inc_{plan['asset'].code}_work.atp"
            with open(tmp, "wb") as fp:
                fp.write(plan["raw"])
            tar.add(tmp, arcname=f"{plan['asset'].code}/work.atp")
            os.remove(tmp)
            items.append({
                "code": plan["asset"].code,
                "path": plan["path"],
                "target_dir": plan["target"],
                "lines_changed": plan["info"]["changed"],
                "old_dirs": sorted(plan["info"]["old_dirs"]),
            })
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(items, fp, ensure_ascii=False, indent=2)
    print(f"backup: {tar_path}\nmanifest: {manifest_path}", flush=True)

    written = 0
    for plan in plans:
        plan["driver"].write_file(
            plan["path"], content=plan["new_text"].encode(plan["encoding"], "replace")
        )
        tree = _walk_storage_tree(plan["driver"], plan["asset"].storage_root_path)
        members = collect_check_members_from_storage(
            plan["driver"], plan["asset"].storage_root_path, tree
        )
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
