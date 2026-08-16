from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.elevation import ElevationApplyJob, ElevationFileRecord
from ..models.line import Line
from ..models.user import User
from ..schemas.elevation import (
    ElevationDatasetListResponse,
    ElevationDatasetSummary,
    ElevationFileRecordAnalyzeResponse,
    ElevationFileRecordCreateRequest,
    ElevationFileRecordListResponse,
    ElevationFileRecordPreviewResponse,
    ElevationFileRecordSummary,
    ElevationFileRecordTerrainBuildResponse,
    ElevationFileRecordUpdateRequest,
    ElevationFileRecordUploadResponse,
)
from .elevation_service import (
    ELEVATION_FILE_EXT_FORMAT_MAP,
    IMPORTABLE_ELEVATION_EXTENSIONS,
    IMPORTABLE_ARCHIVE_EXTENSIONS,
    RASTER_FILE_FORMATS,
    TERRAIN_SUPPORTED_DATASET_FORMATS,
    _build_raster_preview,
    _default_terrain_status_for_format,
    _normalize_str,
    _publish_elevation_change,
    _require_mount,
    _require_rasterio_available,
    _resolve_dataset_mount_code,
    _resolve_file_record_terrain_dir,
    _delete_virtual_directory_if_exists,

    join_virtual_path,
)
from .file_service import _build_driver_or_400


