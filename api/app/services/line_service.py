from __future__ import annotations

import asyncio
import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.tower_model import TowerModel
from ..models.tower_profile import TowerProfile
from ..schemas.line import (
    LineCreateRequest,
    LineListResponse,
    LineSummary,
    LineTowerCreateRequest,
    LineTowerImportResponse,
    LineTowerListResponse,
    LineTowerSummary,
    LineTowerUpdateRequest,
    LineUpdateRequest,
)
from .line_preparation_service import summarize_line_preparation, summarize_line_preparations
from .push_service import publish_topic

LINE_TOPIC = "admin.power-lines"
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
LINE_CODE_PREFIX = "PL"


@dataclass
class CsvImportStats:
    imported_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    warnings: list[str] | None = None

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


def serialize_line(
    line: Line,
    *,
    tower_count: int = 0,
    preparation_json: dict[str, Any] | None = None,
) -> LineSummary:
    return LineSummary(
        id=line.id,
        code=line.code,
        name=line.name,
        voltage_kv=line.voltage_kv,
        phase_sequence_json=line.phase_sequence_json or {},
        arrester_install_json=line.arrester_install_json or {},
        lightning_param_json=line.lightning_param_json or {},
        preparation_json=preparation_json or {},
        tower_count=tower_count,
        create_date=line.create_date,
        create_user=line.create_user,
        update_date=line.update_date,
        update_user=line.update_user,
    )


