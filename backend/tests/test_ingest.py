"""Ingestion test.

The guarantee under test: a chunk's recorded page number is the page its text
actually came from. Everything downstream - every citation the professor sees -
depends on this being exactly right, so it is checked against the real PDFs in
the project directory rather than a synthetic fixture.
"""
from __future__ import annotations

import fitz
import pytest

from app.config import PROJECT_ROOT
from app.services.ingest import clean, extract_chunks, split_page

PDFS = sorted(PROJECT_ROOT.glob("*.pdf"))
pytestmark = pytest.mark.skipif(not PDFS, reason="no reference PDFs in the project root")


def _normalise(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem[:30])
def test_every_chunk_text_is_on_the_page_it_claims(pdf):
    """The single most important assertion in the suite."""
    _, chunks = extract_chunks(str(pdf))
    assert chunks, f"{pdf.name} produced no chunks"

    with fitz.open(str(pdf)) as doc:
        for chunk in chunks:
            page_text = _normalise(clean(doc[chunk["page_no"] - 1].get_text("text")))
            probe = _normalise(chunk["text"])[:60]
            assert probe in page_text, (
                f"{pdf.name}: chunk claims page {chunk['page_no']} but its text "
                f"is not on that page: {probe!r}"
            )


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem[:30])
def test_page_numbers_are_one_based_and_in_range(pdf):
    page_count, chunks = extract_chunks(str(pdf))
    assert page_count > 0
    assert all(1 <= c["page_no"] <= page_count for c in chunks)


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem[:30])
def test_reported_page_count_matches_the_file(pdf):
    page_count, _ = extract_chunks(str(pdf))
    with fitz.open(str(pdf)) as doc:
        assert page_count == doc.page_count


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem[:30])
def test_chunk_ordinals_are_unique_and_sequential(pdf):
    _, chunks = extract_chunks(str(pdf))
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))


def test_split_never_crosses_a_page_boundary():
    """Chunks are cut within a page, which is why page_no can be exact."""
    page = "Sentence one. " * 400
    pieces = split_page(page, size=1000, overlap=150)
    assert len(pieces) > 1
    assert all(piece.strip() for piece, _, _ in pieces)
    assert all(piece in page for piece, _, _ in pieces)


def test_short_page_yields_a_single_chunk():
    assert len(split_page("A short page.", size=1000, overlap=150)) == 1


def test_clean_strips_extraction_artifacts():
    cleaned = clean("�Bullet• text with ﬁne  spacing’s quotes")
    assert "�" not in cleaned
    assert "•" not in cleaned
    assert "fine" in cleaned
    assert "'" in cleaned


def test_clean_strips_zero_width_and_direction_characters():
    """Invisible characters pollute embeddings and break console output."""
    cleaned = clean("learning\u200btrails\ufeff and\u200e continuity")
    assert "\u200b" not in cleaned
    assert "\ufeff" not in cleaned
    assert "\u200e" not in cleaned
    assert "learningtrails" in cleaned
