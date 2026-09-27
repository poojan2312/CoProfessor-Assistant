"""Citation rendering test.

This is the direct answer to "Page numbers etc" and "the wrong material is
referenced with valid but wrong reference". The assertion is that the rendered
page number comes from the parsed document, and that nothing the model wrote can
influence it.
"""
from __future__ import annotations

from app.services import citations


def test_page_number_comes_from_the_database(db, chunks):
    built = citations.build(db, [chunks[0].id])
    assert built[chunks[0].id]["page_no"] == 214


def test_display_string_uses_stored_title_and_author(db, chunks):
    display = citations.build(db, [chunks[0].id])[chunks[0].id]["display"]
    assert display == "Silberschatz, Operating System Concepts, p. 214"


def test_each_chunk_resolves_to_its_own_page(db, chunks):
    built = citations.build(db, [c.id for c in chunks])
    assert {c.id: built[c.id]["page_no"] for c in chunks} == {
        chunks[0].id: 214,
        chunks[1].id: 266,
    }


def test_snippet_is_the_verbatim_chunk_text(db, chunks):
    """The professor must be able to check the claim against the real words."""
    built = citations.build(db, [chunks[1].id])
    assert built[chunks[1].id]["snippet"] == chunks[1].text


def test_model_output_cannot_influence_the_rendered_page(db, chunks):
    """A model 'citation' claiming page 999 changes nothing.

    Only the chunk id is carried forward from generation, so the stored page is
    the one the PDF parser recorded.
    """
    hallucinated = {"page_no": 999, "source_title": "A Book That Does Not Exist"}
    built = citations.build(db, [chunks[0].id])[chunks[0].id]

    assert built["page_no"] != hallucinated["page_no"]
    assert built["page_no"] == 214
    assert built["source_title"] == "Operating System Concepts"


def test_unknown_chunk_ids_are_dropped_not_invented(db, chunks):
    built = citations.build(db, [chunks[0].id, 999_999])
    assert set(built) == {chunks[0].id}


def test_no_chunks_yields_no_citations(db):
    assert citations.build(db, []) == {}


def test_long_chunk_text_is_truncated_for_display(db, chunks):
    chunks[0].text = "x" * 5000
    db.commit()
    snippet = citations.build(db, [chunks[0].id])[chunks[0].id]["snippet"]
    assert len(snippet) <= citations.SNIPPET_CHARS + 3
    assert snippet.endswith("...")
