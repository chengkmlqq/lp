from __future__ import annotations

import asyncio
import csv
import io
import mimetypes
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.tower_model import TowerModel
from ..models.user import User
from ..schemas.tower_model import (
    TowerModelCreateRequest,
    TowerModelImageUploadResponse,
    TowerModelListResponse,
    TowerModelSeedResponse,
    TowerModelSummary,
    TowerModelUpdateRequest,
)
from .file_service import _build_driver_or_400, _require_mount, list_enabled_mounts
from .push_service import publish_topic
from .storage_driver import (
    StorageDriverError,
    StorageInvalidPathError,
    StoragePathNotFoundError,
    join_virtual_path,
    normalize_virtual_path,
)

TOWER_MODEL_TOPIC = "admin.tower-models"
DEFAULT_TOWER_MODEL_IMAGE_DIR = "/tower-models/images"
DEFAULT_SEED_SOURCE_TAG = "legacy-fl"
LEGACY_WORKSPACE_ROOT = Path("/root/.openclaw/workspace/fl")
LEGACY_SETTING_PATH = LEGACY_WORKSPACE_ROOT / "执行目录-2025-11-20" / "Primary" / "LP_Setting.txt"
LEGACY_GANTA_PATH = LEGACY_WORKSPACE_ROOT / "执行目录-2025-11-20" / "Primary" / "LP_GanTa.txt"
LEGACY_MODELS_IMAGE_DIR = LEGACY_WORKSPACE_ROOT / "执行目录-2025-11-20" / "Models"


