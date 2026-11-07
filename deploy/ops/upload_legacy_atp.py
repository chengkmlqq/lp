# -*- coding: utf-8 -*-
"""把 /app/data/legacy_atp 下的老模型写入平台存储（当前为本地 VFS）并登记为资产。

  python upload_legacy.py --dry-run   # 只打印计划
  python upload_legacy.py --apply     # 执行写入 + 登记（全部发布 + 生效）

存储走平台存储驱动（main 挂载），不直连 OSS —— 后端换成 VFS/S3 都能用。
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/app")

import warnings

warnings.filterwarnings("ignore")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.atp_asset_service import (  # noqa: E402
    _build_driver_or_400,
    _resolve_mount,
)

ROOT = "/app/data/legacy_atp"
KEEP_EXT = (".atp", ".dat", ".lib", ".pch", ".acp")
STD_TOWERS = {"ganzi", "guxing", "jiubei", "maotou", "shangzi", "sihuita"}
STD_SCENES = {"fanji", "raoji1", "raoji2", "raoji3"}

apply_flag = "--apply" in sys.argv


def collect():
    items = []
    for dirpath, _dirs, files in os.walk(ROOT):
        low = {f.lower() for f in files}
        if "work.atp" not in low:
            continue
        parts = os.path.relpath(dirpath, ROOT).replace("\\", "/").split("/")
        if len(parts) != 4:
            continue
        volt, tower_raw, scene, arrester = parts
        if not volt.isdigit() or scene.lower() not in STD_SCENES:
            continue
        tower, shield = tower_raw.lower(), "with"
        if tower.endswith("no"):
            tower, shield = tower[:-2], "none"
        elif tower.endswith("d") and tower[:-1] in STD_TOWERS:
            tower, shield = tower[:-1], "single"
        if tower not in STD_TOWERS:
            continue
        sel = [f for f in files if f.lower().endswith(KEEP_EXT)]
        if not sel:
            continue
        items.append({
            "volt": volt, "tower": tower, "tower_raw": tower_raw.lower(), "scene": scene.lower(),
            "arrester": arrester, "shield": shield,
            "code": f"ATP{volt}-{tower_raw.lower()}-{scene.lower()}-{arrester}",
            "name": f"{volt}kV {tower_raw.lower()} {scene.lower()} {arrester}",
            "src": dirpath,
            "dst": f"/atp-assets/{volt}/{tower_raw.lower()}/{scene.lower()}/{arrester}",
            "files": sorted(sel),
        })
    return items


def main():
    items = collect()
    volt_arg = None
    if "--voltages" in sys.argv:
        idx = sys.argv.index("--voltages")
        if idx + 1 < len(sys.argv):
            volt_arg = {v.strip() for v in sys.argv[idx + 1].split(",") if v.strip()}
    if volt_arg:
        items = [i for i in items if i["volt"] in volt_arg]
    codes = [i["code"] for i in items]
    total_files = sum(len(i["files"]) for i in items)
    total_bytes = sum(
        os.path.getsize(os.path.join(i["src"], f)) for i in items for f in i["files"]
    )
    print(f"待写入 {len(items)} 个模型，{total_files} 个文件，{total_bytes / 1048576:.1f} MB，"
          f"code 唯一性 {len(set(codes))}/{len(codes)}")

    db = SessionLocal()
    existing = {r[0] for r in db.execute(text("select code from atp_asset")).all()}
    new_cnt = sum(1 for c in codes if c not in existing)
    print(f"库中已存在 {len(codes) - new_cnt} 个（将更新），新增 {new_cnt} 个")

    mount = _resolve_mount(db, "main")
    print(f"存储目标：mount={mount.code} backend={mount.backend.code}({mount.backend.driver_type}) "
          f"root={mount.root_path}")

    if not apply_flag:
        for i in items[:5]:
            print("  ", i["code"], "->", i["dst"], f"({len(i['files'])} files)")
        print("[dry-run] 未写入")
        return

    driver = _build_driver_or_400(mount)
    done = {"models": 0, "files": 0}
    lock_failed = []

    def put_one(item):
        driver.ensure_directory(item["dst"])
        n = 0
        for fn in item["files"]:
            with open(os.path.join(item["src"], fn), "rb") as fh:
                driver.write_file(f"{item['dst']}/{fn}", content=fh.read())
            n += 1
        return n

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(put_one, it): it for it in items}
        for idx, (fut, it) in enumerate(futures.items(), 1):
            try:
                done["files"] += fut.result()
                done["models"] += 1
            except Exception as exc:  # noqa: BLE001
                lock_failed.append((it["code"], str(exc)[:160]))
                print("  FAIL", it["code"], str(exc)[:140])
            if idx % 100 == 0:
                print(f"  写入 {idx}/{len(items)}，累计 {done['models']} 模型 / {done['files']} 文件")

    print(f"存储写入完成：{done['models']} 个模型 / {done['files']} 个文件，失败 {len(lock_failed)}")

    ins = upd = 0
    for it in items:
        row = db.execute(text("select id, is_active from atp_asset where code=:c"), {"c": it["code"]}).mappings().first()
        if row:
            db.execute(text(
                "update atp_asset set is_active=0 where voltage_level=:v and tower_type=:t and scene_type=:s "
                "and arrester_config=:a and shield_wire=:w and id<>:i"),
                {"v": it["volt"], "t": it["tower"], "s": it["scene"], "a": it["arrester"],
                 "w": it["shield"], "i": row["id"]})
            db.execute(text(
                "update atp_asset set name=:n, status='enabled', is_published=1, published_date=now(), "
                "is_active=1, model_format='legacy', storage_mount_code='main', storage_root_path=:p, "
                "test_status=NULL, test_message=NULL, update_date=now() where id=:i"),
                {"n": it["name"], "p": it["dst"], "i": row["id"]})
            upd += 1
        else:
            db.execute(text(
                "insert into atp_asset (id, code, name, description, status, voltage_level, tower_type, scene_type, "
                "arrester_config, version, is_active, is_published, published_date, shield_wire, storage_mount_code, "
                "storage_root_path, tags_json, slots_json, model_format, format_check_json, create_date, update_date) "
                "values (replace(uuid(),'-',''), :c, :n, :d, 'enabled', :v, :t, :s, :a, 'v1', 1, 1, now(), :w, 'main', "
                ":p, '[]', '{}', 'legacy', '{}', now(), now())"),
                {"c": it["code"], "n": it["name"], "d": f"老模型上传（{it['src']}）", "v": it["volt"],
                 "t": it["tower"], "s": it["scene"], "a": it["arrester"], "w": it["shield"], "p": it["dst"]})
            ins += 1
        if (ins + upd) % 100 == 0:
            db.commit()
    db.commit()
    print(f"资产登记完成：新增 {ins}，更新 {upd}")
    total = db.execute(text("select count(*) from atp_asset")).scalar()
    pub = db.execute(text("select count(*) from atp_asset where is_published=1")).scalar()
    act = db.execute(text("select count(*) from atp_asset where is_active=1")).scalar()
    print(f"库内资产 {total}，已发布 {pub}，生效 {act}")


if __name__ == "__main__":
    main()