def serialize_file_record(
    item: ElevationFileRecord,
    *,
    linked_line_count: int = 0,
) -> ElevationFileRecordSummary:
    return ElevationFileRecordSummary(
        id=item.id,
        file_name=item.file_name,
        file_path=item.file_path,
        file_format=item.file_format,
        file_size=item.file_size,
        source=item.source,
        mount_code=item.mount_code,
        resolution_m=item.resolution_m,
        status=item.status,  # type: ignore[arg-type]
        data_source_type=item.data_source_type,
        linked_line_count=linked_line_count,
        bbox_min_lon=item.bbox_min_lon,
        bbox_max_lon=item.bbox_max_lon,
        bbox_min_lat=item.bbox_min_lat,
        bbox_max_lat=item.bbox_max_lat,
        sample_count=item.sample_count,
        analysis_task_id=item.analysis_task_id,
        analysis_status=item.analysis_status,
        analysis_error_message=item.analysis_error_message,
        analysis_started_at=item.analysis_started_at,
        analysis_finished_at=item.analysis_finished_at,
        terrain_status=item.terrain_status,  # type: ignore[arg-type]
        terrain_task_id=item.terrain_task_id,
        terrain_error_message=item.terrain_error_message,
        terrain_root_path=item.terrain_root_path,
        terrain_url_template=item.terrain_url_template,
        terrain_min_zoom=item.terrain_min_zoom,
        terrain_max_zoom=item.terrain_max_zoom,
        terrain_bounds=item.terrain_bounds,
        terrain_metadata=item.terrain_metadata,
        notes=item.notes,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_file_records(
    db: Session,
    *,
    keyword: str | None,
    status_filter: str | None,
) -> ElevationFileRecordListResponse:
    stmt = select(ElevationFileRecord)
    total_stmt = select(func.count()).select_from(ElevationFileRecord)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = (
            ElevationFileRecord.file_name.ilike(like)
            | ElevationFileRecord.source.ilike(like)
        )
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    if status_filter in {"active", "disabled"}:
        stmt = stmt.where(ElevationFileRecord.status == status_filter)
        total_stmt = total_stmt.where(ElevationFileRecord.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(ElevationFileRecord.update_date.desc(), ElevationFileRecord.create_date.desc())
    ).scalars().all()

    if not items:
        return ElevationFileRecordListResponse(items=[], total=total)

    # 关联线路数：SQL 子查询统计（一对多，一个文件可能对同一线路多次回填，需 DISTINCT）
    linked_count_sub = (
        select(
            ElevationApplyJob.file_record_id,
            func.count(func.distinct(ElevationApplyJob.line_id)).label("linked_line_count"),
        )
        .where(ElevationApplyJob.file_record_id.in_([item.id for item in items]))
        .group_by(ElevationApplyJob.file_record_id)
    )
    linked_counts = dict(db.execute(linked_count_sub).all())

    return ElevationFileRecordListResponse(
        items=[
            serialize_file_record(item, linked_line_count=int(linked_counts.get(item.id, 0)))
            for item in items
        ],
        total=total,
    )


def serialize_elevation_dataset(item: ElevationFileRecord) -> ElevationDatasetSummary:
    """Map an ElevationFileRecord to the legacy ElevationDatasetSummary format."""
    from pathlib import Path as _Path
    return ElevationDatasetSummary(
        id=item.id,
        code=item.id,
        name=item.file_name,
        source=item.source,
        file_format=item.file_format,
        mount_code=item.mount_code,
        dataset_dir=str(_Path(item.file_path).parent) if item.file_path else "",
        file_path=item.file_path,
        resolution_m=item.resolution_m,
        status=item.status,  # type: ignore[arg-type]
        usage_status="idle",
        sample_count=item.sample_count,
        bbox_min_lon=item.bbox_min_lon,
        bbox_max_lon=item.bbox_max_lon,
        bbox_min_lat=item.bbox_min_lat,
        bbox_max_lat=item.bbox_max_lat,
        analysis_task_id=item.analysis_task_id,
        analysis_status=item.analysis_status,
        analysis_error_message=item.analysis_error_message,
        analysis_started_at=item.analysis_started_at,
        analysis_finished_at=item.analysis_finished_at,
        terrain_status=item.terrain_status,  # type: ignore[arg-type]
        terrain_task_id=item.terrain_task_id,
        terrain_error_message=item.terrain_error_message,
        terrain_root_path=item.terrain_root_path,
        terrain_url_template=item.terrain_url_template,
        terrain_min_zoom=item.terrain_min_zoom,
        terrain_max_zoom=item.terrain_max_zoom,
        terrain_bounds=item.terrain_bounds,
        terrain_metadata=item.terrain_metadata,
        notes=item.notes,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_elevation_datasets(
    db: Session,
) -> ElevationDatasetListResponse:
    """List elevation file records mapped to the legacy dataset format.

    The frontend still references the old /api/v1/elevation/datasets endpoint
    which expects ElevationDatasetSummary. This function bridges the gap by
    mapping ElevationFileRecord records to the dataset format.
    """
    stmt = select(ElevationFileRecord)
    total_stmt = select(func.count()).select_from(ElevationFileRecord)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(ElevationFileRecord.update_date.desc(), ElevationFileRecord.create_date.desc())
    ).scalars().all()
    return ElevationDatasetListResponse(
        items=[serialize_elevation_dataset(item) for item in items],
        total=total,
    )


def get_file_record_by_id(db: Session, record_id: str) -> ElevationFileRecord | None:
    return db.execute(
        select(ElevationFileRecord).where(ElevationFileRecord.id == record_id)
    ).scalar_one_or_none()


def create_file_record_from_upload(
    db: Session,
    file: UploadFile | None,
    payload: ElevationFileRecordCreateRequest,
    *,
    actor: User,
    content: bytes | None = None,
    filename: str | None = None,
) -> ElevationFileRecordUploadResponse:
    """Create a file record and upload the file in one operation. Supports ZIP files with automatic extraction.

    两段式上传兼容：可直接传 ``file``（单段式 multipart），也可传 ``content`` +
    ``filename``（先经 upload-temp 上传到临时区，再在确认提交时引用）。两种方式
    走同一条校验与入库链路。
    """
    if content is None:
        if file is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件，请提供 file 或 temp_file_id")
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")

        filename = file.filename.strip()

        # Read file content
        try:
            content = file.file.read()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"读取上传文件失败：{exc}"
            ) from exc
        finally:
            try:
                file.file.close()
            except Exception:
                pass

    if not filename or not filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件名不能为空")
    filename = filename.strip()
    file_ext = Path(filename).suffix.lower()

    if file_ext not in IMPORTABLE_ELEVATION_EXTENSIONS and file_ext not in IMPORTABLE_ARCHIVE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式: {file_ext}，仅支持 .tif/.zip"
        )

    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    # Determine mount and storage
    mount_code = _resolve_dataset_mount_code(db, requested_mount_code=payload.mount_code)
    mount = _require_mount(db, mount_code)
    driver = _build_driver_or_400(mount)

    # Handle ZIP file extraction
    if file_ext in IMPORTABLE_ARCHIVE_EXTENSIONS:
        return _create_file_records_from_zip(
            db=db,
            zip_content=content,
            zip_filename=filename,
            payload=payload,
            mount_code=mount_code,
            driver=driver,
            actor=actor,
        )

    # Handle single file upload
    file_format = ELEVATION_FILE_EXT_FORMAT_MAP.get(file_ext)
    if file_format is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式: {file_ext}"
        )

    _require_rasterio_available()

    file_size = len(content)

    # Generate unique storage path
    from uuid import uuid4
    record_id = uuid4().hex
    storage_dir = f"/elevation/records/{record_id[:2]}/{record_id[2:4]}"
    storage_path = join_virtual_path(storage_dir, filename)

    # Ensure directory exists and write file
    try:
        driver.ensure_directory(storage_dir)
        driver.write_file(
            storage_path,
            content=content,
            content_type=mimetypes.guess_type(filename)[0],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"文件存储失败: {exc}"
        ) from exc

    # Create database record
    now = utcnow()
    record = ElevationFileRecord(
        id=record_id,
        file_name=filename,
        file_path=storage_path,
        file_format=file_format,
        file_size=file_size,
        source=_normalize_str(payload.source),
        mount_code=mount_code,
        resolution_m=payload.resolution_m,
        status="active",
        terrain_status=_default_terrain_status_for_format(file_format),
        notes=_normalize_str(payload.notes),
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(record)
    db.commit()

    saved = get_file_record_by_id(db, record.id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文件记录创建失败"
        )

    _publish_elevation_change(
        "elevation.file_record.created",
        {"action": "file_record_created", "file_record_id": saved.id},
    )

    warnings: list[str] = []

    # Trigger analysis
    try:
        from ..tasks.elevation_tasks import analyze_elevation_file_record_job
        task = analyze_elevation_file_record_job.delay(saved.id, actor.id)
        saved.analysis_task_id = str(task.id)
        saved.analysis_status = "queued"
        saved.update_date = utcnow()
        db.commit()
    except Exception as exc:
        warnings.append(f"自动分析任务派发失败：{exc}")

    return ElevationFileRecordUploadResponse(
        record=serialize_file_record(saved),
        detail="文件已上传并创建记录",
        warnings=warnings,
    )


def _create_file_records_from_zip(
    db: Session,
    zip_content: bytes,
    zip_filename: str,
    payload: ElevationFileRecordCreateRequest,
    mount_code: str,
    driver: Any,
    actor: User,
) -> ElevationFileRecordUploadResponse:
    """Extract ZIP file and create file records for each contained elevation data file."""
    warnings: list[str] = []
    created_records: list[ElevationFileRecord] = []
    storage_failures: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue

                member_name = Path(member.filename).name
                if not member_name:
                    warnings.append(f"压缩包条目 {member.filename} 文件名无效，已跳过")
                    continue

                # 跳过 ASTER GDEM 质量图文件（_num.tif）
                if member_name.lower().endswith("_num.tif"):
                    warnings.append(f"压缩包条目 {member_name} 是质量图文件（_num.tif），已跳过")
                    continue

                suffix = Path(member_name).suffix.lower()
                if suffix not in IMPORTABLE_ELEVATION_EXTENSIONS:
                    warnings.append(f"压缩包条目 {member_name} 类型不支持，已跳过")
                    continue

                try:
                    data = archive.read(member)
                except Exception as exc:
                    warnings.append(f"压缩包条目 {member_name} 读取失败：{exc}")
                    continue

                if not data:
                    warnings.append(f"压缩包条目 {member_name} 内容为空，已跳过")
                    continue

                # Determine file format
                file_format = ELEVATION_FILE_EXT_FORMAT_MAP[suffix]

                file_size = len(data)

                # Generate unique storage path for each file
                from uuid import uuid4
                record_id = uuid4().hex
                storage_dir = f"/elevation/records/{record_id[:2]}/{record_id[2:4]}"
                storage_path = join_virtual_path(storage_dir, member_name)

                # Ensure directory exists and write file
                try:
                    driver.ensure_directory(storage_dir)
                    driver.write_file(
                        storage_path,
                        content=data,
                        content_type=mimetypes.guess_type(member_name)[0],
                    )
                except Exception as exc:
                    storage_failures.append(f"压缩包条目 {member_name} 存储失败: {exc}")
                    continue

                # Create database record
                now = utcnow()
                record = ElevationFileRecord(
                    id=record_id,
                    file_name=member_name,
                    file_path=storage_path,
                    file_format=file_format,
                    file_size=file_size,
                    source=_normalize_str(payload.source),
                    mount_code=mount_code,
                    resolution_m=payload.resolution_m,
                    status="active",
                    terrain_status=_default_terrain_status_for_format(file_format),
                    notes=_normalize_str(payload.notes),
                    create_date=now,
                    create_user=actor.id,
                    update_date=now,
                    update_user=actor.id,
                )
                db.add(record)
                created_records.append(record)

    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ZIP 文件损坏：{exc}"
        ) from exc

    if not created_records:
        if storage_failures:
            # ZIP contained valid elevation files but none could be stored
            # (e.g. S3 SignatureDoesNotMatch). Surface the storage reason up
            # front instead of the misleading "no valid elevation file found".
            detail = (
                "ZIP 中已找到合法高程数据文件，但全部存储失败，请检查存储后端配置"
                + "：" + "；".join(storage_failures[:10])
            )
            if len(storage_failures) > 10:
                detail += f"（共 {len(storage_failures)} 条存储失败，仅显示前 10 条）"
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=detail,
            )
        detail = "ZIP 文件中没有找到有效的高程数据文件"
        if warnings:
            detail += "：" + "；".join(warnings[:10])
            if len(warnings) > 10:
                detail += f"（共 {len(warnings)} 条警告，仅显示前 10 条）"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        )

    db.commit()

    # Publish events and trigger analysis for each record
    for record in created_records:
        _publish_elevation_change(
            "elevation.file_record.created",
            {"action": "file_record_created", "file_record_id": record.id},
        )

        try:
            from ..tasks.elevation_tasks import analyze_elevation_file_record_job
            task = analyze_elevation_file_record_job.delay(record.id, actor.id)
            record.analysis_task_id = str(task.id)
            record.analysis_status = "queued"
            record.update_date = utcnow()
        except Exception as exc:
            warnings.append(f"文件 {record.file_name} 自动分析任务派发失败：{exc}")

    db.commit()

    # Return summary of first record (for consistency with existing API)
    first_record = get_file_record_by_id(db, created_records[0].id)
    if not first_record:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文件记录创建失败"
        )

    detail = f"ZIP 文件已解压：成功创建 {len(created_records)} 个文件记录"
    if warnings:
        detail += f"，{len(warnings)} 个警告"

    return ElevationFileRecordUploadResponse(
        record=serialize_file_record(first_record),
        detail=detail,
        warnings=warnings,
    )


