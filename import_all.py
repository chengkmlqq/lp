#!/usr/bin/env python3
"""Clear and re-import all CSV files with corrected line names."""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

from app.core.database import SessionLocal
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.services.line_service import import_line_towers_from_csv, create_line
from app.schemas.line import LineCreateRequest


class FakeUploadFile:
    def __init__(self, content: bytes, filename: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.size = len(content)


ACTOR = "system-import"

# All files with correct expected line names
CSV_CONFIGS = [
    ("test.csv", "utf-8-sig", "交流500kV雁船线（双回段）", 500),
    ("110kV白暮易线.csv", "gbk", "110kV白暮易线", 110),
    ("500kV昆罗Ⅰ线_完整.csv", "gbk", "500kV昆罗Ⅰ线", 500),
    ("500kV安电线_计算用参数+结果.csv", "utf-8-sig", "500kV安电线", 500),
    ("220kV磐高线.csv", "gbk", "220kV磐高线", 220),
    ("500kV青八甲线.csv", "utf-8-sig", "500kV青八甲线", 500),
    ("湖南110kV桐茨线.csv", "gbk", "湖南110kV桐茨线", 110),
    # Test/calculation files - keep names as-is from CSV
    ("220kV酒杯与猫头测试结果.csv", "tganta", "220kV酒杯与猫头测试结果", 220),
    ("500kV酒杯与猫头测试结果.csv", "tganta", "500kV酒杯与猫头测试结果", 500),
    ("避雷器计算结果_雁船线.csv", "tganta", "避雷器计算结果-雁船线", 500),
]


def read_csv_bytes(filename: str, encoding: str) -> tuple[bytes, str]:
    """Read CSV, fix line name in first data row, return processed bytes and encoding."""
    with open(filename, "rb") as f:
        raw = f.read()

    if encoding == "tganta":
        # Remove <TGanTa> line, data is utf-8-sig
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        if lines and lines[0].strip() == "<TGanTa>":
            lines = lines[1:]
        text = "\n".join(lines)
        return text.encode("utf-8"), "utf-8-sig"

    # Standard files: decode with encoding
    text = raw.decode(encoding)
    return raw, encoding


def fix_line_name_in_csv(raw: bytes, encoding: str, new_name: str) -> bytes:
    """Replace the 线路名称 value in first data row with the correct full name."""
    text = raw.decode(encoding)
    lines = text.splitlines()
    if not lines:
        return raw

    # Parse header to find 线路名称 column
    reader = csv.reader(io.StringIO("\n".join(lines)))
    rows = list(reader)
    if len(rows) < 2:
        return raw

    header = rows[0]
    try:
        name_idx = header.index("线路名称")
    except ValueError:
        return raw

    # Replace in first data row
    rows[1][name_idx] = new_name
    # Write back preserving original line endings
    output = "\r\n".join([",".join(row) for row in rows])
    return output.encode("utf-8")


def clean_database(db):
    """Delete all existing lines and related data."""
    print("[CLEAN] Deleting all existing tower profiles, towers, and lines...")
    db.query(TowerProfile).delete()
    db.query(LineTower).delete()
    db.query(Line).delete()
    db.commit()
    print("[CLEAN] Done.")


def main():
    db = SessionLocal()
    try:
        clean_database(db)

        for csv_file, encoding, line_name, voltage_kv in CSV_CONFIGS:
            csv_path = os.path.join(os.path.dirname(__file__), csv_file)
            if not os.path.exists(csv_path):
                print(f"[SKIP] {csv_file} not found")
                continue

            raw, actual_enc = read_csv_bytes(csv_file, encoding)

            # Fix the line name in CSV first row to match what we want
            if actual_enc == "utf-8-sig":
                raw = fix_line_name_in_csv(raw, actual_enc, line_name)
            elif actual_enc == "gbk":
                fixed = fix_line_name_in_csv(raw, actual_enc, line_name)
                raw = fixed

            # Create line
            print(f"[CREATE] '{line_name}' ({voltage_kv}kV)...")
            payload = LineCreateRequest(name=line_name, voltage_kv=voltage_kv)
            result = create_line(db, payload, actor_user_id=ACTOR)
            line_obj = db.query(Line).filter(Line.id == result.id).first()
            print(f"  -> id={result.id}")

            # Import towers
            print(f"[IMPORT] Towers from {csv_file}...")
            try:
                fake = FakeUploadFile(raw, csv_file)
                r = import_line_towers_from_csv(
                    db, line=line_obj, file=fake, actor_user_id=ACTOR,
                )
                print(
                    f"  -> Imported: {r.imported_count}, Updated: {r.updated_count}, "
                    f"Skipped: {r.skipped_count}, Warnings: {r.warning_count}"
                )
                if r.warnings:
                    for w in r.warnings[:3]:
                        print(f"    ⚠ {w}")
            except Exception as e:
                print(f"  [ERROR] {e}")
                import traceback
                traceback.print_exc()
                db.rollback()
                continue

        # Final summary
        lines = db.query(Line).order_by(Line.create_date).all()
        print(f"\n{'='*50}")
        print(f"✅ 最终结果：共 {len(lines)} 条线路")
        for l in lines:
            cnt = db.query(LineTower).filter(LineTower.line_id == l.id).count()
            print(f"   [{l.code}] {l.name} - {l.voltage_kv}kV - {cnt}基杆塔")
        total = db.query(LineTower).count()
        print(f"   总杆塔数: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
