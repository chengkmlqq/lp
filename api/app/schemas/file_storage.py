from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

StorageDriverType = Literal["VFS", "S3"]


class FileStorageBackendPublic(BaseModel):
    id: int
    code: str
    name: str
    driver_type: StorageDriverType
    status: str
    is_default: bool
    config_summary: dict[str, Any] = Field(default_factory=dict)


class FileStorageMountPublic(BaseModel):
    id: int
    code: str
    name: str
    mount_path: str
    root_path: str
    is_enabled: bool
    backend: FileStorageBackendPublic


class FileBreadcrumbItem(BaseModel):
    name: str
    path: str


class FileEntryPublic(BaseModel):
    id: int
    path: str
    parent_path: str
    name: str
    is_dir: bool
    size: int
    mime_type: str | None = None
    etag: str | None = None
    storage_key: str | None = None
    modified_at: datetime | None = None
    synced_at: datetime


class FileListResponse(BaseModel):
    mounts: list[FileStorageMountPublic]
    current_mount: FileStorageMountPublic
    current_path: str
    breadcrumbs: list[FileBreadcrumbItem]
    items: list[FileEntryPublic]
    total: int
    synced_at: datetime


class FileCreateDirectoryRequest(BaseModel):
    mount_code: str = Field(min_length=2, max_length=64)
    parent_path: str = Field(default="/", max_length=2048)
    name: str = Field(min_length=1, max_length=255)


class FileDeleteRequest(BaseModel):
    mount_code: str = Field(min_length=2, max_length=64)
    path: str = Field(min_length=1, max_length=2048)
    is_dir: bool
    recursive: bool = False


class FileRenameRequest(BaseModel):
    mount_code: str = Field(min_length=2, max_length=64)
    path: str = Field(min_length=1, max_length=2048)
    is_dir: bool
    new_name: str = Field(min_length=1, max_length=255)


class FileMoveRequest(BaseModel):
    mount_code: str = Field(min_length=2, max_length=64)
    path: str = Field(min_length=1, max_length=2048)
    is_dir: bool
    target_parent_path: str = Field(default="/", max_length=2048)
    new_name: str | None = Field(default=None, max_length=255)


class FileOperationResponse(BaseModel):
    success: bool = True
    mount_code: str
    path: str
    action: str | None = None
    target_path: str | None = None
