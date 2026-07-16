from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..models.file_storage import FileStorageBackend, FileStorageMount


class StorageDriverError(RuntimeError):
    pass


class StoragePathNotFoundError(StorageDriverError):
    pass


class StorageInvalidPathError(StorageDriverError):
    pass


class StorageNotConfiguredError(StorageDriverError):
    pass


@dataclass(slots=True)
class StorageObject:
    path: str
    parent_path: str
    name: str
    is_dir: bool
    size: int = 0
    modified_at: datetime | None = None
    mime_type: str | None = None
    etag: str | None = None
    storage_key: str | None = None


@dataclass(slots=True)
class StorageReadResult:
    path: str
    name: str
    content: bytes
    mime_type: str | None = None


class StorageDriver(Protocol):
    def list_dir(self, path: str) -> list[StorageObject]:
        ...

    def ensure_directory(self, path: str) -> None:
        ...

    def delete_path(self, path: str, *, is_dir: bool, recursive: bool) -> None:
        ...

    def rename_path(self, path: str, *, is_dir: bool, new_name: str) -> str:
        ...

    def move_path(self, path: str, *, is_dir: bool, target_parent_path: str, new_name: str | None) -> str:
        ...

    def write_file(self, path: str, *, content: bytes, content_type: str | None = None) -> StorageObject:
        ...

    def read_file(self, path: str) -> StorageReadResult:
        ...


def normalize_virtual_path(path: str | None) -> str:
    raw = (path or "/").strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = f"/{raw}"

    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise StorageInvalidPathError("Parent traversal is not allowed")
        parts.append(part)

    return f"/{'/'.join(parts)}" if parts else "/"


def join_virtual_path(parent_path: str, name: str) -> str:
    normalized_parent = normalize_virtual_path(parent_path)
    normalized_name = name.strip().strip("/")
    if not normalized_name:
        raise StorageInvalidPathError("Name cannot be empty")
    if "/" in normalized_name or normalized_name in {".", ".."}:
        raise StorageInvalidPathError("Invalid directory or file name")
    if normalized_parent == "/":
        return f"/{normalized_name}"
    return f"{normalized_parent}/{normalized_name}"


def build_storage_driver(backend: FileStorageBackend, mount: FileStorageMount) -> StorageDriver:
    driver_type = backend.driver_type.strip().upper()
    config = backend.config_json if isinstance(backend.config_json, dict) else {}

    if driver_type == "VFS":
        root_dir = _coerce_non_empty_string(config.get("root_dir"))
        if not root_dir:
            raise StorageNotConfiguredError("VFS backend requires config.root_dir")
        return VfsStorageDriver(root_dir=root_dir, mount_root_path=mount.root_path)
    if driver_type == "S3":
        return S3StorageDriver(config=config, mount_root_path=mount.root_path)

    raise StorageNotConfiguredError(f"Unsupported storage driver type: {backend.driver_type}")


