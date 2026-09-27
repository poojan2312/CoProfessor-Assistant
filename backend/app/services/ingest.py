"""PDF ingestion.

The page number recorded here is the one PyMuPDF reports for the page the text
was actually extracted from, and chunks are cut WITHIN a page so a chunk can
never span a page boundary. That is what makes `Chunk.page_no` exact rather than
approximate, and it is the reason the assistant cannot get a page number wrong.
"""
from __future__ import annotations

import logging
import re

import fitz  # PyMuPDF
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document
from app.services import embeddings
from app.services.vectorstore import get_store

log = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
# Symbol fonts and broken encodings leave replacement characters, private-use
# glyphs and control codes in extracted text. They would otherwise be embedded
# and shown back to the professor as citation evidence.
_JUNK = re.compile(
    r"[\ufffd\ue000-\uf8ff\x00-\x08\x0b\x0c\x0e-\x1f"
    r"\u200b-\u200f\u2028\u2029\u202a-\u202e\ufeff]"
)
MIN_CHUNK_CHARS = 60

# Ligatures, smart quotes and bullet glyphs, expanded so that both retrieval and
# the displayed snippet see ordinary words.
_REPLACEMENTS = {
    "\u00ad": "", "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
    "\u2022": "-", "\u25cf": "-", "\u25aa": "-", "\u00a0": " ",
}


def clean(text: str) -> str:
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = _JUNK.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def split_page(text: str, size: int, overlap: int) -> list[tuple[str, int, int]]:
    """Split one page into (text, char_start, char_end) windows.

    Breaks on a paragraph or sentence boundary near the target size when one is
    available, so chunks stay readable when shown to the professor as evidence.
    """
    if len(text) <= size:
        return [(text, 0, len(text))] if text else []

    out: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for marker in ("\n\n", ". ", "\n", " "):
                cut = window.rfind(marker)
                if cut > size * 0.5:
                    end = start + cut + len(marker)
                    break
        piece = text[start:end].strip()
        if piece:
            out.append((piece, start, end))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def extract_chunks(path: str) -> tuple[int, list[dict]]:
    """Return (page_count, chunks) where each chunk carries its true page number."""
    settings = get_settings()
    chunks: list[dict] = []
    ordinal = 0

    with fitz.open(path) as pdf:
        page_count = pdf.page_count
        for page_index in range(page_count):
            page_text = clean(pdf[page_index].get_text("text"))
            if not page_text:
                continue
            for piece, start, end in split_page(
                page_text, settings.chunk_size, settings.chunk_overlap
            ):
                if len(piece) < MIN_CHUNK_CHARS:
                    continue
                chunks.append(
                    {
                        "page_no": page_index + 1,  # 1-based, as a reader would count
                        "ordinal": ordinal,
                        "text": piece,
                        "char_start": start,
                        "char_end": end,
                    }
                )
                ordinal += 1

    return page_count, chunks


def ingest_document(db: Session, document_id: int) -> None:
    """Parse, chunk, embed and index one uploaded document.

    Runs in a FastAPI background task. Failures are recorded on the Document row
    so the UI can show them instead of leaving the upload stuck on 'processing'.
    """
    document = db.get(Document, document_id)
    if document is None:
        log.error("ingest: document %s vanished", document_id)
        return

    document.ingest_status = "processing"
    db.commit()

    try:
        page_count, raw_chunks = extract_chunks(document.path)
        if not raw_chunks:
            raise ValueError(
                "No extractable text found. If this is a scanned PDF it needs OCR first."
            )

        rows = [Chunk(document_id=document.id, **c) for c in raw_chunks]
        db.add_all(rows)
        db.flush()  # assign ids before they go into the vector index

        vectors = embeddings.embed_texts(
            [r.text for r in rows], task_type=embeddings.DOCUMENT
        )

        source = document.source
        get_store().add(
            chunk_ids=[r.id for r in rows],
            embeddings=vectors,
            metadatas=[
                {
                    "chunk_id": r.id,
                    "document_id": document.id,
                    "source_id": source.id,
                    "course_id": source.course_id,
                    "page_no": r.page_no,
                }
                for r in rows
            ],
        )

        document.page_count = page_count
        document.chunk_count = len(rows)
        document.ingest_status = "ready"
        document.ingest_error = ""
        db.commit()
        log.info("ingested %s: %s pages, %s chunks", document.filename, page_count, len(rows))

    except Exception as exc:  # noqa: BLE001 - status must reflect any failure
        db.rollback()
        document = db.get(Document, document_id)
        if document is not None:
            document.ingest_status = "failed"
            document.ingest_error = str(exc)[:1000]
            db.commit()
        log.exception("ingest failed for document %s", document_id)