def serialize_tower_model(item: TowerModel) -> TowerModelSummary:
    return TowerModelSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        tower_type=item.tower_type,
        description=item.description,
        image_mount_code=item.image_mount_code,
        image_path=item.image_path,
        source_tag=item.source_tag,
        is_enabled=item.is_enabled,
        sort_order=item.sort_order,
        default_altitude_m=item.default_altitude_m,
        default_terrain=item.default_terrain,
        default_ground_resistance_ohm=item.default_ground_resistance_ohm,
        default_lightning_density=item.default_lightning_density,
        default_span_small_m=item.default_span_small_m,
        default_span_large_m=item.default_span_large_m,
        default_slope_1=item.default_slope_1,
        default_slope_2=item.default_slope_2,
        default_risk_level=item.default_risk_level,
        default_raw_json=item.default_raw_json or {},
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_tower_models(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    enabled: bool | None,
) -> TowerModelListResponse:
    stmt = select(TowerModel)
    total_stmt = select(func.count()).select_from(TowerModel)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = or_(
            TowerModel.code.ilike(like),
            TowerModel.name.ilike(like),
            TowerModel.tower_type.ilike(like),
        )
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    if enabled is not None:
        stmt = stmt.where(TowerModel.is_enabled == enabled)
        total_stmt = total_stmt.where(TowerModel.is_enabled == enabled)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(TowerModel.sort_order.asc(), TowerModel.code.asc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()
    return TowerModelListResponse(
        items=[serialize_tower_model(item) for item in items],
        total=total,
    )


def list_tower_models_for_selector(db: Session) -> list[TowerModelSummary]:
    items = db.execute(
        select(TowerModel)
        .where(TowerModel.is_enabled.is_(True))
        .order_by(TowerModel.sort_order.asc(), TowerModel.code.asc())
    ).scalars().all()
    return [serialize_tower_model(item) for item in items]


def get_tower_model_by_id(db: Session, model_id: str) -> TowerModel | None:
    return db.execute(
        select(TowerModel).where(TowerModel.id == model_id)
    ).scalar_one_or_none()


def get_tower_model_by_code(db: Session, code: str) -> TowerModel | None:
    normalized = code.strip()
    if not normalized:
        return None
    return db.execute(
        select(TowerModel).where(func.lower(TowerModel.code) == normalized.lower())
    ).scalar_one_or_none()


def create_tower_model(
    db: Session,
    payload: TowerModelCreateRequest,
    *,
    actor: User,
) -> TowerModelSummary | None:
    normalized_code = payload.code.strip()
    if get_tower_model_by_code(db, normalized_code):
        return None

    now = utcnow()
    item = TowerModel(
        code=normalized_code,
        name=payload.name.strip(),
        tower_type=_normalize_str(payload.tower_type),
        description=_normalize_str(payload.description),
        image_mount_code=_normalize_str(payload.image_mount_code),
        image_path=_normalize_path(payload.image_path),
        source_tag=_normalize_str(payload.source_tag),
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
        default_altitude_m=payload.default_altitude_m,
        default_terrain=_normalize_str(payload.default_terrain),
        default_ground_resistance_ohm=payload.default_ground_resistance_ohm,
        default_lightning_density=payload.default_lightning_density,
        default_span_small_m=payload.default_span_small_m,
        default_span_large_m=payload.default_span_large_m,
        default_slope_1=payload.default_slope_1,
        default_slope_2=payload.default_slope_2,
        default_risk_level=_normalize_str(payload.default_risk_level),
        default_raw_json=payload.default_raw_json or {},
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(item)
    db.commit()
    saved = get_tower_model_by_id(db, item.id)
    if not saved:
        return None
    _publish_tower_model_change(
        "tower-model.created",
        {"action": "tower_model_created", "model_id": saved.id},
    )
    return serialize_tower_model(saved)


def update_tower_model(
    db: Session,
    model_id: str,
    payload: TowerModelUpdateRequest,
    *,
    actor: User,
) -> TowerModelSummary | None:
    item = get_tower_model_by_id(db, model_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        item.name = str(update_data["name"]).strip()
    if "tower_type" in update_data:
        item.tower_type = _normalize_str(update_data["tower_type"])
    if "description" in update_data:
        item.description = _normalize_str(update_data["description"])
    if "image_mount_code" in update_data:
        item.image_mount_code = _normalize_str(update_data["image_mount_code"])
    if "image_path" in update_data:
        item.image_path = _normalize_path(update_data["image_path"])
    if "source_tag" in update_data:
        item.source_tag = _normalize_str(update_data["source_tag"])
    if "is_enabled" in update_data and update_data["is_enabled"] is not None:
        item.is_enabled = bool(update_data["is_enabled"])
    if "sort_order" in update_data and update_data["sort_order"] is not None:
        item.sort_order = int(update_data["sort_order"])

    for field in (
        "default_altitude_m",
        "default_ground_resistance_ohm",
        "default_lightning_density",
        "default_span_small_m",
        "default_span_large_m",
        "default_slope_1",
        "default_slope_2",
    ):
        if field in update_data:
            setattr(item, field, update_data[field])

    if "default_terrain" in update_data:
        item.default_terrain = _normalize_str(update_data["default_terrain"])
    if "default_risk_level" in update_data:
        item.default_risk_level = _normalize_str(update_data["default_risk_level"])
    if "default_raw_json" in update_data and update_data["default_raw_json"] is not None:
        item.default_raw_json = dict(update_data["default_raw_json"])

    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_tower_model_by_id(db, model_id)
    if not saved:
        return None
    _publish_tower_model_change(
        "tower-model.updated",
        {"action": "tower_model_updated", "model_id": model_id},
    )
    return serialize_tower_model(saved)


def delete_tower_model(db: Session, model_id: str) -> bool:
    item = get_tower_model_by_id(db, model_id)
    if not item:
        return False

    db.delete(item)
    db.commit()
    _publish_tower_model_change(
        "tower-model.deleted",
        {"action": "tower_model_deleted", "model_id": model_id},
    )
    return True


def upload_tower_model_image(
    db: Session,
    *,
    model_id: str,
    mount_code: str,
    file: UploadFile,
    actor: User,
) -> TowerModelImageUploadResponse:
    item = get_tower_model_by_id(db, model_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型不存在")

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片格式不支持，仅支持 jpg/jpeg/png/webp/gif/bmp")

    try:
        content = file.file.read()
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传图片为空")

    mount = _require_mount(db, mount_code)
    driver = _build_driver_or_400(mount)
    image_dir = normalize_virtual_path(DEFAULT_TOWER_MODEL_IMAGE_DIR)
    _ensure_directory(driver, image_dir)
    safe_basename = _sanitize_filename(item.code) or "tower_model"
    target_name = f"{safe_basename}{suffix}"
    target_path = join_virtual_path(image_dir, target_name)

    content_type = file.content_type or mimetypes.guess_type(filename)[0]
    try:
        driver.write_file(target_path, content=content, content_type=content_type)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    item.image_mount_code = mount.code
    item.image_path = target_path
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_tower_model_by_id(db, model_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="保存图片关联失败")

    _publish_tower_model_change(
        "tower-model.image-uploaded",
        {"action": "tower_model_image_uploaded", "model_id": model_id},
    )
    return TowerModelImageUploadResponse(
        model=serialize_tower_model(saved),
        mount_code=mount.code,
        image_path=target_path,
    )


def seed_tower_models_from_legacy(
    db: Session,
    *,
    actor: User,
    overwrite_existing: bool,
) -> TowerModelSeedResponse:
    if not LEGACY_SETTING_PATH.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"老系统配置文件不存在: {LEGACY_SETTING_PATH}")
    if not LEGACY_GANTA_PATH.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"老系统杆塔文件不存在: {LEGACY_GANTA_PATH}")
    if not LEGACY_MODELS_IMAGE_DIR.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"老系统图片目录不存在: {LEGACY_MODELS_IMAGE_DIR}")

    mount = _resolve_default_mount(db)
    driver = _build_driver_or_400(mount)
    image_dir = normalize_virtual_path(DEFAULT_TOWER_MODEL_IMAGE_DIR)
    _ensure_directory(driver, image_dir)

    model_codes = _load_legacy_model_codes(LEGACY_SETTING_PATH)
    defaults_by_model = _load_legacy_defaults_by_model(LEGACY_GANTA_PATH)
    if not model_codes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="老系统配置未解析到杆塔模型清单")

    imported_models = 0
    updated_models = 0
    skipped_models = 0
    copied_images = 0
    warnings: list[str] = []

    for sort_index, model_code in enumerate(model_codes, start=1):
        existing = get_tower_model_by_code(db, model_code)
        defaults = defaults_by_model.get(model_code, {})

        image_path = None
        source_image = _find_legacy_image_file(model_code)
        if source_image is not None:
            target_name = f"{_sanitize_filename(model_code) or model_code}.jpg"
            target_path = join_virtual_path(image_dir, target_name)
            try:
                driver.write_file(
                    target_path,
                    content=source_image.read_bytes(),
                    content_type=mimetypes.guess_type(source_image.name)[0] or "image/jpeg",
                )
                image_path = target_path
                copied_images += 1
            except Exception as exc:
                warnings.append(f"模型 {model_code} 图片复制失败: {exc}")
        else:
            warnings.append(f"模型 {model_code} 未找到匹配图片")

        if existing and not overwrite_existing:
            skipped_models += 1
            continue

        if existing is None:
            now = utcnow()
            existing = TowerModel(
                code=model_code,
                name=model_code,
                source_tag=DEFAULT_SEED_SOURCE_TAG,
                is_enabled=True,
                sort_order=sort_index,
                create_date=now,
                create_user=actor.id,
                update_date=now,
                update_user=actor.id,
            )
            db.add(existing)
            imported_models += 1
        else:
            updated_models += 1

        existing.source_tag = DEFAULT_SEED_SOURCE_TAG
        existing.is_enabled = True
        existing.sort_order = sort_index
        existing.tower_type = _normalize_str(str(defaults.get("tower_type") or ""))
        existing.default_altitude_m = _coerce_optional_float(defaults.get("altitude_m"))
        existing.default_terrain = _normalize_str(str(defaults.get("terrain") or ""))
        existing.default_ground_resistance_ohm = _coerce_optional_float(defaults.get("ground_resistance_ohm"))
        existing.default_lightning_density = _coerce_optional_float(defaults.get("lightning_density"))
        existing.default_span_small_m = _coerce_optional_float(defaults.get("span_small_m"))
        existing.default_span_large_m = _coerce_optional_float(defaults.get("span_large_m"))
        existing.default_slope_1 = _coerce_optional_float(defaults.get("slope_1"))
        existing.default_slope_2 = _coerce_optional_float(defaults.get("slope_2"))
        existing.default_risk_level = _normalize_str(str(defaults.get("risk_level") or ""))
        existing.default_raw_json = dict(defaults.get("raw_json") or {})
        if image_path:
            existing.image_mount_code = mount.code
            existing.image_path = image_path
        existing.update_user = actor.id
        existing.update_date = utcnow()

    db.commit()

    _publish_tower_model_change(
        "tower-model.seeded",
        {
            "action": "tower_model_seeded",
            "imported_models": imported_models,
            "updated_models": updated_models,
            "skipped_models": skipped_models,
        },
    )
    return TowerModelSeedResponse(
        total_models=len(model_codes),
        imported_models=imported_models,
        updated_models=updated_models,
        skipped_models=skipped_models,
        copied_images=copied_images,
        warnings=warnings,
    )