def serialize_line_tower(item: LineTower) -> LineTowerSummary:
    return LineTowerSummary(
        id=item.id,
        line_id=item.line_id,
        seq_no=item.seq_no,
        tower_no=item.tower_no,
        tower_model=item.tower_model,
        tower_type=item.tower_type,
        longitude=item.longitude,
        latitude=item.latitude,
        altitude_m=item.altitude_m,
        terrain=item.terrain,
        ground_resistance_ohm=item.ground_resistance_ohm,
        lightning_density=item.lightning_density,
        span_small_m=item.span_small_m,
        span_large_m=item.span_large_m,
        slope_1=item.slope_1,
        slope_2=item.slope_2,
        risk_level=item.risk_level,
        circuit_geometry_json=item.circuit_geometry_json or {},
        lightning_result_json=item.lightning_result_json or {},
        raw_extra_json=item.raw_extra_json or {},
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_lines(
    db: Session,
    *,
    keyword: str | None,
) -> LineListResponse:
    stmt = select(Line)
    total_stmt = select(func.count()).select_from(Line)

    normalized = (keyword or "").strip()
    if normalized:
        like = f"%{normalized}%"
        predicate = or_(Line.code.ilike(like), Line.name.ilike(like))
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(stmt.order_by(Line.update_date.desc(), Line.code.asc())).scalars().all()
    line_ids = [item.id for item in items]
    tower_count_map = _load_tower_counts(db, line_ids)
    preparation_map = summarize_line_preparations(db, items, tower_count_map=tower_count_map)

    return LineListResponse(
        items=[
            serialize_line(
                item,
                tower_count=tower_count_map.get(item.id, 0),
                preparation_json=preparation_map.get(item.id, {}),
            )
            for item in items
        ],
        total=total,
    )


def get_line_by_id(db: Session, line_id: str) -> Line | None:
    return db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()


def get_line_by_code(db: Session, code: str) -> Line | None:
    normalized = code.strip()
    if not normalized:
        return None
    return db.execute(select(Line).where(func.lower(Line.code) == normalized.lower())).scalar_one_or_none()


def create_line(
    db: Session,
    payload: LineCreateRequest,
    *,
    actor_user_id: str,
) -> LineSummary:
    for _ in range(20):
        now = utcnow()
        line = Line(
            code=_generate_line_code(db),
            name=payload.name.strip(),
            voltage_kv=payload.voltage_kv,
            phase_sequence_json=payload.phase_sequence_json,
            arrester_install_json=payload.arrester_install_json,
            lightning_param_json=payload.lightning_param_json,
            create_user=actor_user_id,
            update_user=actor_user_id,
            create_date=now,
            update_date=now,
        )
        db.add(line)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if get_line_by_code(db, line.code):
                continue
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create line") from exc

        saved = get_line_by_id(db, line.id)
        if not saved:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to load created line")

        _publish_line_change("power-lines.created", {"action": "created", "line_id": saved.id})
        return serialize_line(saved, tower_count=0, preparation_json=summarize_line_preparation(db, saved, tower_count=0))

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate unique line code")


def update_line(
    db: Session,
    line_id: str,
    payload: LineUpdateRequest,
    *,
    actor_user_id: str,
) -> LineSummary | None:
    line = get_line_by_id(db, line_id)
    if not line:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        line.name = str(update_data["name"]).strip()
    if "voltage_kv" in update_data:
        line.voltage_kv = update_data["voltage_kv"]
    if "phase_sequence_json" in update_data and update_data["phase_sequence_json"] is not None:
        line.phase_sequence_json = dict(update_data["phase_sequence_json"])
    if "arrester_install_json" in update_data and update_data["arrester_install_json"] is not None:
        line.arrester_install_json = dict(update_data["arrester_install_json"])
    if "lightning_param_json" in update_data and update_data["lightning_param_json"] is not None:
        line.lightning_param_json = dict(update_data["lightning_param_json"])

    line.update_user = actor_user_id
    line.update_date = utcnow()
    db.commit()

    saved = get_line_by_id(db, line_id)
    if not saved:
        return None

    tower_count = int(db.scalar(select(func.count()).select_from(LineTower).where(LineTower.line_id == line_id)) or 0)
    _publish_line_change("power-lines.updated", {"action": "updated", "line_id": line_id})
    return serialize_line(
        saved,
        tower_count=tower_count,
        preparation_json=summarize_line_preparation(db, saved, tower_count=tower_count),
    )


def delete_line(db: Session, line_id: str) -> bool:
    line = get_line_by_id(db, line_id)
    if not line:
        return False

    db.delete(line)
    db.commit()
    _publish_line_change("power-lines.deleted", {"action": "deleted", "line_id": line_id})
    return True


def list_line_towers(
    db: Session,
    *,
    line_id: str,
    keyword: str | None,
    tower_type: str | None,
    risk_level: str | None,
    limit: int,
    offset: int,
) -> LineTowerListResponse:
    filters: list[Any] = [LineTower.line_id == line_id]
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        filters.append(or_(LineTower.tower_no.ilike(like), LineTower.tower_model.ilike(like)))
    if tower_type:
        filters.append(LineTower.tower_type == tower_type)
    if risk_level:
        filters.append(LineTower.risk_level == risk_level)

    total = int(db.scalar(select(func.count()).select_from(LineTower).where(*filters)) or 0)
    items = db.execute(
        select(LineTower)
        .where(*filters)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    return LineTowerListResponse(
        items=[serialize_line_tower(item) for item in items],
        total=total,
    )


def get_line_tower_by_id(db: Session, tower_id: str) -> LineTower | None:
    return db.execute(select(LineTower).where(LineTower.id == tower_id)).scalar_one_or_none()


def create_line_tower(
    db: Session,
    line_id: str,
    payload: LineTowerCreateRequest,
    *,
    actor_user_id: str,
) -> LineTowerSummary | None:
    if not get_line_by_id(db, line_id):
        return None

    existed = db.execute(
        select(LineTower).where(
            LineTower.line_id == line_id,
            or_(LineTower.seq_no == payload.seq_no, LineTower.tower_no == payload.tower_no.strip()),
        )
    ).scalar_one_or_none()
    if existed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tower sequence or tower number already exists")

    model_defaults = _load_tower_model_defaults(db, payload.tower_model)
    now = utcnow()
    item = LineTower(
        line_id=line_id,
        seq_no=payload.seq_no,
        tower_no=payload.tower_no.strip(),
        tower_model=model_defaults.get("tower_model") if model_defaults else _normalize_str(payload.tower_model),
        tower_type=_pick_optional_value(payload.tower_type, model_defaults.get("tower_type") if model_defaults else None),
        longitude=payload.longitude,
        latitude=payload.latitude,
        altitude_m=_pick_optional_value(payload.altitude_m, model_defaults.get("altitude_m") if model_defaults else None),
        terrain=_pick_optional_value(_normalize_str(payload.terrain), model_defaults.get("terrain") if model_defaults else None),
        ground_resistance_ohm=_pick_optional_value(payload.ground_resistance_ohm, model_defaults.get("ground_resistance_ohm") if model_defaults else None),
        lightning_density=_pick_optional_value(payload.lightning_density, model_defaults.get("lightning_density") if model_defaults else None),
        span_small_m=_pick_optional_value(payload.span_small_m, model_defaults.get("span_small_m") if model_defaults else None),
        span_large_m=_pick_optional_value(payload.span_large_m, model_defaults.get("span_large_m") if model_defaults else None),
        slope_1=_pick_optional_value(payload.slope_1, model_defaults.get("slope_1") if model_defaults else None),
        slope_2=_pick_optional_value(payload.slope_2, model_defaults.get("slope_2") if model_defaults else None),
        risk_level=_pick_optional_value(_normalize_str(payload.risk_level), model_defaults.get("risk_level") if model_defaults else None),
        circuit_geometry_json=_pick_dict_value(payload.circuit_geometry_json, _extract_model_default_dict(model_defaults, "circuit_geometry_json")),
        lightning_result_json=_pick_dict_value(payload.lightning_result_json, _extract_model_default_dict(model_defaults, "lightning_result_json")),
        raw_extra_json=payload.raw_extra_json or {},
        create_user=actor_user_id,
        update_user=actor_user_id,
        create_date=now,
        update_date=now,
    )
    db.add(item)
    db.commit()

    saved = get_line_tower_by_id(db, item.id)
    if not saved:
        return None
    _publish_line_change("power-lines.towers.created", {"action": "tower_created", "line_id": line_id, "tower_id": saved.id})
    return serialize_line_tower(saved)


def update_line_tower(
    db: Session,
    tower_id: str,
    payload: LineTowerUpdateRequest,
    *,
    actor_user_id: str,
) -> LineTowerSummary | None:
    tower = get_line_tower_by_id(db, tower_id)
    if not tower:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    next_seq_no = tower.seq_no
    if "seq_no" in update_data and update_data["seq_no"] is not None:
        next_seq_no = int(update_data["seq_no"])

    next_tower_no = tower.tower_no
    if "tower_no" in update_data:
        normalized_tower_no = _normalize_str(update_data["tower_no"])
        if normalized_tower_no is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tower_no cannot be empty")
        next_tower_no = normalized_tower_no

    conflict = db.execute(
        select(LineTower).where(
            LineTower.line_id == tower.line_id,
            LineTower.id != tower.id,
            or_(LineTower.seq_no == next_seq_no, LineTower.tower_no == next_tower_no),
        )
    ).scalar_one_or_none()
    if conflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tower sequence or tower number already exists")

    for field in (
        "seq_no",
        "longitude",
        "latitude",
        "altitude_m",
        "ground_resistance_ohm",
        "lightning_density",
        "span_small_m",
        "span_large_m",
        "slope_1",
        "slope_2",
    ):
        if field in update_data and update_data[field] is not None:
            setattr(tower, field, update_data[field])

    if "tower_no" in update_data:
        tower.tower_no = next_tower_no

    for field in ("tower_model", "tower_type", "terrain", "risk_level"):
        if field in update_data:
            setattr(tower, field, _normalize_str(update_data[field]))

    if "circuit_geometry_json" in update_data and update_data["circuit_geometry_json"] is not None:
        tower.circuit_geometry_json = dict(update_data["circuit_geometry_json"])
    if "lightning_result_json" in update_data and update_data["lightning_result_json"] is not None:
        tower.lightning_result_json = dict(update_data["lightning_result_json"])
    if "raw_extra_json" in update_data and update_data["raw_extra_json"] is not None:
        tower.raw_extra_json = dict(update_data["raw_extra_json"])

    tower.update_user = actor_user_id
    tower.update_date = utcnow()
    db.commit()

    saved = get_line_tower_by_id(db, tower_id)
    if not saved:
        return None
    _publish_line_change(
        "power-lines.towers.updated",
        {"action": "tower_updated", "line_id": saved.line_id, "tower_id": saved.id},
    )
    return serialize_line_tower(saved)


def delete_line_tower(db: Session, tower_id: str) -> bool:
    item = get_line_tower_by_id(db, tower_id)
    if not item:
        return False

    line_id = item.line_id
    db.delete(item)
    db.commit()
    _publish_line_change("power-lines.towers.deleted", {"action": "tower_deleted", "line_id": line_id, "tower_id": tower_id})
    return True


def import_line_towers_from_csv(
    db: Session,
    *,
    line: Line,
    file: UploadFile,
    actor_user_id: str,
) -> LineTowerImportResponse:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is empty")

    text = _decode_csv_bytes(content)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file has no rows")

    raw_header = rows[0]
    if not raw_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV header is empty")

    max_row_len = max((len(row) for row in rows[1:]), default=len(raw_header))
    header = list(raw_header)
    extra_headers: list[str] = []
    if max_row_len > len(header):
        extra_count = max_row_len - len(header)
        extra_headers = [f"__extra_col_{idx}" for idx in range(1, extra_count + 1)]
        header.extend(extra_headers)

    stats = CsvImportStats()
    existing_towers = db.execute(select(LineTower).where(LineTower.line_id == line.id)).scalars().all()
    tower_by_seq = {item.seq_no: item for item in existing_towers}
    tower_by_no = {item.tower_no: item for item in existing_towers}

    first_data_row: dict[str, str] | None = None

    for row_index, source_row in enumerate(rows[1:], start=2):
        row_values = source_row + [""] * (len(header) - len(source_row))
        row = {name: row_values[idx] for idx, name in enumerate(header)}
        if all(not str(value).strip() for value in row.values()):
            continue

        if first_data_row is None:
            first_data_row = row

        seq_no = _parse_int(row.get("序号"))
        tower_no = _normalize_str(row.get("塔号"))
        if seq_no is None or not tower_no:
            stats.skipped_count += 1
            if stats.warnings is not None:
                stats.warnings.append(f"第 {row_index} 行缺少有效的序号/塔号，已跳过")
            continue

        tower_from_seq = tower_by_seq.get(seq_no)
        tower_from_no = tower_by_no.get(tower_no)
        if tower_from_seq and tower_from_no and tower_from_seq.id != tower_from_no.id:
            stats.skipped_count += 1
            if stats.warnings is not None:
                stats.warnings.append(f"第 {row_index} 行序号/塔号映射冲突，已跳过")
            continue

        tower = tower_from_seq or tower_from_no

        is_created = tower is None
        if tower is None:
            tower = LineTower(
                line_id=line.id,
                seq_no=seq_no,
                tower_no=tower_no,
                create_user=actor_user_id,
                create_date=utcnow(),
            )
            db.add(tower)

        tower.seq_no = seq_no
        tower.tower_no = tower_no
        source_model_name = _normalize_str(row.get("杆塔模型"))
        model_defaults = _load_tower_model_defaults_from_row(db, source_row=row, source_model_name=source_model_name)
        tower.tower_model = model_defaults.get("tower_model") if model_defaults else source_model_name
        tower.tower_type = _pick_optional_value(
            _normalize_str(row.get("直线或耐张杆塔")),
            model_defaults.get("tower_type") if model_defaults else None,
        )
        tower.longitude = _parse_float(row.get("经度"))
        tower.latitude = _parse_float(row.get("纬度"))
        tower.altitude_m = _pick_optional_value(_parse_float(row.get("海拔m")), model_defaults.get("altitude_m") if model_defaults else None)
        tower.terrain = _pick_optional_value(_normalize_str(row.get("地形")), model_defaults.get("terrain") if model_defaults else None)
        tower.ground_resistance_ohm = _pick_optional_value(_parse_float(row.get("接地电阻")), model_defaults.get("ground_resistance_ohm") if model_defaults else None)
        tower.lightning_density = _pick_optional_value(_parse_float(row.get("地闪密度")), model_defaults.get("lightning_density") if model_defaults else None)
        tower.span_small_m = _pick_optional_value(_parse_float(row.get("小号侧档距")), model_defaults.get("span_small_m") if model_defaults else None)
        tower.span_large_m = _pick_optional_value(_parse_float(row.get("大号侧档距")), model_defaults.get("span_large_m") if model_defaults else None)
        tower.slope_1 = _pick_optional_value(_parse_float(row.get("地面倾角1")), model_defaults.get("slope_1") if model_defaults else None)
        tower.slope_2 = _pick_optional_value(_parse_float(row.get("地面倾角2")), model_defaults.get("slope_2") if model_defaults else None)
        tower.risk_level = _pick_optional_value(_normalize_str(row.get("雷击风险等级")), model_defaults.get("risk_level") if model_defaults else None)
        tower.circuit_geometry_json = _pick_dict_value(_build_circuit_geometry(row), _extract_model_default_dict(model_defaults, "circuit_geometry_json"))
        tower.lightning_result_json = _pick_dict_value(_build_lightning_result(row), _extract_model_default_dict(model_defaults, "lightning_result_json"))
        tower.raw_extra_json = _extract_extra_values(row, extra_headers)
        tower.update_user = actor_user_id
        tower.update_date = utcnow()
        db.flush()
        _upsert_tower_profile_from_legacy_row(
            db,
            tower=tower,
            row=row,
            actor_user_id=actor_user_id,
        )

        tower_by_seq[tower.seq_no] = tower
        tower_by_no[tower.tower_no] = tower

        if is_created:
            stats.imported_count += 1
        else:
            stats.updated_count += 1

    _apply_line_metadata_from_csv(
        line,
        first_data_row,
        actor_user_id=actor_user_id,
        warnings=stats.warnings if stats.warnings is not None else [],
    )

    db.commit()
    tower_count = int(db.scalar(select(func.count()).select_from(LineTower).where(LineTower.line_id == line.id)) or 0)
    _publish_line_change(
        "power-lines.towers.imported",
        {
            "action": "tower_imported",
            "line_id": line.id,
            "imported_count": stats.imported_count,
            "updated_count": stats.updated_count,
            "skipped_count": stats.skipped_count,
        },
    )

    return LineTowerImportResponse(
        line=serialize_line(
            line,
            tower_count=tower_count,
            preparation_json=summarize_line_preparation(db, line, tower_count=tower_count),
        ),
        imported_count=stats.imported_count,
        updated_count=stats.updated_count,
        skipped_count=stats.skipped_count,
        warning_count=len(stats.warnings or []),
        warnings=stats.warnings or [],
    )


def export_line_towers_to_csv(db: Session, *, line: Line) -> tuple[str, bytes]:
    towers = db.execute(
        select(LineTower)
        .where(LineTower.line_id == line.id)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
    ).scalars().all()

    tower_ids = [tower.id for tower in towers]
    profile_map = {
        profile.tower_id: profile
        for profile in (
            db.execute(select(TowerProfile).where(TowerProfile.tower_id.in_(tower_ids))).scalars().all()
            if tower_ids
            else []
        )
    }

    headers = [
        "线路编号",
        "序号",
        "线路名称",
        "电压等级",
        "塔号",
        "杆塔模型",
        "塔形",
        "经度",
        "纬度",
        "I回相序",
        "II回相序",
        "III回相序",
        "IV回相序",
        "A相是否安装避雷器",
        "B相是否安装避雷器",
        "C相是否安装避雷器",
        "接地电阻",
        "左避雷中距m",
        "右避雷中距m",
        "避雷线高度m",
        "绝缘子串长度mm",
        "杆塔呼高m",
        "I回上相中距m",
        "I回中相中距m",
        "I回下相中距m",
        "I回上相高度m",
        "I回中相高度m",
        "I回下相高度m",
        "II回上相中距m",
        "II回中相中距m",
        "II回下相中距m",
        "II回上相高度m",
        "II回中相高度m",
        "II回下相高度m",
        "III回上相中距m",
        "III回中相中距m",
        "III回下相中距m",
        "III回上相高度m",
        "III回中相高度m",
        "III回下相高度m",
        "IV回上相中距m",
        "IV回中相中距m",
        "IV回下相中距m",
        "IV回上相高度m",
        "IV回中相高度m",
        "IV回下相高度m",
        "小号侧档距",
        "大号侧档距",
        "电角度",
        "雷电流幅值a",
        "雷电流幅值b",
        "地面倾角1",
        "地面倾角2",
        "海拔m",
        "地形",
        "地闪密度",
        "直线或耐张杆塔",
        "绕击反击",
        "反击耐雷水平kA",
        "反击跳闸率(次/100km.a)",
        "绕击耐雷水平kA",
        "绕击跳闸率(次/100km.a)",
        "雷击风险等级",
        "几何参数JSON",
        "雷电参数JSON",
        "额外字段JSON",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    for tower in towers:
        profile = profile_map.get(tower.id)
        writer.writerow(
            [
                line.code,
                tower.seq_no,
                line.name,
                line.voltage_kv or "",
                tower.tower_no,
                tower.tower_model or "",
                tower.tower_type or "",
                _to_csv_number(tower.longitude),
                _to_csv_number(tower.latitude),
                _normalize_str(_pick_export_value(profile.phase_sequence_1 if profile else None, _safe_dict(line.phase_sequence_json).get("I"))) or "",
                _normalize_str(_pick_export_value(profile.phase_sequence_2 if profile else None, _safe_dict(line.phase_sequence_json).get("II"))) or "",
                _normalize_str(_pick_export_value(profile.phase_sequence_3 if profile else None, _safe_dict(line.phase_sequence_json).get("III"))) or "",
                _normalize_str(_pick_export_value(profile.phase_sequence_4 if profile else None, _safe_dict(line.phase_sequence_json).get("IV"))) or "",
                _normalize_str(_pick_export_value(profile.arrester_a if profile else None, _safe_dict(line.arrester_install_json).get("A"))) or "",
                _normalize_str(_pick_export_value(profile.arrester_b if profile else None, _safe_dict(line.arrester_install_json).get("B"))) or "",
                _normalize_str(_pick_export_value(profile.arrester_c if profile else None, _safe_dict(line.arrester_install_json).get("C"))) or "",
                _to_csv_number(tower.ground_resistance_ohm),
                _to_csv_number(
                    _pick_export_float(
                        profile.protection_angle_left_deg if profile else None,
                        _read_nested_value(profile.geometry_layers_json if profile else None, "lightning_wire", "left_mid_distance_m"),
                        _read_nested_value(tower.circuit_geometry_json, "lightning_wire", "left_mid_distance_m"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.protection_angle_right_deg if profile else None,
                        _read_nested_value(profile.geometry_layers_json if profile else None, "lightning_wire", "right_mid_distance_m"),
                        _read_nested_value(tower.circuit_geometry_json, "lightning_wire", "right_mid_distance_m"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.shield_wire_height_m if profile else None,
                        _read_nested_value(profile.geometry_layers_json if profile else None, "lightning_wire", "height_m"),
                        _read_nested_value(tower.circuit_geometry_json, "lightning_wire", "height_m"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.insulator_length_m if profile else None,
                        _read_nested_value(profile.geometry_layers_json if profile else None, "insulator_length_mm"),
                        _read_nested_value(tower.circuit_geometry_json, "insulator_length_mm"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.call_height_m if profile else None,
                        _read_nested_value(profile.geometry_layers_json if profile else None, "tower_height_m"),
                        _read_nested_value(tower.circuit_geometry_json, "tower_height_m"),
                    )
                ),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_spacing_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_spacing_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_spacing_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_spacing_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_spacing_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_spacing_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_height_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_height_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_height_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_height_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "I", "phase_height_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "I", "phase_height_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_spacing_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_spacing_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_spacing_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_spacing_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_spacing_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_spacing_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_height_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_height_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_height_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_height_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "II", "phase_height_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "II", "phase_height_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_spacing_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_spacing_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_spacing_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_spacing_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_spacing_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_spacing_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_height_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_height_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_height_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_height_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "III", "phase_height_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "III", "phase_height_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_spacing_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_spacing_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_spacing_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_spacing_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_spacing_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_spacing_m", "lower"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_height_m", "upper"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_height_m", "upper"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_height_m", "middle"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_height_m", "middle"))),
                _to_csv_number(_pick_export_float(_read_nested_value(profile.geometry_layers_json if profile else None, "IV", "phase_height_m", "lower"), _read_nested_value(tower.circuit_geometry_json, "IV", "phase_height_m", "lower"))),
                _to_csv_number(tower.span_small_m),
                _to_csv_number(tower.span_large_m),
                _to_csv_number(
                    _pick_export_float(
                        profile.angle_deg if profile else None,
                        _safe_dict(line.lightning_param_json).get("电角度"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.current_a if profile else None,
                        _safe_dict(line.lightning_param_json).get("雷电流幅值a"),
                    )
                ),
                _to_csv_number(
                    _pick_export_float(
                        profile.current_b if profile else None,
                        _safe_dict(line.lightning_param_json).get("雷电流幅值b"),
                    )
                ),
                _to_csv_number(tower.slope_1),
                _to_csv_number(tower.slope_2),
                _to_csv_number(tower.altitude_m),
                tower.terrain or "",
                _to_csv_number(tower.lightning_density),
                _normalize_str(_pick_export_value(profile.structure_kind if profile else None, tower.tower_type)) or "",
                _normalize_str(_pick_export_value(profile.stroke_mode if profile else None, _safe_dict(tower.lightning_result_json).get("counterstroke_indicator"))) or "",
                _to_csv_number(_pick_export_float(_safe_dict(tower.lightning_result_json).get("counterstroke_withstand_ka"))),
                _to_csv_number(_pick_export_float(_safe_dict(tower.lightning_result_json).get("counterstroke_trip_rate"))),
                _to_csv_number(_pick_export_float(_safe_dict(tower.lightning_result_json).get("shielding_withstand_ka"))),
                _to_csv_number(_pick_export_float(_safe_dict(tower.lightning_result_json).get("shielding_trip_rate"))),
                _normalize_str(_pick_export_value(tower.risk_level, _safe_dict(tower.lightning_result_json).get("risk_level"))) or "",
                _json_dumps_compact(tower.circuit_geometry_json or {}),
                _json_dumps_compact(tower.lightning_result_json or {}),
                _json_dumps_compact(tower.raw_extra_json or {}),
            ]
        )

    filename = f"{line.code}_towers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return filename, output.getvalue().encode("utf-8-sig")


def _load_tower_counts(db: Session, line_ids: list[str]) -> dict[str, int]:
    if not line_ids:
        return {}
    rows = db.execute(
        select(LineTower.line_id, func.count())
        .where(LineTower.line_id.in_(line_ids))
        .group_by(LineTower.line_id)
    ).all()
    return {str(row[0]): int(row[1] or 0) for row in rows}


def _apply_line_metadata_from_csv(
    line: Line,
    row: dict[str, str] | None,
    *,
    actor_user_id: str,
    warnings: list[str],
) -> None:
    if not row:
        return

    csv_line_code = _normalize_str(row.get("线路编号"))
    if csv_line_code and csv_line_code != line.code:
        warnings.append(f"CSV 线路编号 {csv_line_code} 与当前线路编码 {line.code} 不一致，已保留当前线路编码")

    csv_line_name = _normalize_str(row.get("线路名称"))
    if csv_line_name:
        line.name = csv_line_name

    voltage = _parse_int(row.get("电压等级"))
    if voltage is not None:
        line.voltage_kv = voltage

    line.phase_sequence_json = {
        "I": _normalize_str(row.get("I回相序")),
        "II": _normalize_str(row.get("II回相序")),
        "III": _normalize_str(row.get("III回相序")),
        "IV": _normalize_str(row.get("IV回相序")),
    }
    line.arrester_install_json = {
        "A": _normalize_str(row.get("A相是否安装避雷器")),
        "B": _normalize_str(row.get("B相是否安装避雷器")),
        "C": _normalize_str(row.get("C相是否安装避雷器")),
    }
    line.lightning_param_json = {
        "电角度": _parse_float(row.get("电角度")),
        "雷电流幅值a": _parse_float(row.get("雷电流幅值a")),
        "雷电流幅值b": _parse_float(row.get("雷电流幅值b")),
    }
    line.update_user = actor_user_id
    line.update_date = utcnow()


def _build_circuit_geometry(row: dict[str, str]) -> dict[str, Any]:
    def value(key: str) -> float | None:
        return _parse_float(row.get(key))

    return {
        "I": {
            "phase_spacing_m": {
                "upper": value("I回上相中距m"),
                "middle": value("I回中相中距m"),
                "lower": value("I回下相中距m"),
            },
            "phase_height_m": {
                "upper": value("I回上相高度m"),
                "middle": value("I回中相高度m"),
                "lower": value("I回下相高度m"),
            },
        },
        "II": {
            "phase_spacing_m": {
                "upper": value("II回上相中距m"),
                "middle": value("II回中相中距m"),
                "lower": value("II回下相中距m"),
            },
            "phase_height_m": {
                "upper": value("II回上相高度m"),
                "middle": value("II回中相高度m"),
                "lower": value("II回下相高度m"),
            },
        },
        "III": {
            "phase_spacing_m": {
                "upper": value("III回上相中距m"),
                "middle": value("III回中相中距m"),
                "lower": value("III回下相中距m"),
            },
            "phase_height_m": {
                "upper": value("III回上相高度m"),
                "middle": value("III回中相高度m"),
                "lower": value("III回下相高度m"),
            },
        },
        "IV": {
            "phase_spacing_m": {
                "upper": value("IV回上相中距m"),
                "middle": value("IV回中相中距m"),
                "lower": value("IV回下相中距m"),
            },
            "phase_height_m": {
                "upper": value("IV回上相高度m"),
                "middle": value("IV回中相高度m"),
                "lower": value("IV回下相高度m"),
            },
        },
        "insulator_length_mm": _parse_float(row.get("绝缘子串长度mm")),
        "tower_height_m": _parse_float(row.get("杆塔呼高m")),
        "lightning_wire": {
            "left_mid_distance_m": _parse_float(row.get("左避雷中距m")),
            "right_mid_distance_m": _parse_float(row.get("右避雷中距m")),
            "height_m": _parse_float(row.get("避雷线高度m")),
        },
    }


def _build_lightning_result(row: dict[str, str]) -> dict[str, Any]:
    return {
        "counterstroke_indicator": _parse_float(row.get("绕击反击")),
        "counterstroke_withstand_ka": _parse_float(row.get("反击耐雷水平kA")),
        "counterstroke_trip_rate": _parse_float(row.get("反击跳闸率(次/100km.a)")),
        "shielding_withstand_ka": _parse_float(row.get("绕击耐雷水平kA")),
        "shielding_trip_rate": _parse_float(row.get("绕击跳闸率(次/100km.a)")),
        "risk_level": _normalize_str(row.get("雷击风险等级")),
    }


def _upsert_tower_profile_from_legacy_row(
    db: Session,
    *,
    tower: LineTower,
    row: dict[str, str],
    actor_user_id: str,
) -> None:
    profile = db.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one_or_none()
    now = utcnow()
    if profile is None:
        profile = TowerProfile(
            tower_id=tower.id,
            create_date=now,
            create_user=actor_user_id,
            update_date=now,
            update_user=actor_user_id,
        )
        db.add(profile)

    geometry_layers = _build_circuit_geometry(row)
    extra_profile_json = dict(profile.extra_profile_json or {})

    profile.phase_sequence_1 = _pick_optional_value(_normalize_str(row.get("I回相序")), profile.phase_sequence_1)
    profile.phase_sequence_2 = _pick_optional_value(_normalize_str(row.get("II回相序")), profile.phase_sequence_2)
    profile.phase_sequence_3 = _pick_optional_value(_normalize_str(row.get("III回相序")), profile.phase_sequence_3)
    profile.phase_sequence_4 = _pick_optional_value(_normalize_str(row.get("IV回相序")), profile.phase_sequence_4)
    profile.arrester_a = _pick_optional_value(_normalize_str(row.get("A相是否安装避雷器")), profile.arrester_a)
    profile.arrester_b = _pick_optional_value(_normalize_str(row.get("B相是否安装避雷器")), profile.arrester_b)
    profile.arrester_c = _pick_optional_value(_normalize_str(row.get("C相是否安装避雷器")), profile.arrester_c)
    profile.protection_angle_left_deg = _pick_optional_value(_parse_float(row.get("左避雷中距m")), profile.protection_angle_left_deg)
    profile.protection_angle_right_deg = _pick_optional_value(_parse_float(row.get("右避雷中距m")), profile.protection_angle_right_deg)
    profile.shield_wire_height_m = _pick_optional_value(_parse_float(row.get("避雷线高度m")), profile.shield_wire_height_m)
    profile.insulator_length_m = _pick_optional_value(_parse_float(row.get("绝缘子串长度mm")), profile.insulator_length_m)
    profile.call_height_m = _pick_optional_value(_parse_float(row.get("杆塔呼高m")), profile.call_height_m)
    profile.angle_deg = _pick_optional_value(_parse_float(row.get("电角度")), profile.angle_deg)
    profile.current_a = _pick_optional_value(_parse_float(row.get("雷电流幅值a")), profile.current_a)
    profile.current_b = _pick_optional_value(_parse_float(row.get("雷电流幅值b")), profile.current_b)
    profile.structure_kind = _pick_optional_value(_normalize_str(row.get("直线或耐张杆塔")), profile.structure_kind)
    profile.stroke_mode = _pick_optional_value(_normalize_str(row.get("绕击反击")), profile.stroke_mode)
    profile.geometry_layers_json = _pick_dict_value(geometry_layers, profile.geometry_layers_json or {})

    cause_analysis = _normalize_str(row.get("原因分析"))
    mitigation_recommendation = _normalize_str(row.get("措施推荐"))
    if cause_analysis is not None:
        extra_profile_json["cause_analysis"] = cause_analysis
    if mitigation_recommendation is not None:
        extra_profile_json["mitigation_recommendation"] = mitigation_recommendation
    profile.extra_profile_json = extra_profile_json
    profile.update_date = now
    profile.update_user = actor_user_id


def _extract_extra_values(row: dict[str, str], extra_headers: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in extra_headers:
        value = _normalize_str(row.get(key))
        if value is not None:
            result[key] = value
    return result


def _decode_csv_bytes(content: bytes) -> str:
    for encoding in CSV_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV encoding is not supported")


def _normalize_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {"-1", "-1.0"}:
        return None
    return text


def _parse_float(value: Any) -> float | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return int(float(normalized))
    except ValueError:
        return None


def _json_dumps_compact(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _read_nested_value(value: Any, *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _pick_export_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _pick_export_float(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        parsed = _parse_float(value)
        if parsed is not None:
            return parsed
    return None


def _to_csv_number(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _publish_line_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            LINE_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lines"],
            dedupe_key=f"{event_name}:{payload.get('line_id', 'unknown')}",
        )
    )


def _pick_optional_value(primary: Any, fallback: Any) -> Any:
    if primary is None:
        return fallback
    if isinstance(primary, str) and not primary.strip():
        return fallback
    return primary


def _pick_dict_value(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if _has_meaningful_dict_data(primary):
        return primary
    if fallback:
        return fallback
    return {}


def _has_meaningful_dict_data(value: dict[str, Any] | None) -> bool:
    if not value:
        return False
    for item in value.values():
        if item is None:
            continue
        if isinstance(item, dict):
            if _has_meaningful_dict_data(item):
                return True
            continue
        if isinstance(item, list):
            if len(item) > 0:
                return True
            continue
        return True
    return False


def _extract_model_default_dict(defaults: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not defaults:
        return {}
    raw_json = defaults.get("raw_json")
    if not isinstance(raw_json, dict):
        return {}
    candidate = raw_json.get(key)
    if isinstance(candidate, dict):
        return candidate
    return {}


def _load_tower_model_defaults(db: Session, model_code: str | None) -> dict[str, Any] | None:
    normalized = _normalize_str(model_code)
    if normalized is None:
        return None
    model = db.execute(
        select(TowerModel).where(
            func.lower(TowerModel.code) == normalized.lower(),
            TowerModel.is_enabled.is_(True),
        )
    ).scalar_one_or_none()
    if not model:
        return None

    return {
        "tower_model": model.code,
        "tower_type": model.tower_type,
        "altitude_m": model.default_altitude_m,
        "terrain": model.default_terrain,
        "ground_resistance_ohm": model.default_ground_resistance_ohm,
        "lightning_density": model.default_lightning_density,
        "span_small_m": model.default_span_small_m,
        "span_large_m": model.default_span_large_m,
        "slope_1": model.default_slope_1,
        "slope_2": model.default_slope_2,
        "risk_level": model.default_risk_level,
        "raw_json": model.default_raw_json or {},
    }


def _load_tower_model_defaults_from_row(
    db: Session,
    *,
    source_row: dict[str, str],
    source_model_name: str | None,
) -> dict[str, Any] | None:
    from .tower_model_service import derive_tower_model_code_from_legacy, derive_tower_model_default_values_from_legacy_row

    model_code = derive_tower_model_code_from_legacy(source_model_name or "")
    model_defaults = _load_tower_model_defaults(db, model_code)
    if model_defaults:
        return model_defaults

    if not model_code:
        return None

    fallback = derive_tower_model_default_values_from_legacy_row(source_row)
    if not fallback:
        return None
    return {
        "tower_model": model_code,
        "tower_type": fallback.get("tower_type"),
        "altitude_m": fallback.get("altitude_m"),
        "terrain": fallback.get("terrain"),
        "ground_resistance_ohm": fallback.get("ground_resistance_ohm"),
        "lightning_density": fallback.get("lightning_density"),
        "span_small_m": fallback.get("span_small_m"),
        "span_large_m": fallback.get("span_large_m"),
        "slope_1": fallback.get("slope_1"),
        "slope_2": fallback.get("slope_2"),
        "risk_level": fallback.get("risk_level"),
        "raw_json": fallback.get("raw_json") or {},
    }


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)


def _generate_line_code(db: Session) -> str:
    date_part = utcnow().strftime("%Y%m%d")
    for _ in range(20):
        candidate = f"{LINE_CODE_PREFIX}-{date_part}-{uuid4().hex[:6].upper()}"
        if not get_line_by_code(db, candidate):
            return candidate
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate unique line code")
