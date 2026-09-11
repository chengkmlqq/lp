"""真实快照 A/B：代码路径 vs 配置路径（config_db）逐参数对比（用真实塔快照）。"""
from __future__ import annotations

import os
import sys

from sqlalchemy import text

from app.core.database import SessionLocal

os.environ["ATP_MAPPING_MODE"] = "config_db"
from app.services.atp_param_config import get_rules  # noqa: E402
from app.services.atp_param_resolver import build_context, resolve_params  # noqa: E402
from app.services.fl_analysis_external import compute_csharp_atp_params  # noqa: E402


def main() -> int:
    db = SessionLocal()
    rows = db.execute(
        text(
            """
            SELECT s.id, s.tower_no, s.base_tower_json, s.profile_json, l.name AS line_name
            FROM fl_analysis_tower_snapshot s
            JOIN fl_analysis_job j ON j.id = s.job_id
            JOIN power_line l ON l.id = j.line_id
            ORDER BY s.create_date DESC
            LIMIT 40
            """
        )
    ).fetchall()
    db.close()
    if not rows:
        print("无快照数据")
        return 1

    rules = get_rules(force=True)
    if rules is None:
        print("配置不可用")
        return 1

    checked = 0
    failures: list[str] = []
    seen_towers: set[str] = set()
    for snapshot_id, tower_no, base_tower, profile, line_name in rows:
        key = f"{line_name}:{tower_no}"
        if key in seen_towers:
            continue
        seen_towers.add(key)
        options = {"binary_search_current_ka": 146.0}
        # 代码路径：临时强制 code 模式（否则会走到配置路径，比较失去意义）
        os.environ["ATP_MAPPING_MODE"] = "code"
        code_params = compute_csharp_atp_params(
            base_tower=base_tower, profile=profile, execution_options=options
        )
        os.environ["ATP_MAPPING_MODE"] = "config_db"
        context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
        config_params = resolve_params(context, rules).as_dict()
        checked += 1
        diff = {
            slot: (code_params.get(slot), config_params.get(slot))
            for slot in set(code_params) | set(config_params)
            if code_params.get(slot) != config_params.get(slot)
        }
        if diff:
            failures.append(f"[{key}] " + "; ".join(f"{k}: code={v[0]} config={v[1]}" for k, v in list(diff.items())[:6]))

    print(f"真实快照对照：{checked} 个塔（最近 40 条快照去重）")
    for line in failures[:8]:
        print("  ❌", line)
    if failures:
        print(f"❌ 不一致 {len(failures)} 个塔")
        return 1
    print("✅ 真实快照下 代码路径 与 配置路径 逐参数一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
