from __future__ import annotations

import asyncio
import mimetypes
import zipfile
from datetime import datetime
from io import BytesIO

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, joinedload

from ..models.base import utcnow
from ..models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from ..models.user import User
from ..schemas.file_storage import (
    FileBreadcrumbItem,
    FileCreateDirectoryRequest,
    FileDeleteRequest,
    FileEntryPublic,
    FileListResponse,
    FileMoveRequest,
    FileOperationResponse,
    FileRenameRequest,
    FileStorageBackendPublic,
    FileStorageMountPublic,
)
from .audit_service import compose_audit_detail, write_audit_log
from .push_service import publish_topic
from .storage_driver import (
    StorageDriverError,
    StorageInvalidPathError,
    StorageNotConfiguredError,
    StorageObject,
    StoragePathNotFoundError,
    build_storage_driver,
    join_virtual_path,
    normalize_virtual_path,
)

FILES_TOPIC = "admin.files"
FILES_REFETCH_ENDPOINT = "/api/v1/admin/files"


def list_files(
    db: Session,
    *,
    actor: User,
    mount_code: str | None,
    path: str | None,
) -> FileListResponse:
    mounts = list_enabled_mounts(db)
    if not mounts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No enabled file mount found")

    current_mount = _pick_mount(mounts, mount_code)
    try:
        normalized_path = normalize_virtual_path(path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    driver = _build_driver_or_400(current_mount)

    try:
        entries = driver.list_dir(normalized_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    synced_at = _sync_directory_index(
        db,
        mount=current_mount,
        parent_path=normalized_path,
        objects=entries,
        actor=actor,
    )
    db.commit()

    index_entries = db.execute(
        select(FileIndexEntry)
        .where(and_(FileIndexEntry.mount_id == current_mount.id, FileIndexEntry.parent_path == normalized_path))
        .order_by(FileIndexEntry.is_dir.desc(), FileIndexEntry.name.asc())
    ).scalars().all()

    return FileListResponse(
        mounts=[serialize_mount(item) for item in mounts],
        current_mount=serialize_mount(current_mount),
        current_path=normalized_path,
        breadcrumbs=build_breadcrumbs(normalized_path),
        items=[serialize_index_entry(item) for item in index_entries],
        total=len(index_entries),
        synced_at=synced_at,
    )


def create_directory(
    db: Session,
    payload: FileCreateDirectoryRequest,
    *,
    actor: User,
) -> FileOperationResponse:
    mount = _require_mount(db, payload.mount_code)
    driver = _build_driver_or_400(mount)

    try:
        parent_path = normalize_virtual_path(payload.parent_path)
        target_path = join_virtual_path(parent_path, payload.name)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        driver.ensure_directory(target_path)
        entries = driver.list_dir(parent_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    _sync_directory_index(
        db,
        mount=mount,
        parent_path=parent_path,
        objects=entries,
        actor=actor,
    )
    write_audit_log(
        db,
        action="file.mkdir",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"mount_code={mount.code}",
            f"path={target_path}",
            f"parent_path={parent_path}",
        ),
    )
    db.commit()
    _notify_files_changed(action="created_directory", mount_code=mount.code, path=target_path)

    return FileOperationResponse(success=True, mount_code=mount.code, path=target_path, action="created_directory")


def delete_file_path(
    db: Session,
    payload: FileDeleteRequest,
    *,
    actor: User,
) -> FileOperationResponse:
    mount = _require_mount(db, payload.mount_code)
    driver = _build_driver_or_400(mount)

    try:
        target_path = normalize_virtual_path(payload.path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if target_path == "/":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Root path cannot be deleted")

    try:
        driver.delete_path(target_path, is_dir=payload.is_dir, recursive=payload.recursive)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    _delete_index_by_path(db, mount_id=mount.id, target_path=target_path)

    parent_path = _get_parent_path(target_path)
    try:
        parent_entries = driver.list_dir(parent_path)
    except StorageDriverError:
        parent_entries = []

    _sync_directory_index(
        db,
        mount=mount,
        parent_path=parent_path,
        objects=parent_entries,
        actor=actor,
    )
    write_audit_log(
        db,
        action="file.delete",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"mount_code={mount.code}",
            f"path={target_path}",
            f"is_dir={str(payload.is_dir).lower()}",
            f"recursive={str(payload.recursive).lower()}",
        ),
    )
    db.commit()
    _notify_files_changed(action="deleted_path", mount_code=mount.code, path=target_path)

    return FileOperationResponse(success=True, mount_code=mount.code, path=target_path, action="deleted_path")


def rename_file_path(
    db: Session,
    payload: FileRenameRequest,
    *,
    actor: User,
) -> FileOperationResponse:
    mount = _require_mount(db, payload.mount_code)
    driver = _build_driver_or_400(mount)

    try:
        source_path = normalize_virtual_path(payload.path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if source_path == "/":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Root path cannot be renamed")

    try:
        target_path = driver.rename_path(source_path, is_dir=payload.is_dir, new_name=payload.new_name)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    _delete_index_by_path(db, mount_id=mount.id, target_path=source_path)

    parent_paths = {
        _get_parent_path(source_path),
        _get_parent_path(target_path),
    }
    for parent_path in parent_paths:
        try:
            parent_entries = driver.list_dir(parent_path)
        except StorageDriverError:
            parent_entries = []
        _sync_directory_index(
            db,
            mount=mount,
            parent_path=parent_path,
            objects=parent_entries,
            actor=actor,
        )

    write_audit_log(
        db,
        action="file.rename",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"mount_code={mount.code}",
            f"source_path={source_path}",
            f"target_path={target_path}",
            f"is_dir={str(payload.is_dir).lower()}",
        ),
    )
    db.commit()
    _notify_files_changed(action="renamed_path", mount_code=mount.code, path=target_path)
    return FileOperationResponse(
        success=True,
        mount_code=mount.code,
        path=source_path,
        action="renamed_path",
        target_path=target_path,
    )


def move_file_path(
    db: Session,
    payload: FileMoveRequest,
    *,
    actor: User,
) -> FileOperationResponse:
    mount = _require_mount(db, payload.mount_code)
    driver = _build_driver_or_400(mount)

    try:
        source_path = normalize_virtual_path(payload.path)
        target_parent_path = normalize_virtual_path(payload.target_parent_path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if source_path == "/":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Root path cannot be moved")

    new_name = payload.new_name.strip() if isinstance(payload.new_name, str) else None

    try:
        target_path = driver.move_path(
            source_path,
            is_dir=payload.is_dir,
            target_parent_path=target_parent_path,
            new_name=new_name,
        )
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    _delete_index_by_path(db, mount_id=mount.id, target_path=source_path)

    parent_paths = {
        _get_parent_path(source_path),
        _get_parent_path(target_path),
    }
    for parent_path in parent_paths:
        try:
            parent_entries = driver.list_dir(parent_path)
        except StorageDriverError:
            parent_entries = []
        _sync_directory_index(
            db,
            mount=mount,
            parent_path=parent_path,
            objects=parent_entries,
            actor=actor,
        )

    write_audit_log(
        db,
        action="file.move",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"mount_code={mount.code}",
            f"source_path={source_path}",
            f"target_path={target_path}",
            f"is_dir={str(payload.is_dir).lower()}",
        ),
    )
    db.commit()
    _notify_files_changed(action="moved_path", mount_code=mount.code, path=target_path)
    return FileOperationResponse(
        success=True,
        mount_code=mount.code,
        path=source_path,
        action="moved_path",
        target_path=target_path,
    )


def upload_file_to_path(
    db: Session,
    *,
    mount_code: str,
    parent_path: str,
    file: UploadFile,
    actor: User,
) -> FileOperationResponse:
    mount = _require_mount(db, mount_code)
    driver = _build_driver_or_400(mount)

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name is required")

    try:
        normalized_parent = normalize_virtual_path(parent_path)
        target_path = join_virtual_path(normalized_parent, filename)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        content = file.file.read()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Read upload failed: {exc}") from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    content_type = file.content_type or mimetypes.guess_type(filename)[0]

    try:
        driver.write_file(target_path, content=content, content_type=content_type)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        parent_entries = driver.list_dir(normalized_parent)
    except StorageDriverError:
        parent_entries = []

    _sync_directory_index(
        db,
        mount=mount,
        parent_path=normalized_parent,
        objects=parent_entries,
        actor=actor,
    )
    write_audit_log(
        db,
        action="file.upload",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"mount_code={mount.code}",
            f"path={target_path}",
            f"content_type={content_type or 'application/octet-stream'}",
            f"size={len(content)}",
        ),
    )
    db.commit()

    _notify_files_changed(action="uploaded_file", mount_code=mount.code, path=target_path)
    return FileOperationResponse(
        success=True,
        mount_code=mount.code,
        path=target_path,
        action="uploaded_file",
    )


def download_file_from_path(
    db: Session,
    *,
    mount_code: str,
    path: str,
    actor: User | None = None,
) -> tuple[str, bytes, str | None]:
    mount = _require_mount(db, mount_code)
    driver = _build_driver_or_400(mount)

    try:
        normalized_path = normalize_virtual_path(path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        result = driver.read_file(normalized_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if actor is not None:
        write_audit_log(
            db,
            action="file.download",
            actor_user_id=actor.id,
            detail=compose_audit_detail(
                f"mount_code={mount.code}",
                f"path={normalized_path}",
                f"filename={result.name}",
            ),
        )
        db.commit()

    return result.name, result.content, result.mime_type


def download_directory_as_zip(
    db: Session,
    *,
    mount_code: str,
    path: str,
    actor: User | None = None,
) -> tuple[str, bytes, str]:
    mount = _require_mount(db, mount_code)
    driver = _build_driver_or_400(mount)

    try:
        normalized_path = normalize_virtual_path(path)
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        root_entries = driver.list_dir(normalized_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StorageInvalidPathError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    folder_name = normalized_path.strip("/").split("/")[-1] if normalized_path != "/" else "root"
    safe_folder_name = folder_name or "root"
    zip_filename = f"{safe_folder_name}.zip"

    buffer = BytesIO()
    try:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            stack: list[tuple[str, str, list[StorageObject] | None]] = [(normalized_path, "", root_entries)]
            while stack:
                current_path, relative_prefix, prefetched = stack.pop()
                entries = prefetched if prefetched is not None else driver.list_dir(current_path)
                for entry in entries:
                    relative_name = f"{relative_prefix}{entry.name}"
                    if entry.is_dir:
                        stack.append((entry.path, f"{relative_name}/", None))
                        continue
                    try:
                        read_result = driver.read_file(entry.path)
                    except StoragePathNotFoundError as exc:
                        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
                    except StorageInvalidPathError as exc:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
                    except StorageDriverError as exc:
                        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
                    archive.writestr(relative_name, read_result.content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Create zip archive failed: {exc}",
        ) from exc

    if actor is not None:
        write_audit_log(
            db,
            action="file.download_zip",
            actor_user_id=actor.id,
            detail=compose_audit_detail(
                f"mount_code={mount.code}",
                f"path={normalized_path}",
                f"filename={zip_filename}",
            ),
        )
        db.commit()

    return zip_filename, buffer.getvalue(), "application/zip"


def list_enabled_mounts(db: Session) -> list[FileStorageMount]:
    stmt = (
        select(FileStorageMount)
        .join(FileStorageMount.backend)
        .options(joinedload(FileStorageMount.backend))
        .where(
            and_(
                FileStorageMount.is_enabled.is_(True),
                FileStorageBackend.status == "enabled",
            )
        )
        .order_by(FileStorageBackend.is_default.desc(), FileStorageMount.id.asc())
    )
    return db.execute(stmt).scalars().all()


def _pick_mount(mounts: list[FileStorageMount], mount_code: str | None) -> FileStorageMount:
    if not mount_code:
        return mounts[0]
    for mount in mounts:
        if mount.code == mount_code:
            return mount
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Mount not found: {mount_code}")


def _require_mount(db: Session, mount_code: str) -> FileStorageMount:
    mounts = list_enabled_mounts(db)
    return _pick_mount(mounts, mount_code)


def _build_driver_or_400(mount: FileStorageMount):
    try:
        return build_storage_driver(mount.backend, mount)
    except StorageNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _sync_directory_index(
    db: Session,
    *,
    mount: FileStorageMount,
    parent_path: str,
    objects: list[StorageObject],
    actor: User,
) -> datetime:
    normalized_parent = normalize_virtual_path(parent_path)
    synced_at = utcnow()

    existing_entries = db.execute(
        select(FileIndexEntry)
        .where(and_(FileIndexEntry.mount_id == mount.id, FileIndexEntry.parent_path == normalized_parent))
    ).scalars().all()
    existing_by_path = {item.path: item for item in existing_entries}
    incoming_paths = {item.path for item in objects}

    stale_paths = [path for path in existing_by_path if path not in incoming_paths]
    for stale_path in stale_paths:
        _delete_index_by_path(db, mount_id=mount.id, target_path=stale_path)

    for item in objects:
        record = existing_by_path.get(item.path)
        if not record:
            record = FileIndexEntry(
                mount_id=mount.id,
                path=item.path,
                parent_path=normalized_parent,
                name=item.name,
                is_dir=item.is_dir,
            )
            db.add(record)

        record.parent_path = normalized_parent
        record.name = item.name
        record.is_dir = item.is_dir
        record.size = max(0, int(item.size))
        record.mime_type = item.mime_type
        record.etag = item.etag
        record.storage_key = item.storage_key
        record.modified_at = item.modified_at
        record.synced_at = synced_at
        record.last_synced_by_user_id = actor.id

    db.flush()
    return synced_at


def _delete_index_by_path(db: Session, *, mount_id: int, target_path: str) -> None:
    normalized = normalize_virtual_path(target_path)
    prefix = f"{normalized.rstrip('/')}/%"
    db.execute(
        delete(FileIndexEntry).where(
            and_(
                FileIndexEntry.mount_id == mount_id,
                or_(
                    FileIndexEntry.path == normalized,
                    FileIndexEntry.path.like(prefix),
                    FileIndexEntry.parent_path == normalized,
                ),
            )
        )
    )


def build_breadcrumbs(path: str) -> list[FileBreadcrumbItem]:
    normalized = normalize_virtual_path(path)
    breadcrumbs = [FileBreadcrumbItem(name="根目录", path="/")]
    if normalized == "/":
        return breadcrumbs

    current = ""
    for segment in normalized.strip("/").split("/"):
        current = f"{current}/{segment}"
        breadcrumbs.append(FileBreadcrumbItem(name=segment, path=current))
    return breadcrumbs


def serialize_mount(mount: FileStorageMount) -> FileStorageMountPublic:
    return FileStorageMountPublic(
        id=mount.id,
        code=mount.code,
        name=mount.name,
        mount_path=mount.mount_path,
        root_path=mount.root_path,
        is_enabled=mount.is_enabled,
        backend=serialize_backend(mount.backend),
    )


def serialize_backend(backend: FileStorageBackend) -> FileStorageBackendPublic:
    driver_type = backend.driver_type.strip().upper()
    config = backend.config_json if isinstance(backend.config_json, dict) else {}
    config_summary: dict[str, str] = {}

    if driver_type == "VFS":
        root_dir = config.get("root_dir")
        if isinstance(root_dir, str):
            config_summary["root_dir"] = root_dir
    elif driver_type == "S3":
        for field in ["bucket", "region_name", "endpoint_url"]:
            value = config.get(field)
            if isinstance(value, str) and value.strip():
                config_summary[field] = value.strip()

    normalized_driver_type = "S3" if driver_type == "S3" else "VFS"

    return FileStorageBackendPublic(
        id=backend.id,
        code=backend.code,
        name=backend.name,
        driver_type=normalized_driver_type,
        status=backend.status,
        is_default=backend.is_default,
        config_summary=config_summary,
    )


def serialize_index_entry(entry: FileIndexEntry) -> FileEntryPublic:
    return FileEntryPublic(
        id=entry.id,
        path=entry.path,
        parent_path=entry.parent_path,
        name=entry.name,
        is_dir=entry.is_dir,
        size=entry.size,
        mime_type=entry.mime_type,
        etag=entry.etag,
        storage_key=entry.storage_key,
        modified_at=entry.modified_at,
        synced_at=entry.synced_at,
    )


def _get_parent_path(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return "/"
    parent = normalized.rsplit("/", 1)[0]
    return parent if parent else "/"


def _notify_files_changed(*, action: str, mount_code: str, path: str) -> None:
    _fire_and_forget(
        publish_topic(
            FILES_TOPIC,
            name="files.changed",
            payload={"action": action, "mount_code": mount_code, "path": path},
            requires_refetch=[FILES_REFETCH_ENDPOINT],
            dedupe_key=f"files:{action}:{mount_code}:{path}",
        )
    )


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)
