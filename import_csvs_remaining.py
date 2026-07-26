#!/usr/bin/env python3
"""Import remaining CSV files into the LP database."""

import csv
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))

from app.core.database import SessionLocal
from app.models.line import Line
from app.models.line_tower import LineTower
from app.services.line_service import (
    import_line_towers_from_csv,
    create_line,
    get_line_by_code,
)
from app.schemas.line import LineCreateRequest


class FakeUploadFile:
    def __init__(self, content: bytes, filename: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.size = len(content)


ACTOR = "system-import"

# Remaining files: (filename, initial_name, voltage_kv)
CSV_FILES = [
    ("500kV青八甲线.csv", "500kV青八甲线", 500),
    ("湖南110kV桐茨线.csv", "湖南110kV桐茨线", 110),
    ("220kV酒杯与猫头测试结果.csv", "220kV酒杯与猫头测试结果", 220),
    ("500kV酒杯与猫头测试结果.csv", "500kV酒杯与猫头测试结果", 500),
    ("避雷器计算结果_雁船线.csv", "避雷器计算结果（雁船线）", 500),
]


def preprocess_tganta(raw: bytes) -> bytes:
    """Skip the <TGanTa> line and decode properly."""
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    # Skip first line if it's <TGanTa>
    if lines and lines[0].strip() == "<TGanTa>":
        lines = lines[1:]
    return "\n".join(lines).encode("utf-8")


def main():
    db = SessionLocal()
    try:
        for csv_file, line_name, voltage_kv in CSV_FILES:
            csv_path = os.path.join(os.path.dirname(__file__), csv_file)
            if not os.path.exists(csv_path):
                print(f"[SKIP] {csv_file} not found")
                continue

            with open(csv_path, "rb") as f:
                raw = f.read()

            # Pre-process <TGanTa> prefixed files
            is_tganta = raw.startswith(b"\xef\xbb\xbf<TGanTa>") or raw.startswith(b"<TGanTa>")
            if is_tganta:
                raw = preprocess_tganta(raw)

            # Check if line already exists by checking line name in DB
            existing = (
                db.query(Line)
                .filter(Line.name == line_name)
                .first()
            )
            if existing:
                print(f"[INFO] '{line_name}' already exists (id={existing.id}), skipping...")
                continue

            # Create the line
            print(f"[CREATE] '{line_name}' ({voltage_kv}kV)...")
            payload = LineCreateRequest(name=line_name, voltage_kv=voltage_kv)
            result = create_line(db, payload, actor_user_id=ACTOR)
            line_obj = db.query(Line).filter(Line.id == result.id).first()
            print(f"  -> Created line id={result.id}")

            # Import towers
            print(f"[IMPORT] Towers from {csv_file}...")
            try:
                fake_file = FakeUploadFile(raw, csv_file)
                result = import_line_towers_from_csv(
                    db,
                    line=line_obj,
                    file=fake_file,
                    actor_user_id=ACTOR,
                )
                print(
                    f"  -> Imported: {result.imported_count}, "
                    f"Updated: {result.updated_count}, "
                    f"Skipped: {result.skipped_count}, "
                    f"Warnings: {result.warning_count}"
                )
                if result.warnings:
                    for w in result.warnings[:5]:
                        print(f"    ⚠ {w}")
                    if len(result.warnings) > 5:
                        print(f"    ... and {len(result.warnings)-5} more")
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