class VfsStorageDriver:
    def __init__(self, *, root_dir: str, mount_root_path: str) -> None:
        base_root = Path(root_dir).expanduser().resolve()
        mount_root = normalize_virtual_path(mount_root_path)
        full_root = (base_root / mount_root.lstrip("/")).resolve()
        full_root.mkdir(parents=True, exist_ok=True)

        self._base_root = base_root
        self._root = full_root

    def list_dir(self, path: str) -> list[StorageObject]:
        normalized = normalize_virtual_path(path)
        target = self._resolve_target(normalized)
        if not target.exists():
            raise StoragePathNotFoundError(f"Path not found: {normalized}")
        if not target.is_dir():
            raise StorageInvalidPathError(f"Path is not a directory: {normalized}")

        children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        result: list[StorageObject] = []
        for child in children:
            stat_info = child.stat()
            child_path = self._to_virtual_path(child)
            modified_at = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)
            mime_type = None if child.is_dir() else mimetypes.guess_type(child.name)[0]
            result.append(
                StorageObject(
                    path=child_path,
                    parent_path=normalized,
                    name=child.name,
                    is_dir=child.is_dir(),
                    size=0 if child.is_dir() else int(stat_info.st_size),
                    modified_at=modified_at,
                    mime_type=mime_type,
                    storage_key=child_path.lstrip("/"),
                )
            )
        return result

    def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        target = self._resolve_target(normalized)
        target.mkdir(parents=True, exist_ok=True)

    def delete_path(self, path: str, *, is_dir: bool, recursive: bool) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            raise StorageInvalidPathError("Root path cannot be deleted")

        target = self._resolve_target(normalized)
        if not target.exists():
            raise StoragePathNotFoundError(f"Path not found: {normalized}")

        if is_dir:
            if not target.is_dir():
                raise StorageInvalidPathError(f"Path is not a directory: {normalized}")
            if recursive:
                shutil.rmtree(target)
                return
            target.rmdir()
            return

        if target.is_dir():
            raise StorageInvalidPathError(f"Path is a directory: {normalized}")
        target.unlink()

    def rename_path(self, path: str, *, is_dir: bool, new_name: str) -> str:
        source = normalize_virtual_path(path)
        if source == "/":
            raise StorageInvalidPathError("Root path cannot be renamed")

        parent_path = _parent_virtual_path(source)
        target_path = join_virtual_path(parent_path, new_name)
        if target_path == source:
            return source

        source_target = self._resolve_target(source)
        if not source_target.exists():
            raise StoragePathNotFoundError(f"Path not found: {source}")
        if is_dir and not source_target.is_dir():
            raise StorageInvalidPathError(f"Path is not a directory: {source}")
        if not is_dir and source_target.is_dir():
            raise StorageInvalidPathError(f"Path is a directory: {source}")

        target_target = self._resolve_target(target_path)
        if target_target.exists():
            raise StorageDriverError(f"Path already exists: {target_path}")

        source_target.rename(target_target)
        return target_path

    def move_path(self, path: str, *, is_dir: bool, target_parent_path: str, new_name: str | None) -> str:
        source = normalize_virtual_path(path)
        if source == "/":
            raise StorageInvalidPathError("Root path cannot be moved")

        source_name = _basename_virtual_path(source)
        target_name = (new_name or source_name).strip()
        target_path = join_virtual_path(target_parent_path, target_name)
        if target_path == source:
            return source

        if is_dir and target_path.startswith(f"{source.rstrip('/')}/"):
            raise StorageInvalidPathError("Directory cannot be moved into itself")

        source_target = self._resolve_target(source)
        if not source_target.exists():
            raise StoragePathNotFoundError(f"Path not found: {source}")
        if is_dir and not source_target.is_dir():
            raise StorageInvalidPathError(f"Path is not a directory: {source}")
        if not is_dir and source_target.is_dir():
            raise StorageInvalidPathError(f"Path is a directory: {source}")

        parent_target = self._resolve_target(normalize_virtual_path(target_parent_path))
        if not parent_target.exists() or not parent_target.is_dir():
            raise StoragePathNotFoundError(f"Path not found: {normalize_virtual_path(target_parent_path)}")

        target_target = self._resolve_target(target_path)
        if target_target.exists():
            raise StorageDriverError(f"Path already exists: {target_path}")

        source_target.rename(target_target)
        return target_path

    def write_file(self, path: str, *, content: bytes, content_type: str | None = None) -> StorageObject:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            raise StorageInvalidPathError("Cannot write content to root path")

        parent_path = _parent_virtual_path(normalized)
        parent_target = self._resolve_target(parent_path)
        if not parent_target.exists() or not parent_target.is_dir():
            raise StoragePathNotFoundError(f"Path not found: {parent_path}")

        target = self._resolve_target(normalized)
        if target.exists() and target.is_dir():
            raise StorageInvalidPathError(f"Path is a directory: {normalized}")

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            output.write(content)

        stat_info = target.stat()
        modified_at = datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc)

        return StorageObject(
            path=normalized,
            parent_path=parent_path,
            name=target.name,
            is_dir=False,
            size=int(stat_info.st_size),
            modified_at=modified_at,
            mime_type=content_type or mimetypes.guess_type(target.name)[0],
            storage_key=normalized.lstrip("/"),
        )

    def read_file(self, path: str) -> StorageReadResult:
        normalized = normalize_virtual_path(path)
        target = self._resolve_target(normalized)
        if not target.exists():
            raise StoragePathNotFoundError(f"Path not found: {normalized}")
        if target.is_dir():
            raise StorageInvalidPathError(f"Path is a directory: {normalized}")

        content = target.read_bytes()
        return StorageReadResult(
            path=normalized,
            name=target.name,
            content=content,
            mime_type=mimetypes.guess_type(target.name)[0],
        )

    def _resolve_target(self, normalized_path: str) -> Path:
        candidate = (self._root / normalized_path.lstrip("/")).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageInvalidPathError("Resolved path escaped mount root")
        return candidate

    def _to_virtual_path(self, absolute_path: Path) -> str:
        relative = absolute_path.resolve().relative_to(self._root).as_posix()
        return f"/{relative}" if relative else "/"


