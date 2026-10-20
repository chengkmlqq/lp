"""Seed atp_param_template / atp_param_global from atp_param_mappings JSON.

Mirrors the C# ATP model matrix: one base rule per tower_type (ganzi/guxing/
jiubei/maotou/shangzi/sihuita/zhiliu/vzhiliu/menxing), plus voltage-specific
rules (maotou_750, maotou_1000) as finer-dimension rules, and _common.json
globals as atp_param_global rows. Idempotent: skips existing rows by name+marker.

Run inside the api container:
    sudo docker cp <repo>/scripts/seed_atp_templates.py lp-api-1:/tmp/
    sudo docker exec lp-api-1 sh -c 'cd /app && PYTHONPATH=/app python /tmp/seed_atp_templates.py'
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.atp_param_template import AtpParamGlobal, AtpParamTemplate

MAPPINGS = Path("/app/app/services/atp_param_mappings")


def now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> int:
    db = SessionLocal()
    try:
        # ---- globals from _common.json ----
        common = json.loads((MAPPINGS / "_common.json").read_text(encoding="utf-8"))
        created_g = updated_g = skipped_g = 0
        for slot, spec in (common.get("globals") or {}).items():
            row = db.scalar(select(AtpParamGlobal).where(AtpParamGlobal.slot == slot))
            payload = {
                "expr": spec.get("expr"),
                "value": spec.get("value"),
                "when_expr": spec.get("when"),
                "else_value": spec.get("else"),
                "fmt": int(spec.get("fmt", 2)),
                "enabled": True,
                "updated_at": now(),
                "updated_by": "seed",
            }
            if row is None:
                db.add(AtpParamGlobal(slot=slot, **payload))
                created_g += 1
            else:
                changed = any(getattr(row, k) != v for k, v in payload.items() if k != "updated_at")
                if changed:
                    for k, v in payload.items():
                        setattr(row, k, v)
                    updated_g += 1
                else:
                    skipped_g += 1

        # ---- template rules from *_ .json (skip _common) ----
        created_t = updated_t = skipped_t = 0
        for path in sorted(MAPPINGS.glob("*.json")):
            if path.name == "_common.json":
                continue
            cfg = json.loads(path.read_text(encoding="utf-8"))
            marker = str(cfg.get("marker") or cfg.get("tower_type") or path.stem)
            tower_type = cfg.get("tower_type")
            voltage = cfg.get("voltage_level")
            slots = cfg.get("slots") or {}
            name = str(cfg.get("name") or path.stem)
            row = db.scalar(
                select(AtpParamTemplate).where(
                    AtpParamTemplate.marker == marker,
                    AtpParamTemplate.name == name,
                )
            )
            payload = {
                "marker": marker,
                "tower_type": tower_type,
                "voltage_level": str(voltage) if voltage is not None else None,
                "circuit_count": None,
                "scene_type": None,
                "arrester_config": None,
                "structure_kind": None,
                "priority": int(cfg.get("priority", 100)),
                "mode": "merge",
                "enabled": True,
                "slots_json": slots,
                "defaults_json": dict(cfg.get("defaults") or {}),
                "updated_at": now(),
                "updated_by": "seed",
            }
            if row is None:
                db.add(AtpParamTemplate(id=str(uuid.uuid4()), name=name, created_at=now(), **payload))
                created_t += 1
            else:
                changed = any(getattr(row, k) != v for k, v in payload.items())
                if changed:
                    for k, v in payload.items():
                        setattr(row, k, v)
                    updated_t += 1
                else:
                    skipped_t += 1

        db.commit()
        print(f"globals: +{created_g} ~{updated_g} ={skipped_g}; templates: +{created_t} ~{updated_t} ={skipped_t}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