def seed_tower_models_from_upload(
    db: Session,
    *,
    actor: User,
    overwrite_existing: bool,
    setting_file: UploadFile,
    ganta_file: UploadFile,
    images_zip: UploadFile | None,
) -> TowerModelSeedResponse:
    setting_name = (setting_file.filename or "").strip()
    ganta_name = (ganta_file.filename or "").strip()
    if not setting_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="LP_Setting 文件名不能为空")
    if not ganta_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="LP_GanTa 文件名不能为空")

    setting_bytes = _read_upload_bytes(setting_file, label="LP_Setting")
    ganta_bytes = _read_upload_bytes(ganta_file, label="LP_GanTa")
    image_bytes_map = _load_image_bytes_from_zip(images_zip)

    mount = _resolve_default_mount(db)
    driver = _build_driver_or_400(mount)
    image_dir = normalize_virtual_path(DEFAULT_TOWER_MODEL_IMAGE_DIR)
    _ensure_directory(driver, image_dir)

    model_codes = _load_legacy_model_codes_from_text(_decode_csv_bytes(setting_bytes))
    defaults_by_model = _load_legacy_defaults_by_model_from_bytes(ganta_bytes)
    if not model_codes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传的 LP_Setting 未解析到杆塔模型清单")

    imported_models = 0
    updated_models = 0
    skipped_models = 0
    copied_images = 0
    warnings: list[str] = []

    for sort_index, model_code in enumerate(model_codes, start=1):
        existing = get_tower_model_by_code(db, model_code)
        defaults = defaults_by_model.get(model_code, {})

        image_path = None
        image_payload = image_bytes_map.get(model_code)
        if image_payload is not None:
            suffix, content, content_type = image_payload
            target_name = f"{_sanitize_filename(model_code) or model_code}{suffix}"
            target_path = join_virtual_path(image_dir, target_name)
            try:
                driver.write_file(
                    target_path,
                    content=content,
                    content_type=content_type,
                )
                image_path = target_path
                copied_images += 1
            except Exception as exc:
                warnings.append(f"模型 {model_code} 图片复制失败: {exc}")
        else:
            warnings.append(f"模型 {model_code} 未在上传图片包中找到匹配图片")

        if existing and not overwrite_existing:
            skipped_models += 1
            continue

        if existing is None:
            now = utcnow()
            existing = TowerModel(
                code=model_code,
                name=model_code,
                source_tag=DEFAULT_SEED_SOURCE_TAG,
                is_enabled=True,
                sort_order=sort_index,
                create_date=now,
                create_user=actor.id,
                update_date=now,
                update_user=actor.id,
            )
            db.add(existing)
            imported_models += 1
        else:
            updated_models += 1

        existing.source_tag = DEFAULT_SEED_SOURCE_TAG
        existing.is_enabled = True
        existing.sort_order = sort_index
        existing.tower_type = _normalize_str(str(defaults.get("tower_type") or ""))
        existing.default_altitude_m = _coerce_optional_float(defaults.get("altitude_m"))
        existing.default_terrain = _normalize_str(str(defaults.get("terrain") or ""))
        existing.default_ground_resistance_ohm = _coerce_optional_float(defaults.get("ground_resistance_ohm"))
        existing.default_lightning_density = _coerce_optional_float(defaults.get("lightning_density"))
        existing.default_span_small_m = _coerce_optional_float(defaults.get("span_small_m"))
        existing.default_span_large_m = _coerce_optional_float(defaults.get("span_large_m"))
        existing.default_slope_1 = _coerce_optional_float(defaults.get("slope_1"))
        existing.default_slope_2 = _coerce_optional_float(defaults.get("slope_2"))
        existing.default_risk_level = _normalize_str(str(defaults.get("risk_level") or ""))
        existing.default_raw_json = dict(defaults.get("raw_json") or {})
        if image_path:
            existing.image_mount_code = mount.code
            existing.image_path = image_path
        existing.update_user = actor.id
        existing.update_date = utcnow()

    db.commit()

    _publish_tower_model_change(
        "tower-model.seeded",
        {
            "action": "tower_model_seeded",
            "imported_models": imported_models,
            "updated_models": updated_models,
            "skipped_models": skipped_models,
        },
    )
    return TowerModelSeedResponse(
        total_models=len(model_codes),
        imported_models=imported_models,
        updated_models=updated_models,
        skipped_models=skipped_models,
        copied_images=copied_images,
        warnings=warnings,
    )


