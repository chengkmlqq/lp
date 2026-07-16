"""
Internal API Endpoints

这些端点不进行 JWT 认证，通过其他机制（如共享密钥）保护。
仅用于 worker 与 API 之间的内部通信。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.elevation_service import execute_file_record_terrain_unpack_job

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/elevation/records/{record_id}/terrain/unpack")
async def internal_unpack_elevation_file_record_terrain(
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """解包 terrain staging 中的 tar.gz 包到最终路径（由 worker 通过共享密钥调用）"""
    expected_secret = os.environ.get("UNPACK_SECRET_KEY", "")
    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UNPACK_SECRET_KEY 未配置",
        )
    actual_secret = request.headers.get("X-Unpack-Secret", "")
    if not actual_secret or actual_secret != expected_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="解包密钥无效",
        )

    body = await request.json()
    min_zoom = body.get("min_zoom", 0)
    max_zoom = body.get("max_zoom", 6)
    if not isinstance(min_zoom, int) or not isinstance(max_zoom, int):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_zoom 和 max_zoom 必须为整数",
        )
    tile_count = body.get("tile_count", 0)

    execute_file_record_terrain_unpack_job(
        record_id=record_id,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        tile_count=tile_count,
    )
    return {"status": "ok", "record_id": record_id}
