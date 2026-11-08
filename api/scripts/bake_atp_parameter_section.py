"""【已作废】把老版模型的 `$PARAMETER` 段烘焙成「纯数值」形态。

⚠️ 2026-11-08 起不要再用这个脚本：它把整段烘焙成数值，与 C# `1 delete_others.py`
的实际产物（只删 `$$` 中间变量段、保留 `NAME=NAME_I` 别名块）不同。
现行做法是 `atp_model_format.preprocess_legacy_entry`（导入时自动执行）
+ `scripts/apply_delete_others.py`（存量），两者共用同一实现。
本文件仅作历史留档，产物可由 `apply_delete_others.py --restore-from <bake备份>` 回退。

【原背景】
C# 桌面版跑 ATP 前，先用 `1 delete_others.py` 删掉 `$PARAMETER` 与 `RER001=RER001I` 之间的
变量替换段（一堆 `NAME_I =值 $$`），再由 Update_work_atp3 按特征表把真实值写进别名行
（`RER001=RER001I` → `RER001=1716.0`）。所以 C# 交给引擎的文件里既没有 `$$`，也没有中间变量。

平台侧等价的动作是运行期 `normalize_parameter_section`：解别名 → 写数值（带小数点、无 `$$`）。
但它发生在**运行期**，库里存的模型文件仍带 N 行 `NAME_I =值 $$`，于是预检一直报
W001（行尾 `$$`）/ W002（整数无小数点）/ W003（中间变量超 List31）。

本脚本把这一步提前落进模型文件：`$PARAMETER` 段重写为 `别名=数值`，段落外逐字节保留。
重写后 `_looks_like_csharp_equality_template` 不再命中等号占位符形态，
运行期改由 `override_numeric_current_params` 逐塔覆写几何/电流参数 —— 它的允许集（42 个）
覆盖 `compute_csharp_atp_params` 的全部 26 个键，行为与重写前一致（已核对）。

【安全 / 幂等】
- 默认 dry-run，加 `--apply` 才写盘；**先备份再写**（tar.gz + 清单 json）。
- 只处理 `unresolved` 为空的资产：有悬空引用就跳过并记录，绝不烘出半成品。
- 已是纯数值形态（`rewritten=False`）直接跳过，可反复执行。
- 写完重跑 `inspect_package`，把 model_format / format_check_json 落库（前端读库不现算）。

【用法】
    python bake_atp_parameter_section.py                     # dry-run，列前 20 条
    python bake_atp_parameter_section.py --apply             # 真写
    python bake_atp_parameter_section.py --prefix ATP115 --apply
    python bake_atp_parameter_section.py --prefix ATP115,ATP230 --only-missing
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tarfile
import time
from dataclasses import dataclass
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
from app.services.atp_model_format import inspect_package, normalize_parameter_section

BACKUP_DIR = "/app/data/backup_atp_cleanup"


@dataclass
class Plan:
    asset: AtpAsset
    driver: object
    storage_root_path: str
    atp_path: str
    raw: bytes
    encoding: str
    new_text: str
    before: list[str]
    after: list[str]
    diag: dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烘焙 $PARAMETER 段为纯数值形态")
    parser.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    parser.add_argument("--prefix", default="ATP115,ATP230", help="资产 code 前缀，逗号分隔")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=不限）")
    parser.add_argument("--show", type=int, default=20, help="打印多少条明细")
    return parser.parse_args()


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def _section_preview(text: str, limit: int = 5) -> list[str]:
    out: list[str] = []
    in_params = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.upper() == "$PARAMETER":
            in_params = True
            continue
        if not in_params:
            continue
        if stripped.upper().startswith("BLANK $PARAMETER"):
            break
        if stripped:
            out.append(stripped)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    args = parse_args()
    prefixes = tuple(p.strip() for p in args.prefix.split(",") if p.strip())
    db = SessionLocal()

    assets = [
        a for a in db.scalars(select(AtpAsset).order_by(AtpAsset.code)).all()
        if (a.code or "").startswith(prefixes)
    ]
    if args.limit:
        assets = assets[: args.limit]

    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} prefix={prefixes} candidates={len(assets)}", flush=True)

    counter: collections.Counter[str] = collections.Counter()
    skipped: list[tuple[str, str]] = []
    plans: list[Plan] = []
    started = time.time()

    # ── 阶段一：只读扫描，算出改写方案（不碰文件） ──
    for index, asset in enumerate(assets, start=1):
        try:
            mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
            driver = _build_driver_or_400(_resolve_mount(db, mount_code))
        except Exception as exc:  # noqa: BLE001
            counter["mount_error"] += 1
            skipped.append((asset.code, str(exc)[:120]))
            continue

        atp_path = f"{storage_root_path.rstrip('/')}/work.atp"
        try:
            raw = driver.read_file(atp_path).content
        except Exception as exc:  # noqa: BLE001
            counter["no_work_atp"] += 1
            skipped.append((asset.code, f"读 work.atp 失败: {exc}"[:120]))
            continue

        text, encoding = _decode(raw)
        new_text, diag = normalize_parameter_section(text, undefined_policy="error")
        if diag["unresolved"]:
            counter["unresolved"] += 1
            names = "、".join(item["name"] for item in diag["unresolved"][:5])
            skipped.append((asset.code, f"有 {len(diag['unresolved'])} 个悬空引用（{names}），跳过"))
            continue
        if not diag["rewritten"]:
            counter["already_numeric"] += 1
            continue

        counter["rewritten"] += 1
        counter["dollar_removed"] += text.count("$$") - new_text.count("$$")
        plans.append(Plan(
            asset=asset,
            driver=driver,
            storage_root_path=storage_root_path,
            atp_path=atp_path,
            raw=raw,
            encoding=encoding,
            new_text=new_text,
            before=_section_preview(text),
            after=_section_preview(new_text),
            diag=diag,
        ))
        if len(plans) <= args.show:
            print(f"\n  [{index}/{len(assets)}] {asset.code} ({encoding}, {len(raw)}B)", flush=True)
            print(f"    改写前: {' | '.join(plans[-1].before)}")
            print(f"    改写后: {' | '.join(plans[-1].after)}")

    print(f"\nscan: {dict(counter)} plans={len(plans)}", flush=True)
    for code, message in skipped[: args.show]:
        print(f"  skip {code}: {message}", flush=True)

    if not args.apply:
        print("dry-run 结束（未写盘）。加 --apply 执行。", flush=True)
        return 0

    # ── 阶段二：先备份，再写盘 ──
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tar_path = os.path.join(BACKUP_DIR, f"atp_param_bake_{stamp}.tar.gz")
    manifest_path = os.path.join(BACKUP_DIR, f"atp_param_bake_{stamp}.json")
    with tarfile.open(tar_path, "w:gz") as tar:
        for plan in plans:
            tmp = f"/tmp/bake_{plan.asset.code}_work.atp"
            with open(tmp, "wb") as fp:
                fp.write(plan.raw)
            tar.add(tmp, arcname=f"{plan.asset.code}/work.atp")
            os.remove(tmp)
    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(
            [{"code": p.asset.code, "path": p.atp_path, "bytes": len(p.raw)} for p in plans],
            fp, ensure_ascii=False, indent=2,
        )
    print(f"backup: {tar_path}\nmanifest: {manifest_path}", flush=True)

    written = 0
    for plan in plans:
        plan.driver.write_file(plan.atp_path, content=plan.new_text.encode(plan.encoding, "replace"))
        tree = _walk_storage_tree(plan.driver, plan.storage_root_path)
        members = collect_check_members_from_storage(plan.driver, plan.storage_root_path, tree)
        report = inspect_package(members)
        plan.asset.model_format = report.model_format
        plan.asset.format_check_json = report.as_dict()
        written += 1
        if written % 10 == 0:
            db.commit()
            print(f"  ... written {written}/{len(plans)}", flush=True)
    db.commit()

    elapsed = time.time() - started
    print(f"\ndone written={written} elapsed={elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
