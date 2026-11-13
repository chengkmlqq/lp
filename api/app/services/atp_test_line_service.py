"""ATP 测试线路（单塔基准）服务。

职责：
1. **CRUD + 冻结快照**：任何写操作后重算 ``snapshot_json`` / ``snapshot_hash``，
   让「同一条测试线路 = 逐字节相同的输入」成立（回归可复现的前提）。
2. **三级解析** ``resolve_test_line``：模型级绑定 → 几何维匹配 → 降级（2 维唯一）→ 无命中。
   无命中**不静默降级**到模板模式，而是把可执行的补救指令交给调用方（前端展示「一键派生」）。
3. **派生（derive）**：按 5 级来源把工程字段自动填出来，逐字段标注出处；干跑不落库。
   级别（可信度由高到低）：L1 历史成功 run / 真实杆塔 → L2 参数模板默认值 →
   L3 塔型号字典 → L4 维度项 extra_json → L5 内置兜底。
4. **装配预览**：给出真实执行时会用的 ``base_tower``/``profile`` 与几何阻断项。

设计约束：
- 派生**不允许**产出跑不通的基准：几何硬约束（避雷线中距、四回几何重合、档距范围）
  在 derive 与 create/update 时都会校验，命中即 ``blockers``，禁止落库。
- 模板默认值不足以填满时，用内置兜底并在 ``warnings`` 里明确标注「兜底，需人工确认」。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.atp_asset import AtpAssetVersion, AtpAssetRun
from ..models.atp_test_line import AtpTestLine, AtpTestLineCircuit
from ..models.atp_test_set import AtpTestSetCase
from ..models.base import utcnow
from ..models.dimension_item import DimensionItem
from ..models.tower_model import TowerModel
from ..schemas.atp_test_line import (
    AtpTestLineCircuitPayload,
    AtpTestLineCreateRequest,
    AtpTestLineDeriveRequest,
    AtpTestLineUpdateRequest,
)
from . import atp_line_snapshot as snapshot_asm

logger = logging.getLogger(__name__)

# 派生来源前缀（写进 derive_rules_json / sources，供 UI 显示来源 Tag）
SRC_RUN = "L1:run"
SRC_TOWER = "L1:tower"
SRC_TEMPLATE = "L2:param_template"
SRC_TOWER_MODEL = "L3:tower_model"
SRC_DIMENSION = "L4:dimension"
SRC_BUILTIN = "L5:builtin"
SRC_MANUAL = "manual"

CIRCUIT_KEYS: tuple[str, ...] = ("I", "II", "III", "IV")

# ── L5 内置兜底：按电压等级给工程参考值（仅当 L1~L4 全缺失时使用，必须标 warning）──
# 数值是常见塔型的量级参考，**不是**任何具体工程的实测值。
_BUILTIN_VOLTAGE_REFERENCE: dict[str, dict[str, Any]] = {
    "35": {"insulator_length_m": 0.45, "spacing": (2.5, 2.5, 2.5), "height": (12.0, 15.0, 18.0), "shield_h": 21.0},
    "66": {"insulator_length_m": 0.7, "spacing": (3.0, 3.0, 3.0), "height": (15.0, 18.0, 21.0), "shield_h": 24.0},
    "110": {"insulator_length_m": 1.2, "spacing": (4.0, 4.0, 4.0), "height": (18.0, 22.0, 26.0), "shield_h": 29.0},
    "220": {"insulator_length_m": 2.0, "spacing": (7.0, 7.0, 7.0), "height": (26.0, 32.0, 38.0), "shield_h": 43.0},
    "330": {"insulator_length_m": 2.9, "spacing": (9.0, 9.0, 9.0), "height": (30.0, 38.0, 46.0), "shield_h": 51.0},
    "500": {"insulator_length_m": 4.45, "spacing": (12.0, 12.0, 12.0), "height": (36.0, 48.0, 60.0), "shield_h": 65.0},
    "750": {"insulator_length_m": 6.0, "spacing": (15.0, 15.0, 15.0), "height": (42.0, 55.0, 68.0), "shield_h": 73.0},
    "800": {"insulator_length_m": 6.4, "spacing": (16.0, 16.0, 16.0), "height": (44.0, 58.0, 72.0), "shield_h": 77.0},
    "1000": {"insulator_length_m": 8.0, "spacing": (18.0, 18.0, 18.0), "height": (48.0, 64.0, 80.0), "shield_h": 85.0},
}


# ─────────────────────────── 小工具 ───────────────────────────


def _normalize_asset_id(asset_id: str | None) -> str | None:
    """共享基准用 NULL 还是空串？

    MySQL 唯一索引下 NULL 互不冲突（多行 NULL 不算重复），因此「同一几何维组
    只能有一条共享基准」必须靠应用层保证 —— 这里统一存 ``None`` 并在写入前做
    「同几何维 + asset_id IS NULL」查重。
    """
    value = (asset_id or "").strip()
    return value or None


def normalize_tower_type(value: str | None) -> str:
    """塔型归一化（``d500guxing`` → ``guxing``），与资产解析口径一致。"""
    from .fl_analysis_external import _normalize_tower_shape_code  # noqa: PLC0415

    raw = (value or "").strip()
    if not raw:
        return ""
    return _normalize_tower_shape_code(raw) or raw


def _num(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _insulator_to_m(value: Any) -> float | None:
    """绝缘子串长归一为**米**：>100 视为毫米（与 build_context 的启发式一致）。"""
    raw = _num(value)
    if raw is None:
        return None
    return round(raw / 1000.0, 4) if raw > 100 else raw


def _suggest_code(*, voltage_level: str, tower_type: str, shield_wire: str, asset_code: str | None) -> str:
    parts = ["TL", str(voltage_level or "NA"), str(tower_type or "NA"), str(shield_wire or "with")]
    code = "-".join(parts)
    if asset_code:
        code = f"{code}-{asset_code}"
    return code[:64]


def _ensure_unique_code(db: Session, code: str, *, exclude_id: str | None = None) -> str:
    candidate = code
    suffix = 1
    while True:
        stmt = select(AtpTestLine.id).where(AtpTestLine.code == candidate)
        if exclude_id:
            stmt = stmt.where(AtpTestLine.id != exclude_id)
        if db.execute(stmt).first() is None:
            return candidate
        suffix += 1
        candidate = f"{code[:58]}-{suffix}"


# ─────────────────────────── 序列化 ───────────────────────────


def serialize_summary(row: AtpTestLine, *, asset_code: str | None = None) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description or "",
        "status": row.status,
        "voltage_level": row.voltage_level,
        "tower_type": row.tower_type,
        "shield_wire": row.shield_wire,
        "scene_type": row.scene_type,
        "arrester_config": row.arrester_config,
        "structure_kind": row.structure_kind,
        "circuit_count": int(row.circuit_count or 1),
        "asset_id": row.asset_id,
        "asset_code": asset_code,
        "span_small_m": row.span_small_m,
        "span_large_m": row.span_large_m,
        "call_height_m": row.call_height_m,
        "insulator_length_m": row.insulator_length_m,
        "current_ka": float(row.current_ka or 31.0),
        "source_kind": row.source_kind,
        "snapshot_hash": row.snapshot_hash,
        "used_count": int(row.used_count or 0),
        "last_used_at": row.last_used_at,
        "create_date": row.create_date,
        "update_date": row.update_date,
        "update_user": row.update_user,
    }


def serialize_detail(row: AtpTestLine, *, asset_code: str | None = None) -> dict[str, Any]:
    data = serialize_summary(row, asset_code=asset_code)
    data.update(
        {
            "ground_resistance_ohm": row.ground_resistance_ohm,
            "lightning_density": row.lightning_density,
            "altitude_m": row.altitude_m,
            "terrain": row.terrain,
            "slope_1": row.slope_1,
            "slope_2": row.slope_2,
            "tower_no": row.tower_no,
            "tower_model": row.tower_model,
            "shield_wire_height_m": row.shield_wire_height_m,
            "shield_wire_left_mid_m": row.shield_wire_left_mid_m,
            "shield_wire_right_mid_m": row.shield_wire_right_mid_m,
            "protection_angle_left_deg": row.protection_angle_left_deg,
            "protection_angle_right_deg": row.protection_angle_right_deg,
            "angle_deg": row.angle_deg,
            "phase_sequence_1": row.phase_sequence_1,
            "phase_sequence_2": row.phase_sequence_2,
            "phase_sequence_3": row.phase_sequence_3,
            "phase_sequence_4": row.phase_sequence_4,
            "arrester_a": row.arrester_a,
            "arrester_b": row.arrester_b,
            "arrester_c": row.arrester_c,
            "current_type": row.current_type,
            "current_head_time_us": row.current_head_time_us,
            "current_tail_time_us": row.current_tail_time_us,
            "source_asset_id": row.source_asset_id,
            "source_run_id": row.source_run_id,
            "source_tower_id": row.source_tower_id,
            "derive_rules_json": row.derive_rules_json or {},
            "snapshot_json": row.snapshot_json or {},
            "snapshot_date": row.snapshot_date,
            "circuits": [
                {
                    "id": c.id,
                    "circuit_no": c.circuit_no,
                    "phase_sequence": c.phase_sequence,
                    "spacing_upper_m": c.spacing_upper_m,
                    "spacing_middle_m": c.spacing_middle_m,
                    "spacing_lower_m": c.spacing_lower_m,
                    "height_upper_m": c.height_upper_m,
                    "height_middle_m": c.height_middle_m,
                    "height_lower_m": c.height_lower_m,
                }
                for c in sorted(row.circuits or [], key=lambda c: c.circuit_no)
            ],
        }
    )
    return data


def _asset_code_map(db: Session, asset_ids: Iterable[str | None]) -> dict[str, str]:
    ids = [aid for aid in {a for a in asset_ids if a}]
    if not ids:
        return {}
    rows = db.execute(select(AtpAssetVersion.id, AtpAssetVersion.code).where(AtpAssetVersion.id.in_(ids))).all()
    return {row[0]: row[1] for row in rows}


# ─────────────────────────── 查询 ───────────────────────────


def get_test_line_by_id(db: Session, test_line_id: str) -> AtpTestLine | None:
    return db.execute(
        select(AtpTestLine).where(AtpTestLine.id == test_line_id)
    ).scalar_one_or_none()


def list_test_lines(
    db: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    keyword: str | None = None,
    voltage_level: str | None = None,
    tower_type: str | None = None,
    shield_wire: str | None = None,
    status_value: str | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    stmt = select(AtpTestLine)
    total_stmt = select(func.count()).select_from(AtpTestLine)

    def _apply(condition: Any) -> None:
        nonlocal stmt, total_stmt
        stmt = stmt.where(condition)
        total_stmt = total_stmt.where(condition)

    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        _apply(
            or_(
                AtpTestLine.code.ilike(like),
                AtpTestLine.name.ilike(like),
                AtpTestLine.description.ilike(like),
            )
        )
    if voltage_level:
        _apply(AtpTestLine.voltage_level == voltage_level.strip())
    if tower_type:
        _apply(AtpTestLine.tower_type == normalize_tower_type(tower_type))
    if shield_wire:
        _apply(AtpTestLine.shield_wire == shield_wire.strip())
    if status_value:
        _apply(AtpTestLine.status == status_value.strip())
    if asset_id:
        _apply(AtpTestLine.asset_id == asset_id.strip())

    total = int(db.scalar(total_stmt) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(
                AtpTestLine.voltage_level.asc(),
                AtpTestLine.tower_type.asc(),
                AtpTestLine.shield_wire.asc(),
                AtpTestLine.create_date.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    codes = _asset_code_map(db, (row.asset_id for row in rows))
    return {
        "items": [serialize_summary(row, asset_code=codes.get(row.asset_id or "")) for row in rows],
        "total": total,
    }


def get_test_line_detail(db: Session, test_line_id: str) -> dict[str, Any]:
    row = get_test_line_by_id(db, test_line_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")
    codes = _asset_code_map(db, [row.asset_id])
    return serialize_detail(row, asset_code=codes.get(row.asset_id or ""))


# ─────────────────────────── 校验（几何硬约束）───────────────────────────


def validate_draft(
    draft: dict[str, Any], circuits: list[AtpTestLineCircuitPayload]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """校验草稿，返回 (blockers, warnings)。

    blockers 非空 → 不可落库（生成出来也跑不通 / 结果失真）。
    """
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not str(draft.get("voltage_level") or "").strip():
        blockers.append({"field": "voltage_level", "reason": "电压等级必填"})
    if not str(draft.get("tower_type") or "").strip():
        blockers.append({"field": "tower_type", "reason": "塔型必填（用于参数模板与资产匹配）"})

    left = _num(draft.get("shield_wire_left_mid_m"))
    right = _num(draft.get("shield_wire_right_mid_m"))
    shield_wire = str(draft.get("shield_wire") or "with")
    if shield_wire == "with":
        if left is None or right is None:
            blockers.append(
                {
                    "field": "shield_wire_left_mid_m",
                    "reason": "有避雷线时左右中距必填（几何管线缺该项会直接 RuntimeError）",
                }
            )
        elif left <= 0 or right <= 0:
            blockers.append(
                {"field": "shield_wire_left_mid_m", "reason": "避雷线左右中距必须大于 0"}
            )

    for field in ("span_small_m", "span_large_m"):
        value = _num(draft.get(field))
        if value is not None and not (0 < value <= 3000):
            blockers.append({"field": field, "reason": "档距需落在 (0, 3000] 米"})

    insulator = _num(draft.get("insulator_length_m"))
    if insulator is not None and insulator > 100:
        blockers.append(
            {
                "field": "insulator_length_m",
                "reason": f"绝缘子串长按「米」存，收到 {insulator}（疑似毫米），请换算后再保存",
            }
        )

    # 回路数：与提交的回路几何条数对齐；四回时必须 4 套独立几何
    circuit_count = int(_num(draft.get("circuit_count")) or 1)
    payload_nos = sorted({int(c.circuit_no) for c in circuits})
    if payload_nos and payload_nos != list(range(1, len(payload_nos) + 1)):
        warnings.append(
            {
                "field": "circuits",
                "reason": f"回路编号不连续：{payload_nos}（应为 1..N）",
            }
        )
    if circuit_count <= 0 or circuit_count > 4:
        blockers.append({"field": "circuit_count", "reason": "回路数需在 1~4"})
    elif circuits and len(circuits) != circuit_count:
        warnings.append(
            {
                "field": "circuit_count",
                "reason": f"回路数为 {circuit_count}，但提交了 {len(circuits)} 组回路几何",
            }
        )

    # 四回几何重合检查（LCC 会判定导体重合、不产 .pch）
    if len(circuits) > 1:
        signatures = {
            (
                c.spacing_upper_m,
                c.spacing_middle_m,
                c.spacing_lower_m,
                c.height_upper_m,
                c.height_middle_m,
                c.height_lower_m,
            )
            for c in circuits
        }
        if len(signatures) < len(circuits):
            blockers.append(
                {
                    "field": "circuits",
                    "reason": "多回路几何完全相同 → LCC 判定导体重合、不产 .pch，需各回路独立几何",
                }
            )

    for circuit in circuits:
        if all(
            getattr(circuit, f) is None
            for f in ("spacing_upper_m", "height_upper_m", "height_middle_m", "height_lower_m")
        ):
            blockers.append(
                {
                    "field": f"circuits[{circuit.circuit_no}]",
                    "reason": "该回路没有任何相中距/相高数据",
                }
            )
    return blockers, warnings


# ─────────────────────────── 快照重算 ───────────────────────────


def _replace_circuits(
    db: Session, row: AtpTestLine, circuits: Iterable[AtpTestLineCircuitPayload]
) -> None:
    existing = {c.circuit_no: c for c in list(row.circuits or [])}
    seen: set[int] = set()
    for payload in circuits:
        seen.add(int(payload.circuit_no))
        current = existing.get(int(payload.circuit_no))
        if current is None:
            current = AtpTestLineCircuit(test_line_id=row.id, circuit_no=int(payload.circuit_no))
            db.add(current)
            row.circuits.append(current)
        current.phase_sequence = payload.phase_sequence
        current.spacing_upper_m = payload.spacing_upper_m
        current.spacing_middle_m = payload.spacing_middle_m
        current.spacing_lower_m = payload.spacing_lower_m
        current.height_upper_m = payload.height_upper_m
        current.height_middle_m = payload.height_middle_m
        current.height_lower_m = payload.height_lower_m
    for circuit_no, current in existing.items():
        if circuit_no not in seen:
            row.circuits.remove(current)
            db.delete(current)


def rebuild_snapshot(db: Session, row: AtpTestLine) -> dict[str, Any]:
    """重算并写入冻结快照（同时回填 circuit_count）。"""
    db.flush()
    snapshot = snapshot_asm.build_snapshot(row)
    base_tower = snapshot.get("base_tower") or {}
    profile = snapshot.get("profile") or {}
    row.snapshot_json = snapshot
    row.snapshot_hash = snapshot.get("snapshot_hash")
    row.snapshot_date = utcnow()
    # 回路数由几何推导（有相高数据的回路条数），与参数模板 context.circuit_count 同口径
    derived_count = sum(
        1
        for key in CIRCUIT_KEYS
        if any(
            (base_tower.get("circuit_geometry_json", {}).get(key, {}).get("phase_height_m") or {}).get(k)
            is not None
            for k in ("upper", "middle", "lower")
        )
    )
    if derived_count:
        row.circuit_count = derived_count
    _ = profile
    return snapshot


# ─────────────────────────── 创建 / 编辑 / 删除 ───────────────────────────


def _apply_geometry_fields(row: AtpTestLine, data: dict[str, Any]) -> None:
    for field in (
        "voltage_level",
        "tower_type",
        "shield_wire",
        "scene_type",
        "arrester_config",
        "structure_kind",
        "circuit_count",
        "asset_id",
        "span_small_m",
        "span_large_m",
        "ground_resistance_ohm",
        "lightning_density",
        "altitude_m",
        "terrain",
        "slope_1",
        "slope_2",
        "tower_no",
        "tower_model",
        "call_height_m",
        "insulator_length_m",
        "shield_wire_height_m",
        "shield_wire_left_mid_m",
        "shield_wire_right_mid_m",
        "protection_angle_left_deg",
        "protection_angle_right_deg",
        "angle_deg",
        "phase_sequence_1",
        "phase_sequence_2",
        "phase_sequence_3",
        "phase_sequence_4",
        "arrester_a",
        "arrester_b",
        "arrester_c",
        "current_ka",
        "current_type",
        "current_head_time_us",
        "current_tail_time_us",
    ):
        if field in data:
            value = data[field]
            if field == "asset_id":
                value = _normalize_asset_id(value)
            elif field == "tower_type" and value:
                value = normalize_tower_type(str(value))
            row.__setattr__(field, value)


def _check_geometry_conflict(
    db: Session, *, row: AtpTestLine, exclude_id: str | None = None
) -> None:
    """同一几何维组 + 同 asset_id 只能有一条（MySQL 唯一索引对 NULL 不生效，应用层兜）。"""
    stmt = select(AtpTestLine.id).where(
        AtpTestLine.voltage_level == row.voltage_level,
        AtpTestLine.tower_type == row.tower_type,
        AtpTestLine.shield_wire == row.shield_wire,
    )
    if row.asset_id is None:
        stmt = stmt.where(AtpTestLine.asset_id.is_(None))
    else:
        stmt = stmt.where(AtpTestLine.asset_id == row.asset_id)
    if exclude_id:
        stmt = stmt.where(AtpTestLine.id != exclude_id)
    if db.execute(stmt).first() is not None:
        scope = f"模型专用（asset_id={row.asset_id}）" if row.asset_id else "共享基准"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"已存在同一几何维组的{scope}测试线路："
                f"{row.voltage_level}kV / {row.tower_type} / {row.shield_wire}。"
                "如需变体请改用「复制」，或调整维度组合。"
            ),
        )


def create_test_line(
    db: Session,
    *,
    payload: AtpTestLineCreateRequest,
    actor_user_id: str | None,
    allow_warnings: bool = True,
) -> dict[str, Any]:
    data = payload.model_dump(exclude={"circuits", "code", "name", "description", "status"})
    circuits = list(payload.circuits or [])
    blockers, warnings = validate_draft(data, circuits)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "测试线路几何校验未通过", "blockers": blockers},
        )
    if warnings and not allow_warnings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "存在告警，未确认前不允许落库", "warnings": warnings},
        )

    asset_code = None
    if payload.asset_id:
        asset = db.get(AtpAssetVersion, payload.asset_id)
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"ATP 资产不存在：{payload.asset_id}"
            )
        asset_code = asset.code

    row = AtpTestLine(
        code=_ensure_unique_code(
            db,
            payload.code
            or _suggest_code(
                voltage_level=str(data.get("voltage_level") or ""),
                tower_type=str(data.get("tower_type") or ""),
                shield_wire=str(data.get("shield_wire") or "with"),
                asset_code=asset_code,
            ),
        ),
        name=payload.name or f"{data.get('voltage_level')}kV {data.get('tower_type')} 测试线路",
        description=payload.description or "",
        status=payload.status,
        source_kind=payload.source_kind,
        source_asset_id=payload.source_asset_id,
        source_run_id=payload.source_run_id,
        source_tower_id=payload.source_tower_id,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    _apply_geometry_fields(row, data)
    db.add(row)
    db.flush()
    _check_geometry_conflict(db, row=row, exclude_id=row.id)
    _replace_circuits(db, row, circuits)
    rebuild_snapshot(db, row)
    db.commit()
    db.refresh(row)
    codes = _asset_code_map(db, [row.asset_id])
    return serialize_detail(row, asset_code=codes.get(row.asset_id or ""))


def update_test_line(
    db: Session,
    *,
    test_line_id: str,
    payload: AtpTestLineUpdateRequest,
    actor_user_id: str | None,
) -> dict[str, Any]:
    row = get_test_line_by_id(db, test_line_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")

    data = payload.model_dump(exclude_unset=True, exclude={"circuits", "reset_snapshot"})
    # 冻结的线路禁止「自动重派生」，但人工编辑是允许的（冻结语义见设计文档 §4.1）
    if payload.code is not None:
        row.code = _ensure_unique_code(db, payload.code.strip(), exclude_id=row.id)
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.status is not None:
        row.status = payload.status

    _apply_geometry_fields(row, data)

    circuits: list[AtpTestLineCircuitPayload] | None = payload.circuits
    if circuits is None:
        circuits = [
            AtpTestLineCircuitPayload(
                circuit_no=c.circuit_no,
                phase_sequence=c.phase_sequence,
                spacing_upper_m=c.spacing_upper_m,
                spacing_middle_m=c.spacing_middle_m,
                spacing_lower_m=c.spacing_lower_m,
                height_upper_m=c.height_upper_m,
                height_middle_m=c.height_middle_m,
                height_lower_m=c.height_lower_m,
            )
            for c in sorted(row.circuits or [], key=lambda c: c.circuit_no)
        ]

    draft = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    blockers, warnings = validate_draft(draft, circuits)
    if blockers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "测试线路几何校验未通过", "blockers": blockers},
        )

    _check_geometry_conflict(db, row=row, exclude_id=row.id)
    if payload.circuits is not None:
        _replace_circuits(db, row, circuits)
    row.update_user = actor_user_id
    row.update_date = utcnow()
    rebuild_snapshot(db, row)
    db.commit()
    db.refresh(row)
    codes = _asset_code_map(db, [row.asset_id])
    return serialize_detail(row, asset_code=codes.get(row.asset_id or ""))


def list_usage(db: Session, test_line_id: str) -> dict[str, Any]:
    row = get_test_line_by_id(db, test_line_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")
    items: list[dict[str, Any]] = []
    assets = list(
        db.scalars(select(AtpAssetVersion).where(AtpAssetVersion.test_line_id == test_line_id)).all()
    )
    for asset in assets:
        items.append({"kind": "asset", "id": asset.id, "code": asset.code, "name": asset.name})
    cases = list(
        db.scalars(select(AtpTestSetCase).where(AtpTestSetCase.test_line_id == test_line_id)).all()
    )
    for case in cases:
        items.append(
            {
                "kind": "test_set_case",
                "id": case.id,
                "code": case.job_kind,
                "name": case.name or "(未命名用例)",
            }
        )
    return {"test_line_id": test_line_id, "items": items, "total": len(items)}


def delete_test_line(db: Session, test_line_id: str) -> None:
    row = get_test_line_by_id(db, test_line_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")
    usage = list_usage(db, test_line_id)
    if usage["total"]:
        refs = "、".join(f"{i['kind']}:{i.get('code') or i['id']}" for i in usage["items"][:5])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该测试线路仍被引用（{usage['total']} 处：{refs}），请先解除绑定",
        )
    db.delete(row)
    db.commit()


def clone_test_line(
    db: Session,
    *,
    test_line_id: str,
    code: str | None,
    name: str | None,
    overrides: dict[str, Any],
    actor_user_id: str | None,
) -> dict[str, Any]:
    """复制为同几何维新样本（改电压/塔型/避雷线时用）。"""
    source = get_test_line_by_id(db, test_line_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")
    detail = serialize_detail(source)
    data: dict[str, Any] = {
        field: detail.get(field)
        for field in (
            "voltage_level", "tower_type", "shield_wire", "scene_type", "arrester_config",
            "structure_kind", "circuit_count", "span_small_m", "span_large_m",
            "ground_resistance_ohm", "lightning_density", "altitude_m", "terrain",
            "slope_1", "slope_2", "tower_no", "tower_model", "call_height_m",
            "insulator_length_m", "shield_wire_height_m", "shield_wire_left_mid_m",
            "shield_wire_right_mid_m", "protection_angle_left_deg",
            "protection_angle_right_deg", "angle_deg", "phase_sequence_1",
            "phase_sequence_2", "phase_sequence_3", "phase_sequence_4",
            "arrester_a", "arrester_b", "arrester_c", "current_ka", "current_type",
            "current_head_time_us", "current_tail_time_us",
        )
    }
    data.update(overrides or {})
    data["asset_id"] = None  # 复制体默认是共享基准，避免与源争同一模型绑定
    circuits = [
        AtpTestLineCircuitPayload(**{k: c[k] for k in (
            "circuit_no", "phase_sequence", "spacing_upper_m", "spacing_middle_m",
            "spacing_lower_m", "height_upper_m", "height_middle_m", "height_lower_m",
        )})
        for c in detail.get("circuits") or []
    ]
    payload = AtpTestLineCreateRequest(
        **data,
        code=code,
        name=name or f"{source.name} 副本",
        description=source.description or "",
        status="enabled",
        source_kind="manual",
        circuits=circuits,
    )
    return create_test_line(db, payload=payload, actor_user_id=actor_user_id)


# ─────────────────────────── 三级解析 ───────────────────────────


def resolve_test_line(
    db: Session,
    *,
    test_line_id: str | None = None,
    asset: AtpAssetVersion | None = None,
    voltage_level: str | None = None,
    tower_type: str | None = None,
    shield_wire: str | None = None,
    include_degraded: bool = True,
) -> tuple[AtpTestLine | None, str]:
    """解析「本次测试该用哪条测试线路」。

    返回 ``(row, matched_by)``，``matched_by`` ∈ bound / geometry / degraded / none。

    优先级：
    1. 显式 ``test_line_id``（校验存在且未停用）
    2. ``asset.test_line_id``（模型级绑定）
    3. 几何维三元组匹配 ``status=enabled`` 的共享基准（asset_id IS NULL）
    4. 降级：仅 ``(voltage_level, tower_type)`` 且唯一 → 记 degraded（调用方须记录，
       因为「有无避雷线」会改变几何，降级意味着基准可能不完全匹配）
    5. 无命中 → ``(None, "none")``，**不静默回退到 template 模式**
    """
    if test_line_id:
        row = get_test_line_by_id(db, test_line_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"测试线路不存在：{test_line_id}"
            )
        if row.status == "disabled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"测试线路 {row.code} 已停用，请启用后再用于测试",
            )
        return row, "bound"

    if asset is not None and getattr(asset, "test_line_id", None):
        bound = get_test_line_by_id(db, str(asset.test_line_id))
        if bound is not None and bound.status != "disabled":
            return bound, "bound"

    voltage = (voltage_level or getattr(asset, "voltage_level", None) or "").strip()
    tower = normalize_tower_type(tower_type or getattr(asset, "tower_type", None))
    shield = (shield_wire or getattr(asset, "shield_wire", None) or "with").strip()
    if not voltage or not tower:
        return None, "none"

    def _base_stmt():
        return select(AtpTestLine).where(
            AtpTestLine.status == "enabled",
            AtpTestLine.asset_id.is_(None),
        )

    hit = db.execute(
        _base_stmt().where(
            AtpTestLine.voltage_level == voltage,
            AtpTestLine.tower_type == tower,
            AtpTestLine.shield_wire == shield,
        )
    ).scalars().all()
    if len(hit) == 1:
        return hit[0], "geometry"
    if len(hit) > 1:
        # 应用层已禁止同几何维重复；出现多条说明历史数据异常 → 取最近更新的一条并告警
        logger.warning("[测试线路] 几何维 %s/%s/%s 命中多条，取最近更新", voltage, tower, shield)
        return sorted(hit, key=lambda r: r.update_date, reverse=True)[0], "geometry"

    if include_degraded:
        degraded = db.execute(
            _base_stmt().where(
                AtpTestLine.voltage_level == voltage,
                AtpTestLine.tower_type == tower,
            )
        ).scalars().all()
        if len(degraded) == 1:
            return degraded[0], "degraded"
    return None, "none"


def resolve_for_asset(db: Session, *, asset_id: str) -> dict[str, Any]:
    """给前端「测试线路」来源切换用：按资产维度反查并给出提示。"""
    asset = db.get(AtpAssetVersion, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ATP 资产不存在")
    row, matched_by = resolve_test_line(db, asset=asset)
    if row is None:
        return {
            "test_line": None,
            "matched_by": "none",
            "hint": (
                "该维度组还没有测试线路。可点「派生测试线路」按维度自动生成草稿"
                f"（{asset.voltage_level or '?'}kV / {asset.tower_type or '?'} / "
                f"{asset.shield_wire or 'with'}）。"
            ),
        }
    codes = _asset_code_map(db, [row.asset_id])
    hint = None
    if matched_by == "degraded":
        hint = (
            f"未找到「{asset.shield_wire or 'with'}」避雷线配置的基准，"
            f"已降级匹配 {row.code}（避雷线：{row.shield_wire}）——"
            "几何可能与该模型不完全一致，建议派生一条对应基准。"
        )
    return {
        "test_line": serialize_summary(row, asset_code=codes.get(row.asset_id or "")),
        "matched_by": matched_by,
        "hint": hint,
    }


# ─────────────────────────── 派生（dry-run）───────────────────────────


class _DraftBuilder:
    """按 L1→L5 逐级填充，后写的覆盖先写的，并记录每个字段的最终来源。"""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sources: dict[str, str] = {}

    def put(self, field: str, value: Any, source: str) -> None:
        if value is None or value == "":
            return
        self.values[field] = value
        self.sources[field] = source

    def put_number(self, field: str, value: Any, source: str) -> None:
        self.put(field, _num(value), source)


def _circuits_from_geometry(geometry: dict[str, Any], source: str) -> list[dict[str, Any]]:
    circuits: list[dict[str, Any]] = []
    for idx, key in enumerate(CIRCUIT_KEYS, start=1):
        layer = geometry.get(key) if isinstance(geometry, dict) else None
        if not isinstance(layer, dict):
            continue
        spacing = layer.get("phase_spacing_m") or {}
        height = layer.get("phase_height_m") or {}
        if not any(_num(v) is not None for v in (*spacing.values(), *height.values())):
            continue
        circuits.append(
            {
                "circuit_no": idx,
                "spacing_upper_m": _num(spacing.get("upper")),
                "spacing_middle_m": _num(spacing.get("middle")),
                "spacing_lower_m": _num(spacing.get("lower")),
                "height_upper_m": _num(height.get("upper")),
                "height_middle_m": _num(height.get("middle")),
                "height_lower_m": _num(height.get("lower")),
                "_source": source,
            }
        )
    return circuits


def _apply_case_payload(
    builder: _DraftBuilder,
    *,
    base_tower: dict[str, Any],
    profile: dict[str, Any],
    source: str,
    out: dict[str, Any],
    force_geometry: bool = False,
) -> None:
    """把装配好的 base_tower/profile 摊平成测试线路字段。"""
    if not base_tower and not profile:
        return
    builder.put_number("span_small_m", base_tower.get("span_small_m"), source)
    builder.put_number("span_large_m", base_tower.get("span_large_m"), source)
    builder.put_number("ground_resistance_ohm", base_tower.get("ground_resistance_ohm"), source)
    builder.put_number("lightning_density", base_tower.get("lightning_density"), source)
    builder.put_number("altitude_m", base_tower.get("altitude_m"), source)
    builder.put("terrain", base_tower.get("terrain"), source)
    builder.put_number("slope_1", base_tower.get("slope_1"), source)
    builder.put_number("slope_2", base_tower.get("slope_2"), source)
    builder.put("tower_no", base_tower.get("tower_no"), source)
    builder.put("tower_model", base_tower.get("tower_model"), source)

    builder.put_number("call_height_m", profile.get("call_height_m"), source)
    builder.put_number("insulator_length_m", _insulator_to_m(profile.get("insulator_length_m")), source)
    builder.put_number("shield_wire_height_m", profile.get("shield_wire_height_m"), source)
    builder.put_number("protection_angle_left_deg", profile.get("protection_angle_left_deg"), source)
    builder.put_number("protection_angle_right_deg", profile.get("protection_angle_right_deg"), source)
    builder.put_number("angle_deg", profile.get("angle_deg"), source)
    builder.put("phase_sequence_1", profile.get("phase_sequence_1"), source)
    builder.put("phase_sequence_2", profile.get("phase_sequence_2"), source)
    builder.put("phase_sequence_3", profile.get("phase_sequence_3"), source)
    builder.put("phase_sequence_4", profile.get("phase_sequence_4"), source)
    builder.put("arrester_a", profile.get("arrester_a"), source)
    builder.put("arrester_b", profile.get("arrester_b"), source)
    builder.put("arrester_c", profile.get("arrester_c"), source)
    builder.put("structure_kind", profile.get("structure_kind"), source)
    builder.put("current_type", profile.get("current_type"), source)
    builder.put_number("current_head_time_us", profile.get("current_head_time_us"), source)
    builder.put_number("current_tail_time_us", profile.get("current_tail_time_us"), source)

    geometry = base_tower.get("circuit_geometry_json") or {}
    if isinstance(geometry, dict):
        lightning_wire = geometry.get("lightning_wire") or {}
        if isinstance(lightning_wire, dict):
            builder.put_number(
                "shield_wire_left_mid_m", lightning_wire.get("left_mid_distance_m"), source
            )
            builder.put_number(
                "shield_wire_right_mid_m", lightning_wire.get("right_mid_distance_m"), source
            )
        circuits = _circuits_from_geometry(geometry, source)
        if circuits and (force_geometry or not out.get("circuits")):
            out["circuits"] = circuits


def _latest_success_run(db: Session, asset_id: str) -> AtpAssetRun | None:
    return db.execute(
        select(AtpAssetRun)
        .where(AtpAssetRun.asset_id == asset_id, AtpAssetRun.status == "success")
        .order_by(AtpAssetRun.create_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def _tower_model_defaults(db: Session, tower_type: str) -> TowerModel | None:
    if not tower_type:
        return None
    return db.execute(
        select(TowerModel)
        .where(
            TowerModel.is_enabled.is_(True),
            or_(TowerModel.tower_type == tower_type, TowerModel.code == tower_type),
        )
        .order_by(TowerModel.sort_order.asc())
        .limit(1)
    ).scalar_one_or_none()


def _dimension_extra_map(db: Session, dimension_type: str, codes: Iterable[str | None]) -> dict[str, dict[str, Any]]:
    wanted = [c for c in {c for c in codes if c}]
    if not wanted:
        return {}
    rows = db.execute(
        select(DimensionItem.code, DimensionItem.extra_json).where(
            DimensionItem.dimension_type == dimension_type,
            DimensionItem.code.in_(wanted),
        )
    ).all()
    return {row[0]: dict(row[1] or {}) for row in rows}


def derive_test_line(db: Session, payload: AtpTestLineDeriveRequest) -> dict[str, Any]:
    """按维度/资产/真实杆塔派生草稿（干跑，不落库）。"""
    asset: AtpAssetVersion | None = None
    if payload.asset_id:
        asset = db.get(AtpAssetVersion, payload.asset_id)
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"ATP 资产不存在：{payload.asset_id}"
            )

    voltage_level = (payload.voltage_level or getattr(asset, "voltage_level", None) or "").strip()
    tower_type = normalize_tower_type(
        payload.tower_type or getattr(asset, "tower_type", None) or ""
    )
    shield_wire = (
        payload.shield_wire or getattr(asset, "shield_wire", None) or "with"
    ).strip()
    scene_type = payload.scene_type or getattr(asset, "scene_type", None)
    arrester_config = payload.arrester_config or getattr(asset, "arrester_config", None)
    structure_kind = payload.structure_kind

    builder = _DraftBuilder()
    out: dict[str, Any] = {"circuits": []}
    warnings: list[dict[str, str]] = []
    blockers: list[dict[str, str]] = []

    builder.put("voltage_level", voltage_level, SRC_MANUAL if payload.voltage_level else "asset")
    builder.put("tower_type", tower_type, SRC_MANUAL if payload.tower_type else "asset")
    builder.put("shield_wire", shield_wire, SRC_MANUAL if payload.shield_wire else "asset")
    builder.put("scene_type", scene_type, "asset" if getattr(asset, "scene_type", None) else SRC_MANUAL)
    builder.put(
        "arrester_config",
        arrester_config,
        "asset" if getattr(asset, "arrester_config", None) else SRC_MANUAL,
    )
    builder.put("structure_kind", structure_kind, SRC_MANUAL)

    # ── L5：内置兜底（先铺底，后续各级覆盖）──
    reference = _BUILTIN_VOLTAGE_REFERENCE.get(str(voltage_level))
    if reference:
        builder.put_number("insulator_length_m", reference["insulator_length_m"], SRC_BUILTIN)
        builder.put_number("shield_wire_height_m", reference["shield_h"], SRC_BUILTIN)
        if not out["circuits"]:
            spacing = reference["spacing"]
            height = reference["height"]
            out["circuits"] = [
                {
                    "circuit_no": 1,
                    "spacing_upper_m": spacing[0],
                    "spacing_middle_m": spacing[1],
                    "spacing_lower_m": spacing[2],
                    "height_upper_m": height[0],
                    "height_middle_m": height[1],
                    "height_lower_m": height[2],
                    "_source": SRC_BUILTIN,
                }
            ]

    # ── L4：维度项 extra_json（工程默认值）──
    voltage_extra = _dimension_extra_map(db, "voltage_level", [voltage_level]).get(voltage_level, {})
    tower_extra = _dimension_extra_map(db, "tower_type", [tower_type]).get(tower_type, {})
    scene_extra = _dimension_extra_map(db, "scenario", [scene_type]).get(scene_type or "", {})
    arrester_extra = _dimension_extra_map(db, "arrester_combination", [arrester_config]).get(
        arrester_config or "", {}
    )

    if voltage_extra:
        builder.put_number(
            "insulator_length_m", _insulator_to_m(voltage_extra.get("insulator_length_mm")), SRC_DIMENSION
        )
        builder.put_number("insulator_length_m", _insulator_to_m(voltage_extra.get("insulator_length_m")), SRC_DIMENSION)
        spacing_default = voltage_extra.get("phase_spacing_default") or {}
        height_default = voltage_extra.get("phase_height_default") or {}
        if (spacing_default or height_default) and out["circuits"]:
            first = out["circuits"][0]
            for key, source_key in (("upper", "spacing_upper_m"), ("middle", "spacing_middle_m"), ("lower", "spacing_lower_m")):
                value = _num(spacing_default.get(key))
                if value is not None:
                    first[source_key] = value
                    first["_source"] = SRC_DIMENSION
            for key, source_key in (("upper", "height_upper_m"), ("middle", "height_middle_m"), ("lower", "height_lower_m")):
                value = _num(height_default.get(key))
                if value is not None:
                    first[source_key] = value
                    first["_source"] = SRC_DIMENSION

    if tower_extra:
        builder.put_number("call_height_m", tower_extra.get("call_height_m"), SRC_DIMENSION)
        builder.put_number("circuit_count", tower_extra.get("circuit_count"), SRC_DIMENSION)
        builder.put("tower_model", tower_extra.get("tower_model"), SRC_DIMENSION)

    if scene_extra:
        builder.put_number("slope_1", scene_extra.get("slope_default"), SRC_DIMENSION)
        builder.put("structure_kind", scene_extra.get("structure_kind"), SRC_DIMENSION)

    if arrester_extra:
        arrester = arrester_extra.get("arrester") or {}
        for phase in ("a", "b", "c"):
            flag = arrester.get(phase)
            if flag is None:
                continue
            builder.put(f"arrester_{phase}", "1" if flag else "", SRC_DIMENSION)

    # ── L3：塔型号字典 ──
    tower_model_row = _tower_model_defaults(db, tower_type)
    if tower_model_row is not None:
        builder.put("tower_model", builder.values.get("tower_model") or tower_model_row.code, SRC_TOWER_MODEL)
        builder.put_number("span_small_m", tower_model_row.default_span_small_m, SRC_TOWER_MODEL)
        builder.put_number("span_large_m", tower_model_row.default_span_large_m, SRC_TOWER_MODEL)
        builder.put_number("ground_resistance_ohm", tower_model_row.default_ground_resistance_ohm, SRC_TOWER_MODEL)
        builder.put_number("lightning_density", tower_model_row.default_lightning_density, SRC_TOWER_MODEL)
        builder.put_number("altitude_m", tower_model_row.default_altitude_m, SRC_TOWER_MODEL)
        builder.put("terrain", tower_model_row.default_terrain, SRC_TOWER_MODEL)
        builder.put_number("slope_1", tower_model_row.default_slope_1, SRC_TOWER_MODEL)
        builder.put_number("slope_2", tower_model_row.default_slope_2, SRC_TOWER_MODEL)

    # ── L2：参数模板上下文默认值（按维度匹配）──
    from .atp_param_resolver import collect_context_defaults  # noqa: PLC0415

    circuit_count_hint = int(_num(builder.values.get("circuit_count")) or len(out["circuits"]) or 1)
    template_defaults = collect_context_defaults(
        voltage_level=voltage_level or None,
        tower_type=tower_type or None,
        circuit_count=circuit_count_hint,
        scene_type=scene_type,
        arrester_config=arrester_config,
        structure_kind=structure_kind,
    )
    if template_defaults:
        builder.put_number("call_height_m", template_defaults.get("tower_h"), SRC_TEMPLATE)
        builder.put_number("insulator_length_m", _insulator_to_m(template_defaults.get("insul_m")), SRC_TEMPLATE)
        builder.put_number("shield_wire_height_m", template_defaults.get("shield_h"), SRC_TEMPLATE)
        builder.put_number("shield_wire_left_mid_m", template_defaults.get("lw_l_eff", template_defaults.get("lw_l")), SRC_TEMPLATE)
        builder.put_number("shield_wire_right_mid_m", template_defaults.get("lw_r_eff", template_defaults.get("lw_r")), SRC_TEMPLATE)
        builder.put_number("ground_resistance_ohm", template_defaults.get("ground_r"), SRC_TEMPLATE)

        def _fill_first(sp_prefix: str, h_prefix: str, circuit_no: int) -> None:
            target = next((c for c in out["circuits"] if c["circuit_no"] == circuit_no), None)
            if target is None:
                return
            mapping = {
                "spacing_upper_m": template_defaults.get(f"{sp_prefix}u"),
                "spacing_middle_m": template_defaults.get(f"{sp_prefix}m"),
                "spacing_lower_m": template_defaults.get(f"{sp_prefix}l"),
                "height_upper_m": template_defaults.get(f"{h_prefix}u"),
                "height_middle_m": template_defaults.get(f"{h_prefix}m"),
                "height_lower_m": template_defaults.get(f"{h_prefix}l"),
            }
            changed = False
            for key, value in mapping.items():
                parsed = _num(value)
                if parsed is not None:
                    target[key] = parsed
                    changed = True
            if changed:
                target["_source"] = SRC_TEMPLATE

        _fill_first("sp_", "h_", 1)
        for idx in (2, 3, 4):
            _fill_first(f"c{idx}_sp_", f"c{idx}_", idx)

    # ── L1：真实杆塔 / 历史成功 run（最高可信度）──
    if payload.source_tower_id:
        from .line_service import get_line_tower_by_id  # noqa: PLC0415

        tower = get_line_tower_by_id(db, payload.source_tower_id)
        if tower is None:
            blockers.append({"field": "source_tower_id", "reason": "指定的线路杆塔不存在"})
        else:
            base_tower, profile = snapshot_asm.assemble_from_line_tower(tower, tower.line)
            _apply_case_payload(
                builder,
                base_tower=base_tower,
                profile=profile,
                source=SRC_TOWER,
                out=out,
                force_geometry=True,
            )

    if asset is not None:
        run = _latest_success_run(db, asset.id)
        if run is not None:
            compare = (run.result_summary_json or {}).get("compare") or {}
            case = compare.get("case") or {}
            base_tower = case.get("base_tower") or {}
            profile = case.get("profile") or {}
            if base_tower or profile:
                _apply_case_payload(
                    builder,
                    base_tower=base_tower,
                    profile=profile,
                    source=f"{SRC_RUN}:{run.id[:8]}",
                    out=out,
                    force_geometry=True,
                )

    # ── 汇总为草稿 ──
    circuits_payload = [
        {k: v for k, v in circuit.items() if not k.startswith("_")}
        for circuit in out["circuits"]
    ]
    circuit_sources = {
        f"circuits[{c['circuit_no']}]": c.get("_source", SRC_MANUAL) for c in out["circuits"]
    }

    draft: dict[str, Any] = dict(builder.values)
    draft.setdefault("current_ka", 31.0)
    if "circuit_count" not in draft:
        draft["circuit_count"] = len(circuits_payload) or 1
    if "shield_wire" not in draft or not draft.get("shield_wire"):
        draft["shield_wire"] = shield_wire
    draft["asset_id"] = asset.id if asset is not None else None
    draft["circuits"] = circuits_payload

    # ── 校验 ──
    circuit_models = [AtpTestLineCircuitPayload(**c) for c in circuits_payload]
    shape_blockers, shape_warnings = validate_draft(draft, circuit_models)
    blockers.extend(shape_blockers)
    warnings.extend(shape_warnings)

    # 兜底值提示（必须让用户知道哪些数字不是工程实测值）
    builtin_fields = [f for f, s in builder.sources.items() if s == SRC_BUILTIN]
    if builtin_fields:
        warnings.append(
            {
                "field": ",".join(sorted(builtin_fields)),
                "reason": "这些字段用了内置兜底参考值（按电压分档的量级估计），落库前请人工核对",
            }
        )
    template_fields = [f for f, s in builder.sources.items() if s == SRC_TEMPLATE]
    if template_fields:
        warnings.append(
            {
                "field": ",".join(sorted(template_fields)),
                "reason": "来自参数模板默认值（无杆塔模式的合成口径），与真实台账可能有差异",
            }
        )
    if not out["circuits"]:
        blockers.append(
            {"field": "circuits", "reason": "没拿到任何回路几何（相中距/相高），无法生成 .dat"}
        )

    sources = dict(builder.sources)
    sources.update(circuit_sources)
    return {
        "draft": draft,
        "sources": sources,
        "blockers": blockers,
        "warnings": warnings,
        "suggested_code": _suggest_code(
            voltage_level=voltage_level,
            tower_type=tower_type,
            shield_wire=draft.get("shield_wire") or shield_wire,
            asset_code=getattr(asset, "code", None),
        ),
        "not_consumed": list(snapshot_asm.NOT_CONSUMED_FIELDS),
    }


# ─────────────────────────── 装配预览 ───────────────────────────


def preview_test_line(db: Session, test_line_id: str) -> dict[str, Any]:
    """返回真实执行时会用的 base_tower/profile + 校验结果（不落库）。"""
    row = get_test_line_by_id(db, test_line_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试线路不存在")
    db.flush()
    base_tower, profile = snapshot_asm.assemble_from_test_line(row)
    circuits = [
        AtpTestLineCircuitPayload(
            circuit_no=c.circuit_no,
            phase_sequence=c.phase_sequence,
            spacing_upper_m=c.spacing_upper_m,
            spacing_middle_m=c.spacing_middle_m,
            spacing_lower_m=c.spacing_lower_m,
            height_upper_m=c.height_upper_m,
            height_middle_m=c.height_middle_m,
            height_lower_m=c.height_lower_m,
        )
        for c in sorted(row.circuits or [], key=lambda c: c.circuit_no)
    ]
    draft = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    blockers, warnings = validate_draft(draft, circuits)
    return {
        "base_tower": base_tower,
        "profile": profile,
        "snapshot_hash": snapshot_asm.snapshot_hash(base_tower, profile),
        "not_consumed": list(snapshot_asm.NOT_CONSUMED_FIELDS),
        "blockers": blockers,
        "warnings": warnings,
    }


# ─────────────────────────── 执行期辅助 ───────────────────────────


def mark_used(db: Session, row: AtpTestLine) -> None:
    """记录一次引用（统计 + 最近使用时间）。失败不影响测试。"""
    try:
        row.used_count = int(row.used_count or 0) + 1
        row.last_used_at = utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - 统计失败不应影响测试
        logger.warning("[测试线路] 引用统计失败 id=%s err=%s", row.id, exc)
        db.rollback()


def build_run_meta(row: AtpTestLine, *, matched_by: str) -> dict[str, Any]:
    """写进 compare.json 的 case.test_line 段。"""
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "matched_by": matched_by,
        "snapshot_hash": row.snapshot_hash,
        "voltage_level": row.voltage_level,
        "tower_type": row.tower_type,
        "shield_wire": row.shield_wire,
        "scene_type": row.scene_type,
        "arrester_config": row.arrester_config,
        "source_kind": row.source_kind,
        "derive_rules": row.derive_rules_json or {},
        # 地形/海拔/倾角当前没有消费方 —— 显式标注，避免「以为生效了」
        "not_consumed": list(snapshot_asm.NOT_CONSUMED_FIELDS),
    }


def assemble_payload_from_test_line(row: AtpTestLine) -> tuple[dict[str, Any], dict[str, Any]]:
    """执行期装配：优先用冻结快照（保证可复现），快照缺失时现场装配。

    ⚠️ 用快照而不是现场装配是刻意的：测试线路表被编辑后，历史用例仍应按
    「生成时那套参数」跑，否则回归结论不可比。
    """
    snapshot = row.snapshot_json or {}
    base_tower = snapshot.get("base_tower")
    profile = snapshot.get("profile")
    if isinstance(base_tower, dict) and isinstance(profile, dict) and base_tower and profile:
        return dict(base_tower), dict(profile)
    return snapshot_asm.assemble_from_test_line(row)


__all__ = [
    "SRC_BUILTIN",
    "SRC_DIMENSION",
    "SRC_MANUAL",
    "SRC_RUN",
    "SRC_TEMPLATE",
    "SRC_TOWER",
    "SRC_TOWER_MODEL",
    "assemble_payload_from_test_line",
    "build_run_meta",
    "clone_test_line",
    "create_test_line",
    "delete_test_line",
    "derive_test_line",
    "get_test_line_detail",
    "get_test_line_by_id",
    "list_test_lines",
    "list_usage",
    "mark_used",
    "normalize_tower_type",
    "preview_test_line",
    "rebuild_snapshot",
    "resolve_for_asset",
    "resolve_test_line",
    "serialize_detail",
    "serialize_summary",
    "update_test_line",
    "validate_draft",
]
