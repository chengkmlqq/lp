#!/usr/bin/env python3
"""测试线路「回路几何自检」工具（LP-19）。

检查每条测试线路 ``circuit_geometry_json`` 的回路数是否等于其塔型 EGM 期望回路数
（guxing/guxingd=2、sihuita=4、单回塔型=1；直流/特型不校验）。覆盖全部电压/塔型，
避免 TEST-OLD110guxing 这类「单回几何 × 鼓型塔」错配落在其它批量测试上。

用法（脚本在仓库 lp/ 根目录下运行）：

  # 离线：对导出的 JSON 自检（CI / 无数据库连接时可用；发现错配退出码 1）
  python scripts/check_test_line_circuit_geometry.py --input lines.json
  python scripts/check_test_line_circuit_geometry.py --input lines.json \\
      --voltage 110 --tower-type guxing --json

  # 连库：审计 atp_test_line 表的全部测试线路
  python scripts/check_test_line_circuit_geometry.py --db
  python scripts/check_test_line_circuit_geometry.py --db --voltage 110 --tower-type guxing

  # 下线（置 status=disabled）错配线路；默认只报告不改动（dry-run）
  python scripts/check_test_line_circuit_geometry.py --db --disable --voltage 110 --tower-type guxing

--input JSON 格式（数组）：

  [
    {"code": "TEST-OLD110guxing", "voltage_level": "110",
     "tower_type": "guxing", "status": "enabled",
     "base_tower": {"circuit_geometry_json": {"I": {..}, "II": {..}}}}
  ]

  ``base_tower`` 即快照里的 base_tower_json；缺 circuit_geometry_json 的记录会被跳过
  （不据此判定错配）。tower_type 可为归一化基名（guxing）或模型串（s110guxing）。

说明：
  * 本工具仅做「自检 + 可选下线」。绕击 EGM 的调用方（fl_analysis_service）已统一
    容错：几何不符时跳过 EGM、保留反击结果、不再整塔失败；下线只是数据卫生，避免
    错配线路被后续批量测试选中，并非修复计算失败的必要步骤。
  * 老的外业台账 Line（TEST-* 真实线路）若不在 atp_test_line 表，用 --input 导出其
    快照 base_tower_json 后同样可自检 —— 自检逻辑只依赖 (tower_type, base_tower)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 让脚本可从仓库任意目录运行：把 lp/api 加入 sys.path。
_API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.services.atp_egm_trip_rate import circuit_geometry_mismatch  # noqa: E402


def audit_records(
    records: list[dict[str, Any]],
    *,
    voltage: str | None = None,
    tower_type: str | None = None,
) -> list[dict[str, Any]]:
    """纯函数：对 (tower_type, base_tower) 逐条自检，返回错配清单。

    可按电压精确过滤、按塔型子串过滤（同时兼容归一化基名与模型串）。
    不触碰数据库，便于在单测与无数据库环境里复用。
    """
    findings: list[dict[str, Any]] = []
    for rec in records:
        v = str(rec.get("voltage_level") or "")
        t = str(rec.get("tower_type") or "")
        if voltage and v != str(voltage):
            continue
        if tower_type and tower_type.lower() not in t.lower():
            continue
        base_tower = rec.get("base_tower") or {}
        if not isinstance(base_tower, dict) or not base_tower.get("circuit_geometry_json"):
            continue
        reason = circuit_geometry_mismatch(t, base_tower)
        if reason:
            findings.append(
                {
                    "id": rec.get("id") or rec.get("code") or "",
                    "code": rec.get("code") or "",
                    "voltage_level": v,
                    "tower_type": t,
                    "status": rec.get("status") or "",
                    "reason": reason,
                }
            )
    return findings


def _load_from_db() -> list[dict[str, Any]]:
    """从 atp_test_line 读取全部测试线路，取快照里的 base_tower。"""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.atp_test_line import AtpTestLine

    records: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for row in db.execute(select(AtpTestLine)).scalars().all():
            snap = row.snapshot_json if isinstance(row.snapshot_json, dict) else {}
            base_tower = (snap.get("base_tower") or {}) if isinstance(snap, dict) else {}
            records.append(
                {
                    "id": row.id,
                    "code": row.code,
                    "voltage_level": row.voltage_level,
                    "tower_type": row.tower_type,
                    "status": row.status,
                    "base_tower": base_tower,
                }
            )
    return records


def _disable_findings(findings: list[dict[str, Any]]) -> int:
    """把错配的 atp_test_line 置 status=disabled（显式 --disable 才调用）。"""
    from app.core.database import SessionLocal
    from app.models.atp_test_line import AtpTestLine

    ids = {f["id"] for f in findings if f.get("id")}
    if not ids:
        return 0
    disabled = 0
    with SessionLocal() as db:
        for row in db.query(AtpTestLine).filter(AtpTestLine.id.in_(ids)).all():
            row.status = "disabled"
            disabled += 1
        db.commit()
    return disabled


def _print_report(records_count: int, findings: list[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"checked": records_count, "mismatches": findings}, ensure_ascii=False, indent=2))
        return
    print(f"已自检 {records_count} 条测试线路，发现 {len(findings)} 条回路几何错配。")
    for f in findings:
        print(f"  - [{f['voltage_level']}kV/{f['tower_type']}] {f['code'] or f['id']} "
              f"(status={f['status']}): {f['reason']}")
    if not findings:
        print("回路几何自检通过：无单回/双回（或多回）错配。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测试线路回路几何自检（LP-19）")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--input", metavar="FILE", help="离线 JSON 记录文件（数组）")
    src.add_argument("--db", action="store_true", help="从 atp_test_line 连库审计")
    parser.add_argument("--voltage", help="仅自检该电压等级（如 110）")
    parser.add_argument("--tower-type", help="仅自检该塔型（子串匹配，如 guxing）")
    parser.add_argument("--disable", action="store_true", help="下线错配线路（仅 --db；默认 dry-run）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    if args.disable and not args.db:
        parser.error("--disable 仅适用于 --db 模式（离线 --input 无可下线的记录）")

    if args.input:
        path = Path(args.input)
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            parser.error("--input 文件顶层必须是数组")
        db_mode = False
    else:
        # 默认连库审计（--db 可省略）。
        try:
            records = _load_from_db()
        except Exception as exc:  # noqa: BLE001
            print(
                f"无法连接数据库审计 atp_test_line：{type(exc).__name__}: {exc}\n"
                "可改用 --input lines.json 对导出的快照做离线自检。",
                file=sys.stderr,
            )
            return 2
        db_mode = True

    findings = audit_records(
        records, voltage=args.voltage, tower_type=args.tower_type
    )
    _print_report(len(records), findings, as_json=args.json)

    if findings and args.disable and db_mode:
        n = _disable_findings(findings)
        print(f"已下线 {n} 条错配测试线路（status=disabled）。")

    # 发现错配即返回 1（供 CI / 批量测试前置门禁）；已执行下线则视为已处置，返回 0。
    return 1 if findings and not (db_mode and args.disable) else 0


if __name__ == "__main__":
    raise SystemExit(main())
