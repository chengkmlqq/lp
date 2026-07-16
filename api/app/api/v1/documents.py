from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import (
    CurrentUser,
    get_current_user,
    require_enabled_menu_route,
)
from ...schemas.document import (
    DocumentChapterCreateRequest,
    DocumentChapterListResponse,
    DocumentChapterPublic,
    DocumentChapterTreeItem,
    DocumentChapterUpdateRequest,
    DocumentCreateRequest,
    DocumentListResponse,
    DocumentPublic,
    DocumentUpdateRequest,
)
from ...services.document_service import (
    create_document,
    create_document_chapter,
    delete_document,
    delete_document_chapter,
    get_document_by_id,
    get_document_chapter_by_id,
    get_document_chapter_tree,
    list_document_chapters,
    list_documents,
    serialize_document,
    serialize_document_chapter,
    update_document,
    update_document_chapter,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get(
    "/chapters",
    response_model=DocumentChapterListResponse,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_document_chapters(
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentChapterListResponse:
    return list_document_chapters(db, keyword=keyword, limit=limit, offset=offset)


@router.get(
    "/chapters/tree",
    response_model=list[DocumentChapterTreeItem],
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_chapters_tree(
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentChapterTreeItem]:
    return get_document_chapter_tree(db)


@router.get(
    "/chapters/{chapter_id}",
    response_model=DocumentChapterPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_chapter_detail(
    chapter_id: int,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentChapterPublic:
    chapter = get_document_chapter_by_id(db, chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在",
        )
    return serialize_document_chapter(chapter)


@router.post(
    "/chapters",
    response_model=DocumentChapterPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def create_chapter(
    payload: DocumentChapterCreateRequest,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentChapterPublic:
    chapter = create_document_chapter(db, payload)
    return serialize_document_chapter(chapter)


@router.patch(
    "/chapters/{chapter_id}",
    response_model=DocumentChapterPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def update_chapter(
    chapter_id: int,
    payload: DocumentChapterUpdateRequest,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentChapterPublic:
    chapter = update_document_chapter(db, chapter_id, payload)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在",
        )
    return serialize_document_chapter(chapter)


@router.delete(
    "/chapters/{chapter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_enabled_menu_route)],
)
def delete_chapter(
    chapter_id: int,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    success = delete_document_chapter(db, chapter_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在",
        )


@router.get(
    "",
    response_model=DocumentListResponse,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_documents(
    keyword: str | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    return list_documents(
        db,
        keyword=keyword,
        chapter_id=chapter_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_document_detail(
    document_id: int,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPublic:
    document = get_document_by_id(db, document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在",
        )
    return serialize_document(document)


@router.post(
    "",
    response_model=DocumentPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def create_document_endpoint(
    payload: DocumentCreateRequest,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPublic:
    document = create_document(db, payload)
    return serialize_document(document)


@router.patch(
    "/{document_id}",
    response_model=DocumentPublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def update_document_endpoint(
    document_id: int,
    payload: DocumentUpdateRequest,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentPublic:
    document = update_document(db, document_id, payload)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在",
        )
    return serialize_document(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_enabled_menu_route)],
)
def delete_document_endpoint(
    document_id: int,
    _: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    success = delete_document(db, document_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在",
        )