class S3StorageDriver:
    def __init__(self, *, config: dict[str, Any], mount_root_path: str) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise StorageNotConfiguredError("S3 driver requires boto3 dependency") from exc

        bucket = _coerce_non_empty_string(config.get("bucket"))
        if not bucket:
            raise StorageNotConfiguredError("S3 backend requires config.bucket")

        client_config = Config(
            connect_timeout=_coerce_positive_number(config.get("connect_timeout_seconds"), default=3.0),
            read_timeout=_coerce_positive_number(config.get("read_timeout_seconds"), default=10.0),
            retries={"max_attempts": int(_coerce_positive_number(config.get("max_attempts"), default=2.0))},
            s3={"addressing_style": _coerce_non_empty_string(config.get("addressing_style")) or "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )

        session = boto3.session.Session(
            aws_access_key_id=_coerce_non_empty_string(config.get("access_key_id")),
            aws_secret_access_key=_coerce_non_empty_string(config.get("secret_access_key")),
            aws_session_token=_coerce_non_empty_string(config.get("session_token")),
            region_name=_coerce_non_empty_string(config.get("region_name")),
        )
        self._client = session.client(
            "s3",
            endpoint_url=_coerce_non_empty_string(config.get("endpoint_url")),
            region_name=_coerce_non_empty_string(config.get("region_name")),
            config=client_config,
        )
        self._bucket = bucket
        self._root_prefix = _normalize_s3_prefix(mount_root_path)
        self._should_write_directory_markers = bool(config.get("write_directory_markers", False))

    def list_dir(self, path: str) -> list[StorageObject]:
        normalized = normalize_virtual_path(path)
        prefix = self._key_prefix_for_dir(normalized)

        items: list[StorageObject] = []
        seen_paths: set[str] = set()

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self._bucket,
                Prefix=prefix,
                Delimiter="/",
            )
            for page in pages:
                for common_prefix in page.get("CommonPrefixes", []):
                    directory_key = str(common_prefix.get("Prefix", ""))
                    remainder = self._relative_to_parent(directory_key, normalized)
                    if not remainder:
                        continue
                    name = remainder.split("/", 1)[0]
                    if not name:
                        continue
                    directory_path = join_virtual_path(normalized, name)
                    if directory_path in seen_paths:
                        continue
                    seen_paths.add(directory_path)
                    items.append(
                        StorageObject(
                            path=directory_path,
                            parent_path=normalized,
                            name=name,
                            is_dir=True,
                            size=0,
                            storage_key=directory_key,
                        )
                    )

                for content in page.get("Contents", []):
                    key = str(content.get("Key", ""))
                    if key == prefix:
                        continue
                    remainder = self._relative_to_parent(key, normalized)
                    if not remainder:
                        continue
                    if "/" in remainder:
                        continue
                    child_path = join_virtual_path(normalized, remainder)
                    if child_path in seen_paths:
                        continue

                    is_dir = key.endswith("/")
                    seen_paths.add(child_path)
                    items.append(
                        StorageObject(
                            path=child_path,
                            parent_path=normalized,
                            name=remainder,
                            is_dir=is_dir,
                            size=0 if is_dir else int(content.get("Size", 0)),
                            modified_at=content.get("LastModified"),
                            etag=str(content.get("ETag", "")).strip('"') or None,
                            mime_type=mimetypes.guess_type(child_path)[0] if not is_dir else None,
                            storage_key=key,
                        )
                    )
        except Exception as exc:  # pragma: no cover - provider specific errors
            if _is_s3_not_found(exc):
                raise StoragePathNotFoundError(f"Path not found: {normalized}") from exc
            raise StorageDriverError(f"S3 list failed: {exc}") from exc

        items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        return items

    def ensure_directory(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            return

        # S3-compatible object stores do not require directory marker objects
        # before nested keys are written. The marker PUT is optional and is
        # expensive on high-file-count uploads.
        if not self._should_write_directory_markers:
            return

        key = self._key_for_path(normalized)
        if key and not key.endswith("/"):
            key = f"{key}/"
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=b"")
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 create directory failed: {exc}") from exc

    def delete_path(self, path: str, *, is_dir: bool, recursive: bool) -> None:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            raise StorageInvalidPathError("Root path cannot be deleted")

        if is_dir:
            self._delete_directory(normalized, recursive=recursive)
            return
        self._delete_object(normalized)

    def rename_path(self, path: str, *, is_dir: bool, new_name: str) -> str:
        source = normalize_virtual_path(path)
        if source == "/":
            raise StorageInvalidPathError("Root path cannot be renamed")
        parent = _parent_virtual_path(source)
        return self.move_path(
            source,
            is_dir=is_dir,
            target_parent_path=parent,
            new_name=new_name,
        )

    def move_path(self, path: str, *, is_dir: bool, target_parent_path: str, new_name: str | None) -> str:
        source = normalize_virtual_path(path)
        if source == "/":
            raise StorageInvalidPathError("Root path cannot be moved")

        target_parent = normalize_virtual_path(target_parent_path)
        source_name = _basename_virtual_path(source)
        target_name = (new_name or source_name).strip()
        target_path = join_virtual_path(target_parent, target_name)

        if target_path == source:
            return source
        if is_dir and target_path.startswith(f"{source.rstrip('/')}/"):
            raise StorageInvalidPathError("Directory cannot be moved into itself")

        if is_dir:
            self._move_directory(source, target_path)
        else:
            self._move_object(source, target_path)

        return target_path

    def write_file(self, path: str, *, content: bytes, content_type: str | None = None) -> StorageObject:
        normalized = normalize_virtual_path(path)
        if normalized == "/":
            raise StorageInvalidPathError("Cannot write content to root path")

        key = self._key_for_path(normalized)
        if not key:
            raise StorageInvalidPathError("Cannot write content to root path")
        if key.endswith("/"):
            raise StorageInvalidPathError(f"Path is a directory: {normalized}")

        put_kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": content,
        }
        if content_type:
            put_kwargs["ContentType"] = content_type

        try:
            self._client.put_object(**put_kwargs)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 upload failed: {exc}") from exc

        return StorageObject(
            path=normalized,
            parent_path=_parent_virtual_path(normalized),
            name=_basename_virtual_path(normalized),
            is_dir=False,
            size=len(content),
            mime_type=content_type or mimetypes.guess_type(normalized)[0],
            storage_key=key,
        )

    def read_file(self, path: str) -> StorageReadResult:
        normalized = normalize_virtual_path(path)
        key = self._key_for_path(normalized)
        if not key:
            raise StorageInvalidPathError("Path is a directory: /")

        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            if _is_s3_not_found(exc):
                raise StoragePathNotFoundError(f"Path not found: {normalized}") from exc
            raise StorageDriverError(f"S3 read failed: {exc}") from exc

        body = response.get("Body")
        if body is None:
            raise StorageDriverError("S3 read failed: empty body")

        try:
            content = body.read()
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 read failed: {exc}") from exc

        content_type = response.get("ContentType")
        if not isinstance(content_type, str) or not content_type.strip():
            content_type = mimetypes.guess_type(normalized)[0]

        return StorageReadResult(
            path=normalized,
            name=_basename_virtual_path(normalized),
            content=content,
            mime_type=content_type,
        )

    def _delete_directory(self, path: str, *, recursive: bool) -> None:
        prefix = self._key_prefix_for_dir(path)
        keys: list[str] = []

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)
            for page in pages:
                for item in page.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if key:
                        keys.append(key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 directory listing for deletion failed: {exc}") from exc

        if not keys:
            raise StoragePathNotFoundError(f"Path not found: {path}")

        if not recursive:
            non_marker = [key for key in keys if key != prefix]
            if non_marker:
                raise StorageDriverError("Directory is not empty")

        self._delete_keys(keys)

    def _delete_object(self, path: str) -> None:
        key = self._key_for_path(path)
        self._ensure_object_exists(key, path)

        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 delete failed: {exc}") from exc

    def _move_object(self, source_path: str, target_path: str) -> None:
        source_key = self._key_for_path(source_path)
        target_key = self._key_for_path(target_path)
        self._ensure_object_exists(source_key, source_path)
        self._ensure_object_not_exists(target_key, target_path)

        try:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=target_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )
            self._client.delete_object(Bucket=self._bucket, Key=source_key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 move failed: {exc}") from exc

    def _move_directory(self, source_path: str, target_path: str) -> None:
        source_prefix = self._key_prefix_for_dir(source_path)
        target_prefix = self._key_prefix_for_dir(target_path)

        if source_prefix == target_prefix:
            return

        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self._bucket, Prefix=source_prefix)
            for page in pages:
                for item in page.get("Contents", []):
                    key = str(item.get("Key", ""))
                    if key:
                        keys.append(key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 directory listing for move failed: {exc}") from exc

        if not keys:
            raise StoragePathNotFoundError(f"Path not found: {source_path}")

        if self._prefix_exists(target_prefix):
            raise StorageDriverError(f"Path already exists: {target_path}")

        try:
            for key in keys:
                suffix = key[len(source_prefix) :]
                target_key = f"{target_prefix}{suffix}"
                self._client.copy_object(
                    Bucket=self._bucket,
                    Key=target_key,
                    CopySource={"Bucket": self._bucket, "Key": key},
                )
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 directory move copy failed: {exc}") from exc

        self._delete_keys(keys)

    def _prefix_exists(self, prefix: str) -> bool:
        if not prefix:
            return False
        try:
            response = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix, MaxKeys=1)
        except Exception as exc:  # pragma: no cover - provider specific errors
            raise StorageDriverError(f"S3 exists check failed: {exc}") from exc
        return bool(response.get("KeyCount", 0))

    def _ensure_object_exists(self, key: str, display_path: str) -> None:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # pragma: no cover - provider specific errors
            if _is_s3_not_found(exc):
                raise StoragePathNotFoundError(f"Path not found: {display_path}") from exc
            raise StorageDriverError(f"S3 stat failed: {exc}") from exc

    def _ensure_object_not_exists(self, key: str, display_path: str) -> None:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            raise StorageDriverError(f"Path already exists: {display_path}")
        except StorageDriverError:
            raise
        except Exception as exc:  # pragma: no cover - provider specific errors
            if _is_s3_not_found(exc):
                return
            raise StorageDriverError(f"S3 stat failed: {exc}") from exc

    def _delete_keys(self, keys: list[str]) -> None:
        chunk_size = 1000
        for index in range(0, len(keys), chunk_size):
            chunk = keys[index : index + chunk_size]
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True},
            )

    def _key_for_path(self, normalized_path: str) -> str:
        relative = normalized_path.strip("/")
        if self._root_prefix:
            if not relative:
                return self._root_prefix.rstrip("/")
            return f"{self._root_prefix}{relative}"
        return relative

    def _key_prefix_for_dir(self, normalized_path: str) -> str:
        if normalized_path == "/":
            return self._root_prefix
        key = self._key_for_path(normalized_path)
        return f"{key}/" if key and not key.endswith("/") else key

    def _relative_to_parent(self, key: str, parent_path: str) -> str | None:
        if self._root_prefix and not key.startswith(self._root_prefix):
            return None
        relative = key[len(self._root_prefix) :] if self._root_prefix else key
        relative = relative.strip("/")
        if not relative:
            return None

        parent_relative = parent_path.strip("/")
        if not parent_relative:
            return relative

        if relative == parent_relative:
            return None

        parent_prefix = f"{parent_relative}/"
        if not relative.startswith(parent_prefix):
            return None
        return relative[len(parent_prefix) :]


def _parent_virtual_path(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return "/"
    parent = normalized.rsplit("/", 1)[0]
    return parent if parent else "/"


def _basename_virtual_path(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return ""
    return normalized.rsplit("/", 1)[-1]


def _normalize_s3_prefix(path: str | None) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return ""
    return f"{normalized.strip('/')}/"


def _coerce_non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _coerce_positive_number(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return default
    else:
        return default
    return number if number > 0 else default


def _is_s3_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    code = str(error.get("Code", "")).upper()
    return code in {"404", "NOSUCHKEY", "NOTFOUND"}