def update_file_record(
    db: Session,
    record_id: str,
    payload: ElevationFileRecordUpdateRequest,
    *,
    actor: User,
) -> ElevationFileRecordSummary | None:
    item = get_file_record_by_id(db, record_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "source" in update_data:
        item.source = _normalize_str(update_data["source"])
    if "resolution_m" in update_data:
        item.resolution_m = update_data["resolution_m"]
    if "status" in update_data and update_data["status"] is not None:
        item.status = str(update_data["status"]).strip().lower()
    if "notes" in update_data:
        item.notes = _normalize_str(update_data["notes"])
    if "terrain_url_template" in update_data:
        item.terrain_url_template = _normalize_str(update_data["terrain_url_template"])

    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_file_record_by_id(db, record_id)
    if not saved:
        return None

    _publish_elevation_change(
        "elevation.file_record.updated",
        {"action": "file_record_updated", "file_record_id": saved.id},
    )
    return serialize_file_record(saved)


def delete_file_record(db: Session, record_id: str) -> bool:
    item = get_file_record_by_id(db, record_id)
    if not item:
        return False

    # Check for running jobs
    running_job_count = int(
        db.scalar(
            select(func.count())
            .select_from(ElevationApplyJob)
            .where(
                ElevationApplyJob.file_record_id == record_id,
                ElevationApplyJob.status == "running",
            )
        )
        or 0
    )
    if running_job_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该文件存在 {running_job_count} 个运行中的回填任务，暂不能删除",
        )

    # Clean up stored files before deleting the record
    try:
        mount = _require_mount(db, item.mount_code)
        driver = _build_driver_or_400(mount)

        # 1. Delete the original DEM file from MinIO / storage
        if item.file_path:
            try:
                driver.delete_path(item.file_path, is_dir=False, recursive=False)
            except Exception:
                pass  # ignore if file already gone

        # 2. Delete the generated terrain tiles from shared volume
        terrain_dir = _resolve_file_record_terrain_dir(record_id)
        _delete_virtual_directory_if_exists(driver, terrain_dir)
    except Exception:
        pass  # Best-effort cleanup; don't block record deletion

    # Delete associated jobs
    from sqlalchemy import delete as sql_delete
    db.execute(sql_delete(ElevationApplyJob).where(ElevationApplyJob.file_record_id == record_id))

    # Delete the record
    db.delete(item)
    db.commit()

    _publish_elevation_change(
        "elevation.file_record.deleted",
        {"action": "file_record_deleted", "file_record_id": record_id},
    )
    return True


