from pathlib import Path
import os
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...services.user_service import get_user_by_id

router = APIRouter(tags=["avatar"])

AVATAR_STORAGE_DIR = "/app/data/avatars"

MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@router.get("/users/{user_id}/avatar")
def get_user_avatar(
    user_id: str,
    db: Session = Depends(get_db),
) -> Response:
    user = get_user_by_id(db, user_id)
    if not user or not user.avatar_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    filepath = os.path.join(AVATAR_STORAGE_DIR, user.avatar_path)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar file not found")

    ext = Path(filepath).suffix.lower()
    media_type = MIME_MAP.get(ext, "application/octet-stream")

    with open(filepath, "rb") as f:
        content = f.read()

    return Response(content=content, media_type=media_type, headers={
        "Cache-Control": "public, max-age=86400",
    })
