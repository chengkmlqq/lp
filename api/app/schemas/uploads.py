from __future__ import annotations

from pydantic import BaseModel


class TempUploadResponse(BaseModel):
    """选择文件后立即上传到 MinIO 临时目录，返回 temp_file_id 供确认导入时引用。"""

    temp_file_id: str
    file_name: str = "upload"