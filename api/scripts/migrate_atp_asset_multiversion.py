"""33.2 生产库(MySQL) atp_asset 多版本改造:加列 + 回填 + 归一 no 变体(纯 SQL,不依赖 ORM 新字段)。

【用途】ATP 模型多版本 + 生效字段改造的生产库迁移/数据清洗脚本。
【已执行】2026-10-30 在 33.2 lp-api 容器内跑通:加 version/is_active/shield_wire 列 + 索引,
   559 条回填 version='v1'/is_active=1/shield_wire='with',72 条 no 后缀塔型变体归一(→主塔型 + without + is_active=0)。
【幂等】列存在跳过;无 no 后缀跳过。dry-run 用 --dry-run(只打印不写)。
【用法】python migrate_atp_asset_multiversion.py [--dry-run]
"""
import sys

from app.core.database import SessionLocal
from sqlalchemy import text

DRY = "--dry-run" in sys.argv

NO_VARIANT_MAP = {
    "ganzino": "ganzi",
    "guxingno": "guxing",
    "jiubeino": "jiubei",
    "maotouno": "maotou",
    "shangzino": "shangzi",
    "sihuitano": "sihuita",
}

db = SessionLocal()


def add_column_if_missing(table: str, column: str, ddl: str) -> str:
    exists = db.execute(text(
        f"SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() "
        f"AND table_name = '{table}' AND column_name = '{column}'"
    )).scalar()
    if exists:
        return f"skip {column} (exists)"
    if DRY:
        return f"[DRY] would add {column}"
    db.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
    return f"added {column}"


print("== 步骤1: 加列 ==")
print(add_column_if_missing("atp_asset", "version", "version VARCHAR(32) NOT NULL DEFAULT 'v1'"))
print(add_column_if_missing("atp_asset", "is_active", "is_active TINYINT(1) NOT NULL DEFAULT 0"))
print(add_column_if_missing("atp_asset", "shield_wire", "shield_wire VARCHAR(16) NOT NULL DEFAULT 'with'"))

# 索引(MySQL 8 不支持 CREATE INDEX IF NOT EXISTS)
print("== 步骤1b: 索引 ==")
idx_exists = db.execute(text(
    "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
    "AND table_name = 'atp_asset' AND index_name = 'idx_atp_asset_active'"
)).scalar()
if not idx_exists:
    if DRY:
        print("[DRY] would create idx_atp_asset_active")
    else:
        db.execute(text(
            "CREATE INDEX idx_atp_asset_active ON atp_asset "
            "(voltage_level, tower_type, scene_type, arrester_config, shield_wire, is_active)"
        ))
        print("created idx_atp_asset_active")
else:
    print("idx_atp_asset_active exists")
if not DRY:
    db.commit()

print("== 步骤2: 回填 ==")
if DRY:
    n = db.execute(text("SELECT COUNT(*) FROM atp_asset")).scalar()
    print(f"[DRY] would backfill {n} rows: version='v1', is_active=1, shield_wire='with'")
else:
    db.execute(text("UPDATE atp_asset SET version = 'v1' WHERE version IS NULL OR version = ''"))
    db.execute(text("UPDATE atp_asset SET is_active = 1 WHERE is_active IS NULL OR is_active = 0"))
    db.execute(text("UPDATE atp_asset SET shield_wire = 'with' WHERE shield_wire IS NULL OR shield_wire = ''"))
    db.commit()
    n = db.execute(text("SELECT COUNT(*) FROM atp_asset WHERE is_active = 1")).scalar()
    t = db.execute(text("SELECT COUNT(*) FROM atp_asset")).scalar()
    print(f"backfill done: is_active=1 共 {n}/{t}")

print("== 步骤3: 归一 no 变体 ==")
rows = db.execute(text(
    "SELECT id, code, tower_type, storage_root_path FROM atp_asset WHERE tower_type LIKE '%no'"
)).fetchall()
print(f"no-variant rows found: {len(rows)}")
changed = 0
for rid, code, tw, path in rows:
    tw = (tw or "").strip()
    if tw not in NO_VARIANT_MAP:
        continue
    main_tw = NO_VARIANT_MAP[tw]
    if DRY:
        print(f"[DRY] {code:30s} {tw} -> {main_tw} (shield_wire=without, is_active=0)")
        changed += 1
        continue
    db.execute(text(
        "UPDATE atp_asset SET tower_type = :mt, shield_wire = 'without', is_active = 0 WHERE id = :rid"
    ), {"mt": main_tw, "rid": rid})
    changed += 1
if not DRY:
    db.commit()
print(f"normalized: {changed} rows")

# 归一后确认（DRY 时列尚不存在，跳过分布查询）
print("== 步骤4: 归一后分布 ==")
if not DRY:
    dist = db.execute(text(
        "SELECT shield_wire, is_active, COUNT(*) FROM atp_asset GROUP BY shield_wire, is_active ORDER BY shield_wire, is_active"
    )).fetchall()
    print("shield_wire/is_active dist:", [(r[0], r[1], r[2]) for r in dist])
no_left = db.execute(text("SELECT COUNT(*) FROM atp_asset WHERE tower_type LIKE '%no'")).scalar()
print("remaining no-suffix rows:", no_left)
if not DRY:
    db.commit()
db.close()
print("DONE")
