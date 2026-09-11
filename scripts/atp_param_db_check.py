"""验证 DB 路径（atp_param_template + atp_param_global）与代码路径逐字节一致。"""
from __future__ import annotations

import os

# 对照必须走代码路径：强制 code 模式（运行时默认 config_db 会短路到配置路径）
os.environ["ATP_MAPPING_MODE"] = "code"

import itertools
import json
import sys

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.atp_param_resolver import (
    compute_params_from_config,
    globals_from_rows,
    load_mappings,
    load_mappings_from_rows,
)
from app.services.fl_analysis_external import compute_csharp_atp_params

sys.path.insert(0, "/app/scripts")
from atp_param_golden_test import GEOMETRIES, TIMES, TOWER_TYPES, VOLTAGES, WAVE_TYPES, build_case, diff_dicts  # noqa: E402


def main() -> int:
    db = SessionLocal()
    tpl_rows = [dict(r._mapping) for r in db.execute(text("SELECT * FROM atp_param_template WHERE enabled")).fetchall()]
    glob_rows = [dict(r._mapping) for r in db.execute(text("SELECT * FROM atp_param_global WHERE enabled")).fetchall()]
    db.close()
    print(f"DB 载入：模板 {len(tpl_rows)} 条、全局槽位 {len(glob_rows)} 个")

    json_rules = load_mappings()
    common = {
        "globals": globals_from_rows(glob_rows),
        "exact_canonical": json_rules.exact_canonical,
        "marker_order": json_rules.marker_order,
        "default_marker": json_rules.default_marker,
    }
    db_rules = load_mappings_from_rows(tpl_rows, common=common)

    total = 0
    failures: list[str] = []
    for tower_type, voltage, geom, wave, (head, tail), current in itertools.product(
        TOWER_TYPES, VOLTAGES, GEOMETRIES, WAVE_TYPES, TIMES, [146.0]
    ):
        base_tower, profile, options = build_case(tower_type, voltage, geom, wave, head, tail, current)
        code = compute_csharp_atp_params(base_tower=base_tower, profile=profile, execution_options=options)
        cfg_db = compute_params_from_config(
            base_tower=base_tower, profile=profile, execution_options=options, rules=db_rules
        )
        total += 1
        problems = diff_dicts(code, cfg_db)
        if problems:
            failures.append(f"[{tower_type}/v{voltage}/wave{wave}] " + "; ".join(problems[:4]))
        if len(failures) >= 6:
            break

    print(f"DB 路径对照用例：{total} 组")
    if failures:
        print("❌ 不一致：")
        for item in failures:
            print(" ", item)
        return 1
    print("✅ DB 路径与代码路径逐字节一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
