"""Rendering of citations from database metadata ONLY.

Nothing in this module reads model output. A citation's page number, title and
author come from the PDF parser and the source record; the model's only
contribution was pointing at a chunk id. This is the single place where a
citation string is constructed, so the guarantee holds everywhere by default.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Chunk, Document

SNIPPET_CHARS = 400


def _format(source_title: str, authors: str, page_no: int) -> str:
    parts = []
    if authors:
        parts.append(authors.split(",")[0].strip())
    parts.append(source_title)
    parts.append(f"p. {page_no}")
    return ", ".join(p for p in parts if p)


def build(db: Session, chunk_ids: list[int]) -> dict[int, dict]:
    """Return {chunk_id: citation dict} for the given chunks.

    The `snippet` is the verbatim chunk text. The UI shows it on hover so the
    professor can confirm, without leaving the page, that the cited words really
    are on the cited page - which is the whole point.
    """
    if not chunk_ids:
        return {}

    rows = db.execute(
        select(Chunk)
        .options(joinedload(Chunk.document).joinedload(Document.source))
        .where(Chunk.id.in_(set(chunk_ids)))
    ).scalars().all()

    out: dict[int, dict] = {}
    for chunk in rows:
        source = chunk.document.source
        snippet = chunk.text.strip()
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rstrip() + "..."
        out[chunk.id] = {
            "chunk_id": chunk.id,
            "source_id": source.id,
            "source_title": source.title,
            "authors": source.authors,
            "year": source.year,
            "kind": source.kind,
            "identifier": source.identifier,
            "document_filename": chunk.document.filename,
            "page_no": chunk.page_no,
            "snippet": snippet,
            "display": _format(source.title, source.authors, chunk.page_no),
        }
    return out
