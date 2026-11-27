"""Seed atp_param_template / atp_param_global from atp_param_mappings JSON.

Mirrors the C# ATP model matrix: one base rule per tower_type (ganzi/guxing/
jiubei/maotou/shangzi/sihuita/zhiliu/vzhiliu/menxing), plus voltage-specific
rules (maotou_750, maotou_1000) as finer-dimension rules, and _common.json
globals as atp_param_global rows. Idempotent: skips existing rows by name+marker.

`zv_tower_params.json` 是一条**无维度（通配所有塔型/电压）**的规则，承载 ZV 改造
四变量槽位（ZRE01_/ZRE02_/ZRE03_/VRE___，含 default 兜底）；它和其他模板一样
由本脚本 upsert 进 atp_param_template，从而让参数模板管理页可编辑、并让
「槽位覆盖检测」按模板槽位正确计数（不再误报 missing）。

Run inside the api container:
    sudo docker cp <repo>/scripts/seed_atp_templates.py lp-api-1:/tmp/
    sudo docker exec lp-api-1 sh -c 'cd /app && PYTHONPATH=/app python /tmp/seed_atp_templates.py'

增量补一条新规则（不改动既有模板，避免覆盖页面上的人工编辑）：
    python /tmp/seed_atp_templates.py --only zv_tower_params
⚠️ ``--only`` 只适合「库里已有完整的塔型基础模板、只补新规则」的场景；
   空库请跑全量，否则 config_db 会只看到被 --only 播种的那一条规则。
"""
from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 atp_param_mappings JSON 播种参数模板/全局槽位")
    parser.add_argument(
        "--only",
        default="",
        help="只处理指定 marker（模板）或 slot（全局），逗号分隔；用于增量补规则、不改动既有模板",
    )
    args = parser.parse_args(argv)
    only = {item.strip() for item in (args.only or "").split(",") if item.strip()}

    db = SessionLocal()
    try:
        # ---- globals from _common.json ----
        common = json.loads((MAPPINGS / "_common.json").read_text(encoding="utf-8"))
        created_g = updated_g = skipped_g = 0
        for slot, spec in (common.get("globals") or {}).items():
            if only and slot not in only:
                continue
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
            if only and marker not in only:
                continue
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
