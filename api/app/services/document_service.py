from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.document import Document, DocumentChapter
from ..schemas.document import (
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


def serialize_document_chapter(chapter: DocumentChapter) -> DocumentChapterPublic:
    return DocumentChapterPublic(
        id=chapter.id,
        name=chapter.name,
        description=chapter.description,
        parent_id=chapter.parent_id,
        sort_order=chapter.sort_order,
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
    )


def serialize_document(document: Document) -> DocumentPublic:
    return DocumentPublic(
        id=document.id,
        title=document.title,
        content=document.content,
        chapter_id=document.chapter_id,
        sort_order=document.sort_order,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def build_chapter_tree(chapters: list[DocumentChapter]) -> list[DocumentChapterTreeItem]:
    chapter_map = {c.id: c for c in chapters}
    tree = []

    for chapter in chapters:
        if chapter.parent_id is None:
            tree_item = DocumentChapterTreeItem(
                id=chapter.id,
                name=chapter.name,
                description=chapter.description,
                parent_id=chapter.parent_id,
                sort_order=chapter.sort_order,
                created_at=chapter.created_at,
                updated_at=chapter.updated_at,
                children=[],
                documents=[serialize_document(d) for d in chapter.documents],
            )
            tree.append(tree_item)

    def add_children(node: DocumentChapterTreeItem):
        for chapter in chapters:
            if chapter.parent_id == node.id:
                child_item = DocumentChapterTreeItem(
                    id=chapter.id,
                    name=chapter.name,
                    description=chapter.description,
                    parent_id=chapter.parent_id,
                    sort_order=chapter.sort_order,
                    created_at=chapter.created_at,
                    updated_at=chapter.updated_at,
                    children=[],
                    documents=[serialize_document(d) for d in chapter.documents],
                )
                node.children.append(child_item)
                add_children(child_item)

    for item in tree:
        add_children(item)

    return tree


def list_document_chapters(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None = None,
) -> DocumentChapterListResponse:
    stmt = select(DocumentChapter)
    if keyword:
        stmt = stmt.where(DocumentChapter.name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(DocumentChapter.sort_order, DocumentChapter.id)
    stmt = stmt.limit(limit).offset(offset)

    total_stmt = select(func.count()).select_from(DocumentChapter)
    if keyword:
        total_stmt = total_stmt.where(DocumentChapter.name.ilike(f"%{keyword}%"))

    total = db.scalar(total_stmt) or 0
    chapters = list(db.scalars(stmt).all())

    return DocumentChapterListResponse(
        items=[serialize_document_chapter(c) for c in chapters],
        total=total,
    )


def get_document_chapter_tree(db: Session) -> list[DocumentChapterTreeItem]:
    stmt = select(DocumentChapter).order_by(DocumentChapter.sort_order, DocumentChapter.id)
    chapters = list(db.scalars(stmt).all())
    return build_chapter_tree(chapters)


def get_document_chapter_by_id(db: Session, chapter_id: int) -> DocumentChapter | None:
    return db.get(DocumentChapter, chapter_id)


def create_document_chapter(
    db: Session, payload: DocumentChapterCreateRequest
) -> DocumentChapter:
    chapter = DocumentChapter(
        name=payload.name,
        description=payload.description,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def update_document_chapter(
    db: Session, chapter_id: int, payload: DocumentChapterUpdateRequest
) -> DocumentChapter | None:
    chapter = db.get(DocumentChapter, chapter_id)
    if not chapter:
        return None

    if payload.name is not None:
        chapter.name = payload.name
    if payload.description is not None:
        chapter.description = payload.description
    if payload.parent_id is not None:
        chapter.parent_id = payload.parent_id
    if payload.sort_order is not None:
        chapter.sort_order = payload.sort_order

    db.commit()
    db.refresh(chapter)
    return chapter


def delete_document_chapter(db: Session, chapter_id: int) -> bool:
    chapter = db.get(DocumentChapter, chapter_id)
    if not chapter:
        return False
    db.delete(chapter)
    db.commit()
    return True


def list_documents(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None = None,
    chapter_id: int | None = None,
    status: str | None = None,
) -> DocumentListResponse:
    stmt = select(Document)
    if keyword:
        stmt = stmt.where(Document.title.ilike(f"%{keyword}%"))
    if chapter_id is not None:
        stmt = stmt.where(Document.chapter_id == chapter_id)
    if status:
        stmt = stmt.where(Document.status == status)
    stmt = stmt.order_by(Document.sort_order, Document.id)
    stmt = stmt.limit(limit).offset(offset)

    total_stmt = select(func.count()).select_from(Document)
    if keyword:
        total_stmt = total_stmt.where(Document.title.ilike(f"%{keyword}%"))
    if chapter_id is not None:
        total_stmt = total_stmt.where(Document.chapter_id == chapter_id)
    if status:
        total_stmt = total_stmt.where(Document.status == status)

    total = db.scalar(total_stmt) or 0
    documents = list(db.scalars(stmt).all())

    return DocumentListResponse(
        items=[serialize_document(d) for d in documents],
        total=total,
    )


def get_document_by_id(db: Session, document_id: int) -> Document | None:
    return db.get(Document, document_id)


def create_document(db: Session, payload: DocumentCreateRequest) -> Document:
    document = Document(
        title=payload.title,
        content=payload.content,
        chapter_id=payload.chapter_id,
        sort_order=payload.sort_order,
        status=payload.status,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_document(
    db: Session, document_id: int, payload: DocumentUpdateRequest
) -> Document | None:
    document = db.get(Document, document_id)
    if not document:
        return None

    if payload.title is not None:
        document.title = payload.title
    if payload.content is not None:
        document.content = payload.content
    if payload.chapter_id is not None:
        document.chapter_id = payload.chapter_id
    if payload.sort_order is not None:
        document.sort_order = payload.sort_order
    if payload.status is not None:
        document.status = payload.status

    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document_id: int) -> bool:
    document = db.get(Document, document_id)
    if not document:
        return False
    db.delete(document)
    db.commit()
    return True
