from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ...core.dependencies import CurrentUser, get_current_user, require_enabled_menu_route
from ...core.file_upload import save_temp_file
from ...schemas.uploads import TempUploadResponse

router = APIRouter(
    prefix="/uploads",
    tags=["uploads"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.post("/temp", response_model=TempUploadResponse)
def upload_temp_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> TempUploadResponse:
    """选择文件后立即上传到 MinIO 临时目录，返回 temp_file_id 供确认导入时引用。

    临时文件在导入消费后自动删除，或由 24h 定时清理任务兜底。
    """
    temp_file_id, file_name = save_temp_file(file, current_user.user.id)
    return TempUploadResponse(temp_file_id=temp_file_id, file_name=file_name)