def resolve_tower_model_defaults(
    db: Session,
    *,
    model_code: str,
) -> TowerModelSummary | None:
    item = get_tower_model_by_code(db, model_code)
    if not item or not item.is_enabled:
        return None
    return serialize_tower_model(item)


def _resolve_default_mount(db: Session):
    mounts = list_enabled_mounts(db)
    if not mounts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前未配置可用文件挂载点")
    return mounts[0]


def _ensure_directory(driver: Any, path: str) -> None:
    try:
        driver.ensure_directory(path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _load_legacy_model_codes(setting_path: Path) -> list[str]:
    text = setting_path.read_text(encoding="utf-8", errors="ignore")
    return _load_legacy_model_codes_from_text(text)


def _load_legacy_model_codes_from_text(text: str) -> list[str]:
    start_tag = "<GanTaType_Models>"
    end_tag = "</GanTaType_Models>"
    start = text.find(start_tag)
    end = text.find(end_tag)
    if start < 0 or end < 0 or end <= start:
        return []
    body = text[start + len(start_tag):end]
    items = [line.strip() for line in body.splitlines()]
    return [item for item in items if item]


def _load_legacy_defaults_by_model(ganta_path: Path) -> dict[str, dict[str, Any]]:
    content = ganta_path.read_bytes()
    return _load_legacy_defaults_by_model_from_bytes(content)


def _load_legacy_defaults_by_model_from_bytes(content: bytes) -> dict[str, dict[str, Any]]:
    decoded = _decode_csv_bytes(content)
    rows = list(csv.DictReader(io.StringIO(decoded)))
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        values = derive_tower_model_default_values_from_legacy_row(row)
        model_code = _normalize_str(values.get("model_code"))
        if not model_code:
            continue
        if model_code in result:
            continue
        result[model_code] = values

    return result


def _find_legacy_image_file(model_code: str) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        candidate = LEGACY_MODELS_IMAGE_DIR / f"{model_code}{suffix}"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _decode_csv_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="老系统 CSV 编码无法识别")


