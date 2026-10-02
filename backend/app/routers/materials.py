"""Upload and listing of course materials."""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import UPLOAD_DIR, get_settings
from app.db import SessionLocal, get_db
from app.models import Document, Source
from app.routers.courses import get_course_or_404
from app.schemas import SourceOut
from app.services.ingest import ingest_document

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["materials"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_stem(filename: str) -> str:
    return _SAFE.sub("_", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])[:120] or "upload.pdf"


def _run_ingest(document_id: int) -> None:
    """Background entry point. Owns its own session - the request's is long closed."""
    get_settings()
    with SessionLocal() as db:
        ingest_document(db, document_id)


@router.post(
    "/courses/{course_id}/materials",
    response_model=SourceOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_material(
    course_id: int,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    year: int | None = Form(None),
    db: Session = Depends(get_db),
) -> Source:
    """Accept a PDF, register it as an approved source, and index it in the background."""
    course = get_course_or_404(db, course_id)

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF uploads are supported. Export slides or notes to PDF first.",
        )

    payload = file.file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not payload.startswith(b"%PDF"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That file is not a valid PDF (missing the %PDF header).",
        )

    stem = _safe_stem(file.filename)
    stored_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{stem}"
    stored_path.write_bytes(payload)

    # Uploads are approved on arrival: the professor chose this file deliberately.
    # Sources the assistant *suggests* will enter as 'pending' instead.
    source = Source(
        course_id=course.id,
        kind="uploaded",
        title=(title.strip() or stem.rsplit(".", 1)[0].replace("_", " ")),
        authors=authors.strip(),
        year=year,
        identifier=file.filename or stem,
        status="approved",
        allowed_uses=["lecture_content"],
    )
    db.add(source)
    db.flush()

    document = Document(
        source_id=source.id,
        filename=file.filename or stem,
        path=str(stored_path),
        ingest_status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(source)

    background.add_task(_run_ingest, document.id)
    return source


@router.get("/courses/{course_id}/materials", response_model=list[SourceOut])
def list_materials(course_id: int, db: Session = Depends(get_db)) -> list[Source]:
    get_course_or_404(db, course_id)
    return list(
        db.execute(
            select(Source)
            .options(selectinload(Source.documents))
            .where(Source.course_id == course_id)
            .order_by(Source.created_at.desc())
        ).scalars()
    )


@router.delete("/materials/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(source_id: int, db: Session = Depends(get_db)):
    from app.services.vectorstore import get_store

    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Source {source_id} not found")

    store = get_store()
    for document in source.documents:
        store.delete_document(document.id)
    db.delete(source)
    db.commit()

@router.patch("/materials/{source_id}/approve", response_model=SourceOut)
def approve_material(source_id: int, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Source {source_id} not found")
    source.status = "approved"
    db.commit()
    db.refresh(source)
    return source

@router.patch("/materials/{source_id}/reject", response_model=SourceOut)
def reject_material(source_id: int, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Source {source_id} not found")
    source.status = "rejected"
    db.commit()
    db.refresh(source)
    return source