def queue_file_record_analysis(
    db: Session,
    *,
    record_id: str,
    actor: User,
) -> ElevationFileRecordAnalyzeResponse:
    item = get_file_record_by_id(db, record_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件记录未启用")

    if item.analysis_status in {"queued", "running"}:
        return ElevationFileRecordAnalyzeResponse(
            record=serialize_file_record(item),
            task_id=item.analysis_task_id,
            queued=False,
            detail="分析任务已存在，无需重复提交。",
            warnings=[],
        )

    item.analysis_status = "queued"
    item.analysis_error_message = None
    item.analysis_started_at = None
    item.analysis_finished_at = None
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    try:
        from ..tasks.elevation_tasks import analyze_elevation_file_record_job
        task = analyze_elevation_file_record_job.delay(item.id, actor.id)
    except Exception as exc:
        item.analysis_status = "failed"
        item.analysis_error_message = str(exc)
        item.analysis_finished_at = utcnow()
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析任务派发失败: {exc}"
        ) from exc

    item.analysis_task_id = str(task.id)
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_file_record_by_id(db, record_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文件记录分析任务保存失败"
        )

    _publish_elevation_change(
        "elevation.file_record.analysis.queued",
        {"action": "file_record_analysis_queued", "file_record_id": saved.id, "task_id": saved.analysis_task_id},
    )
    return ElevationFileRecordAnalyzeResponse(
        record=serialize_file_record(saved),
        task_id=saved.analysis_task_id,
        queued=True,
        detail="分析任务已提交，等待执行。",
        warnings=[],
    )