def _read_upload_bytes(file: UploadFile, *, label: str) -> bytes:
    try:
        content = file.file.read()
    finally:
        try:
            file.file.close()
        except Exception:
            pass
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{label} 文件为空")
    return content


def _load_image_bytes_from_zip(images_zip: UploadFile | None) -> dict[str, tuple[str, bytes, str]]:
    if images_zip is None:
        return {}

    filename = (images_zip.filename or "").strip().lower()
    if filename and not filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片包必须是 zip 格式")

    content = _read_upload_bytes(images_zip, label="图片压缩包")
    mapping: dict[str, tuple[str, bytes, str]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                suffix = Path(name).suffix.lower()
                if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
                    continue
                stem = _normalize_str(Path(name).stem)
                if not stem or stem in mapping:
                    continue
                file_content = zf.read(info)
                if not file_content:
                    continue
                content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                mapping[stem] = (suffix, file_content, content_type)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="图片压缩包格式非法") from exc

    return mapping


def _parse_float_value(value: Any) -> float | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _build_circuit_geometry_from_row(row: dict[str, Any]) -> dict[str, Any]:
    def value(key: str) -> float | None:
        return _parse_float_value(row.get(key))

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
        "insulator_length_mm": _parse_float_value(row.get("绝缘子串长度mm")),
        "tower_height_m": _parse_float_value(row.get("杆塔呼高m")),
        "lightning_wire": {
            "left_mid_distance_m": _parse_float_value(row.get("左避雷中距m")),
            "right_mid_distance_m": _parse_float_value(row.get("右避雷中距m")),
            "height_m": _parse_float_value(row.get("避雷线高度m")),
        },
    }


def _build_lightning_result_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "counterstroke_indicator": _parse_float_value(row.get("绕击反击")),
        "counterstroke_withstand_ka": _parse_float_value(row.get("反击耐雷水平kA")),
        "counterstroke_trip_rate": _parse_float_value(row.get("反击跳闸率(次/100km.a)")),
        "shielding_withstand_ka": _parse_float_value(row.get("绕击耐雷水平kA")),
        "shielding_trip_rate": _parse_float_value(row.get("绕击跳闸率(次/100km.a)")),
        "risk_level": _normalize_str(row.get("雷击风险等级")),
    }


