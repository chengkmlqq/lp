#!/usr/bin/env python3
"""Import all CSV files into the LP database."""

import csv
import io
import os
import sys

# Ensure we're using the project venv's packages
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
    """Mimics FastAPI UploadFile for import_line_towers_from_csv."""

    def __init__(self, content: bytes, filename: str):
        self.file = io.BytesIO(content)
        self.filename = filename
        self.size = len(content)


# CSV files to import, with (filename, line_name_override, voltage_kv)
CSV_FILES = [
    ("test.csv", "交流500kV雁船线（双回段）", 500),
    ("110kV白暮易线.csv", "110kV白暮易线", 110),
    ("500kV昆罗Ⅰ线_完整.csv", "500kV昆罗Ⅰ线", 500),
    ("500kV安电线_计算用参数+结果.csv", "500kV安电线", 500),
    ("220kV磐高线.csv", "220kV磐高线", 220),
]

ACTOR = "system-import"


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

            # Check if line already exists
            existing = get_line_by_code(db, line_name) if line_name else None
            if existing:
                print(f"[INFO] Line '{line_name}' already exists (id={existing.id}), updating towers...")
                line_obj = db.query(Line).filter(Line.id == existing.id).first()
            else:
                print(f"[CREATE] Line '{line_name}' ({voltage_kv}kV)...")
                payload = LineCreateRequest(name=line_name, voltage_kv=voltage_kv)
                result = create_line(db, payload, actor_user_id=ACTOR)
                line_obj = db.query(Line).filter(Line.id == result.id).first()
                print(f"  -> Created line id={result.id}")

            # Import towers from CSV
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
                        print(f"    ... and {len(result.warnings)-5} more warnings")
            except Exception as e:
                print(f"  [ERROR] {e}")
                db.rollback()
                continue

        # Summary
        total_lines = db.query(Line).count()
        total_towers = db.query(LineTower).count()
        print(f"\n✅ Done! Total: {total_lines} lines, {total_towers} towers")
    finally:
        db.close()


if __name__ == "__main__":
    main()
