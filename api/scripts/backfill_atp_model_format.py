"""存量 ATP 资产形态回填:按存储里的真实模型文件重判 model_format + 预检报告。

【为什么需要】
`atp_asset.model_format` 列是 2026-11-02 上传预检上线时才加的,DB 迁移给当时已有的
439 条资产统一填了列默认值 `legacy`。存量里本身混着 ATPDraw 7.2+ 的 `$INSERT` 模型,
于是「老版 · $INCLUDE + .lib」标记来自默认值而非判定结果,与文件真实形态不符。
上传口只在上传/更新文件时判定,不会回头改存量,故需要本脚本一次性重判。

【判定依据】与上传同一个函数 `atp_model_format.inspect_package`(按几何引用形态判,
不按版本指纹大小写):`$INSERT` → insert,`$INCLUDE *.lib` → legacy,两者都没有
且带 7.x 指纹 → embed,其余 → plain。

【幂等 / 安全】
- 默认 dry-run,只打印不写库;加 `--apply` 才写。
- 只重判 + 写两列(model_format / format_check_json),不动文件、不动其他字段。
- 单个资产读存储失败只记录并跳过,不中断整批。
- `--force` 才会重判已是 insert/embed/plain 的资产;默认只处理 model_format='legacy'
  且预检报告为空的存量行(即"从未被判定过"的行)。

【用法】
    python backfill_atp_model_format.py                # dry-run,打印前 20 条
    python backfill_atp_model_format.py --apply        # 真正写库
    python backfill_atp_model_format.py --apply --limit 50 --offset 0
    python backfill_atp_model_format.py --apply --force   # 全部重判(含已判过的)
"""
from __future__ import annotations

import argparse
import collections
import sys
import time

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
from app.services.atp_model_format import FORMAT_LABELS, inspect_package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="存量 ATP 资产形态回填")
    parser.add_argument("--apply", action="store_true", help="真正写库(默认 dry-run)")
    parser.add_argument("--force", action="store_true", help="重判全部资产(默认只处理未判定过的存量行)")
    parser.add_argument("--limit", type=int, default=0, help="本次最多处理多少条(0=不限)")
    parser.add_argument("--offset", type=int, default=0, help="跳过前 N 条(分批续跑用)")
    parser.add_argument("--show", type=int, default=20, help="打印多少条明细(默认 20)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()

    stmt = select(AtpAsset).order_by(AtpAsset.create_date, AtpAsset.id)
    if args.offset:
        stmt = stmt.offset(args.offset)
    if args.limit:
        stmt = stmt.limit(args.limit)
    assets = db.scalars(stmt).all()
    if not args.force:
        # 只补"从未判过"的存量行:默认值 legacy + 报告为空 dict
        assets = [
            a for a in assets
            if (a.model_format or "legacy") == "legacy" and not (a.format_check_json or {})
        ]

    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} force={args.force} candidates={len(assets)}", flush=True)
    counter: collections.Counter[str] = collections.Counter()
    drift: list[tuple[str, str, str]] = []
    failures: list[tuple[str, str]] = []
    started = time.time()

    for index, asset in enumerate(assets, start=1):
        try:
            mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
            mount = _resolve_mount(db, mount_code)
            driver = _build_driver_or_400(mount)
            tree = _walk_storage_tree(driver, storage_root_path)
            members = collect_check_members_from_storage(driver, storage_root_path, tree)
        except Exception as exc:  # noqa: BLE001 - 单条失败不中断整批
            counter["read_error"] += 1
            failures.append((asset.code, str(exc)))
            continue

        if not members:
            counter["no_model_files"] += 1
            failures.append((asset.code, f"目录内无 .atp/.dat/.pch: {storage_root_path}"))
            continue

        report = inspect_package(members)
        old = asset.model_format or "legacy"
        counter[f"real_{report.model_format}"] += 1
        if report.model_format != old:
            drift.append((asset.code, old, report.model_format))

        if args.apply:
            asset.model_format = report.model_format
            asset.format_check_json = report.as_dict()
        if index <= args.show:
            print(
                f"  [{index}/{len(assets)}] {asset.code}: {old} -> {report.model_format}"
                f" ({FORMAT_LABELS.get(report.model_format, report.model_format)}),"
                f" errors={len(report.errors)} warn={len(report.warnings)}",
                flush=True,
            )
        if args.apply and index % 20 == 0:
            db.commit()
            print(f"  ... committed {index}/{len(assets)}", flush=True)

    if args.apply:
        db.commit()

    elapsed = time.time() - started
    print("done", dict(counter), f"drift={len(drift)} failures={len(failures)} elapsed={elapsed:.1f}s", flush=True)
    for code, old, new in drift[: args.show]:
        print(f"  drift {code}: {old} -> {new}", flush=True)
    for code, message in failures[: args.show]:
        print(f"  fail  {code}: {message}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
