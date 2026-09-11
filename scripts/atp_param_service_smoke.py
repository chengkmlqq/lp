"""ATP 参数模板服务层冒烟：树 / 试算 / 派生 / 增删改 + 运行时接入一致性。"""
from __future__ import annotations

import os

os.environ["ATP_MAPPING_MODE"] = "config_db"

from app.core.database import SessionLocal  # noqa: E402
from app.services.atp_param_config import cache_info, invalidate  # noqa: E402
from app.services.atp_param_template_service import (  # noqa: E402
    build_tree,
    create_template,
    delete_template,
    derive_template,
    list_templates,
    meta_options,
    resolve_preview,
    update_template,
)


def main() -> int:
    db = SessionLocal()
    try:
        invalidate()
        print("缓存:", cache_info())
        tree = build_tree(db)
        print(f"树: 总规则 {tree['total']} 个；根={tree['root']['label']} 全局槽位={tree['root']['defined_slots']}")
        for group in tree["root"]["children"]:
            marks = []
            for tower in group["children"]:
                marks.append(f"{tower['label']}({tower['defined_slots']}/{tower['effective_slots']})" + ("" if tower["has_template"] else "[继承]"))
                for child in tower["children"]:
                    marks.append(f"  └{child['label']}({child['defined_slots']})")
            print(f"  {group['label']}: " + ", ".join(marks))

        preview = resolve_preview(db, {"tower_type": "maotou", "voltage_level": 1000})
        print("试算(maotou/1000kV) 命中链:", preview["chain"], "槽位:", len(preview["slots"]))

        preview_750 = resolve_preview(db, {"tower_type": "maotou", "voltage_level": 750})
        print("试算(maotou/750kV) 命中链:", preview_750["chain"], "槽位:", len(preview_750["slots"]))

        templates = list_templates(db, tower_type="maotou")
        base = next(item for item in templates if not item["voltage_level"])
        derived = derive_template(db, {"parent_id": base["id"], "tower_type": "maotou", "voltage_level": "220"})
        print("派生建议名:", derived["suggested_name"], "继承槽位数:", len(derived["inherited_slots"]), "链:", derived["chain"])

        created = create_template(
            db,
            {
                "name": "烟测-临时规则",
                "tower_type": "ganzi",
                "voltage_level": "330",
                "priority": 100,
                "slots": {"RELE01": {"expr": "h_u + 1.0", "fmt": 1}},
            },
            operator="smoke",
        )
        print("新建:", created["id"][:8], created["name"], "specificity =", created["specificity"])
        updated = update_template(db, created["id"], {"name": "烟测-临时规则(改)", "slots": {"RELE01": {"expr": "h_u + 2.0", "fmt": 1}}}, operator="smoke")
        print("更新后:", updated["name"], updated["slots"]["RELE01"]["expr"])
        preview_created = resolve_preview(db, {"tower_type": "ganzi", "voltage_level": 330, "rule_id": created["id"]})
        hit = [item for item in preview_created["slots"] if item["slot"] == "RELE01"]
        print("试算命中新建规则:", hit[0] if hit else "未命中", "| 差异槽位:", [item["slot"] for item in preview_created["diff"]])
        delete_template(db, created["id"])
        print("删除完成，剩余规则数:", len(list_templates(db)))

        meta = meta_options(db)
        print("维度选项: 塔型", len(meta["tower_types"]), "电压", len(meta["voltages"]), "场景", len(meta["scene_types"]), "避雷器", len(meta["arrester_configs"]), "槽位", len(meta["slot_names"]))
        print("\n✅ 服务层冒烟通过")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
