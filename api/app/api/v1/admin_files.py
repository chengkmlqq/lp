from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.file_storage import (
    FileCreateDirectoryRequest,
    FileDeleteRequest,
    FileListResponse,
    FileMoveRequest,
    FileOperationResponse,
    FileRenameRequest,
)
from ...services.file_service import (
    create_directory,
    delete_file_path,
    download_directory_as_zip,
    download_file_from_path,
    list_files,
    move_file_path,
    rename_file_path,
    upload_file_to_path,
)

router = APIRouter(prefix="/admin/files", tags=["admin-files"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("", response_model=FileListResponse)
def get_files(
    mount_code: str | None = Query(default=None),
    path: str | None = Query(default="/"),
    current_user: CurrentUser = Depends(require_any_permission("file.read", "file.manage")),
    db: Session = Depends(get_db),
) -> FileListResponse:
    return list_files(
        db,
        actor=current_user.user,
        mount_code=mount_code,
        path=path,
    )


@router.post("/directories", response_model=FileOperationResponse)
def create_directory_endpoint(
    payload: FileCreateDirectoryRequest,
    current_user: CurrentUser = Depends(require_permission("file.manage")),
    db: Session = Depends(get_db),
) -> FileOperationResponse:
    return create_directory(db, payload, actor=current_user.user)


@router.post("/delete", response_model=FileOperationResponse)
def delete_path_endpoint(
    payload: FileDeleteRequest,
    current_user: CurrentUser = Depends(require_permission("file.manage")),
    db: Session = Depends(get_db),
) -> FileOperationResponse:
    return delete_file_path(db, payload, actor=current_user.user)


@router.post("/rename", response_model=FileOperationResponse)
def rename_path_endpoint(
    payload: FileRenameRequest,
    current_user: CurrentUser = Depends(require_permission("file.manage")),
    db: Session = Depends(get_db),
) -> FileOperationResponse:
    return rename_file_path(db, payload, actor=current_user.user)


@router.post("/move", response_model=FileOperationResponse)
def move_path_endpoint(
    payload: FileMoveRequest,
    current_user: CurrentUser = Depends(require_permission("file.manage")),
    db: Session = Depends(get_db),
) -> FileOperationResponse:
    return move_file_path(db, payload, actor=current_user.user)


@router.post("/upload", response_model=FileOperationResponse)
def upload_file_endpoint(
    mount_code: str = Query(..., min_length=2, max_length=64),
    parent_path: str = Query(default="/", max_length=2048),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("file.manage")),
    db: Session = Depends(get_db),
) -> FileOperationResponse:
    return upload_file_to_path(
        db,
        mount_code=mount_code,
        parent_path=parent_path,
        file=file,
        actor=current_user.user,
    )


@router.get("/download")
def download_file_endpoint(
    mount_code: str = Query(..., min_length=2, max_length=64),
    path: str = Query(..., min_length=1, max_length=2048),
    current_user: CurrentUser = Depends(require_any_permission("file.read", "file.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filename, content, content_type = download_file_from_path(
        db,
        mount_code=mount_code,
        path=path,
        actor=current_user.user,
    )

    media_type = content_type or "application/octet-stream"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type=media_type, headers=headers)


@router.get("/download-zip")
def download_directory_zip_endpoint(
    mount_code: str = Query(..., min_length=2, max_length=64),
    path: str = Query(..., min_length=1, max_length=2048),
    current_user: CurrentUser = Depends(require_any_permission("file.read", "file.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filename, content, content_type = download_directory_as_zip(
        db,
        mount_code=mount_code,
        path=path,
        actor=current_user.user,
    )

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type=content_type, headers=headers)