def _to_bool_from_text(value: Any) -> bool | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered in {"是", "true", "1", "yes", "y"}:
        return True
    if lowered in {"否", "false", "0", "no", "n"}:
        return False
    return None


def _normalize_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in {"-1", "-1.0"}:
        return None
    return text


def _normalize_path(value: Any) -> str | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return normalize_virtual_path(normalized)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _safe_float(value: Any) -> float | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _safe_int(value: Any) -> int | None:
    normalized = _normalize_str(value)
    if normalized is None:
        return None
    try:
        return int(float(normalized))
    except ValueError:
        return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _safe_float(value)


def _sanitize_filename(value: str) -> str:
    sanitized = value.strip()
    if not sanitized:
        return ""
    for char in ('\\', '/', ':', '*', '?', '"', "<", ">", "|", " "):
        sanitized = sanitized.replace(char, "_")
    return sanitized


def derive_tower_model_code_from_legacy(model_name: str) -> str:
    normalized = _normalize_str(model_name)
    if normalized is None:
        return ""
    return normalized


def derive_tower_model_default_values_from_legacy_row(row: dict[str, Any]) -> dict[str, Any]:
    model_code = derive_tower_model_code_from_legacy(row.get("杆塔模型"))
    default_dsmd = _safe_float(row.get("地闪密度"))
    default_ground_resistance = _safe_float(row.get("接地电阻"))
    if default_dsmd is None:
        default_dsmd = 2.8
    if default_ground_resistance is None:
        default_ground_resistance = 15.0

    default_raw_json = {
        "legacy_defaults": {
            "voltage_kv": _safe_int(row.get("电压等级")),
            "phase_sequence": {
                "I": _normalize_str(row.get("I回相序")),
                "II": _normalize_str(row.get("II回相序")),
                "III": _normalize_str(row.get("III回相序")),
                "IV": _normalize_str(row.get("IV回相序")),
            },
            "arrester_install": {
                "A": _to_bool_from_text(row.get("A相是否安装避雷器")),
                "B": _to_bool_from_text(row.get("B相是否安装避雷器")),
                "C": _to_bool_from_text(row.get("C相是否安装避雷器")),
            },
            "left_lightning_mid_distance_m": _safe_float(row.get("左避雷中距m")),
            "right_lightning_mid_distance_m": _safe_float(row.get("右避雷中距m")),
            "lightning_wire_height_m": _safe_float(row.get("避雷线高度m")),
            "insulator_length_mm": _safe_float(row.get("绝缘子串长度mm")),
            "tower_height_m": _safe_float(row.get("杆塔呼高m")),
            "electric_angle": _safe_float(row.get("电角度")),
            "current_a": _safe_float(row.get("雷电流幅值a")) or 31.0,
            "current_b": _safe_float(row.get("雷电流幅值b")) or 2.6,
            "rao_ji_fan_ji": _safe_int(row.get("绕击反击")) or 3,
            "counterstrike_level_ka": _safe_float(row.get("反击耐雷水平kA")),
            "counterstrike_trip_rate": _safe_float(row.get("反击跳闸率(次/100km.a)")),
            "shielding_level_ka": _safe_float(row.get("绕击耐雷水平kA")),
            "shielding_trip_rate": _safe_float(row.get("绕击跳闸率(次/100km.a)")),
            "reason_analysis": _normalize_str(row.get("原因分析")),
            "measure_recommend": _normalize_str(row.get("措施推荐")),
        },
        "circuit_geometry_json": _build_circuit_geometry_from_row(row),
        "lightning_result_json": _build_lightning_result_from_row(row),
    }
    return {
        "model_code": model_code,
        "tower_type": _normalize_str(row.get("直线或耐张杆塔")),
        "altitude_m": _safe_float(row.get("海拔m")),
        "terrain": _normalize_str(row.get("地形")),
        "ground_resistance_ohm": default_ground_resistance,
        "lightning_density": default_dsmd,
        "span_small_m": _safe_float(row.get("小号侧档距")),
        "span_large_m": _safe_float(row.get("大号侧档距")),
        "slope_1": _safe_float(row.get("地面倾角1")),
        "slope_2": _safe_float(row.get("地面倾角2")),
        "risk_level": _normalize_str(row.get("雷击风险等级")),
        "raw_json": default_raw_json,
    }


def _publish_tower_model_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            TOWER_MODEL_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/tower-models"],
            dedupe_key=f"{event_name}:{payload.get('model_id', 'all')}",
        )
    )


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)