def queue_file_record_terrain_build(
    db: Session,
    *,
    record_id: str,
    actor: User,
) -> ElevationFileRecordTerrainBuildResponse:
    item = get_file_record_by_id(db, record_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件记录未启用")

    # Check if format supports terrain
    if item.file_format not in TERRAIN_SUPPORTED_DATASET_FORMATS:
        item.terrain_status = "not_supported"
        item.terrain_task_id = None
        item.terrain_error_message = None
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前文件格式不支持地形瓦片生成"
        )

    if item.terrain_status == "processing" or (item.terrain_status == "pending" and item.terrain_task_id):
        return ElevationFileRecordTerrainBuildResponse(
            record=serialize_file_record(item),
            task_id=item.terrain_task_id,
            queued=False,
            detail="地形瓦片任务已存在，无需重复提交。",
            warnings=[],
        )

    item.terrain_status = "pending"
    item.terrain_error_message = None
    item.terrain_root_path = None
    item.terrain_url_template = None
    item.terrain_min_zoom = None
    item.terrain_max_zoom = None
    item.terrain_bounds = None
    item.terrain_metadata = None
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    try:
        from ..tasks.elevation_tasks import build_elevation_file_record_terrain_job
        task = build_elevation_file_record_terrain_job.delay(item.id, actor.id)
    except Exception as exc:
        item.terrain_status = "failed"
        item.terrain_error_message = str(exc)
        item.terrain_task_id = None
        item.update_user = actor.id
        item.update_date = utcnow()
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"地形瓦片任务派发失败: {exc}"
        ) from exc

    item.terrain_task_id = str(task.id)
    item.update_user = actor.id
    item.update_date = utcnow()
    db.commit()

    saved = get_file_record_by_id(db, record_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="地形瓦片任务保存失败"
        )

    _publish_elevation_change(
        "elevation.file_record.terrain.queued",
        {"action": "file_record_terrain_queued", "file_record_id": saved.id, "task_id": saved.terrain_task_id},
    )
    return ElevationFileRecordTerrainBuildResponse(
        record=serialize_file_record(saved),
        task_id=saved.terrain_task_id,
        queued=True,
        detail="地形瓦片任务已提交，等待执行。",
        warnings=[],
    )


def preview_file_record(
    db: Session,
    *,
    record_id: str,
    max_points: int,
) -> ElevationFileRecordPreviewResponse:
    item = get_file_record_by_id(db, record_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件记录不存在")
    if item.status != "active":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件记录未启用")

    preview_limit = max(1, min(max_points, 5000))
    file_format = item.file_format

    if file_format in RASTER_FILE_FORMATS:
        result = _build_raster_preview(db, record=item, limit=preview_limit)

        return ElevationFileRecordPreviewResponse(
            record=serialize_file_record(item),
            preview_mode=result.preview_mode,
            total_points=result.total_points,
            sampled_points=result.sampled_points,
            points=result.points,
            cells=result.cells,
            diagnostics=result.diagnostics,
            warnings=result.warnings,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"不支持的文件格式: {file_format}",
    )
