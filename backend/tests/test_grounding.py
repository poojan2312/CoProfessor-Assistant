"""Resource verification test, foundation layer.

Phase 1 outcome: "Verify that the system does not present non-existent resources
as valid or verified."

These tests encode the professor's specific complaints: a model that cites a
source that was never retrieved, and a model that tries to write a page number
of its own.

Enforcement is structural - any dict carrying a "grounding" list is checked,
wherever it sits in the response - so lecture plans, chat replies and teaching
support are all covered by the same code and the same tests.
"""
from __future__ import annotations

from app.services.grounding import audit, check_tags, cited_chunk_ids, scrub


# --- Tag validation -----------------------------------------------------------

def test_valid_tags_are_accepted():
    result = check_tags(["S1", "S4"], window_size=5)
    assert result.valid == [1, 4]
    assert result.invalid == []


def test_tag_beyond_the_retrieval_window_is_rejected():
    result = check_tags(["S9"], window_size=5)
    assert result.valid == []
    assert result.invalid == ["S9"]


def test_model_written_page_number_is_rejected():
    """The exact failure the professor reported: a plausible-looking reference."""
    result = check_tags(["Silberschatz p. 214", "S2"], window_size=5)
    assert result.valid == [2]
    assert "Silberschatz p. 214" in result.invalid


def test_malformed_tags_are_rejected():
    result = check_tags(["S0", "s1", "S", "", "S-1", "S1.5", None, 7], window_size=5)
    assert result.valid == []
    assert len(result.invalid) == 8


def test_duplicate_tags_collapse():
    assert check_tags(["S2", "S2", "S2"], window_size=3).valid == [2]


def test_non_list_grounding_is_ignored():
    assert check_tags("S1", window_size=3).valid == []
    assert check_tags(None, window_size=3).valid == []


# --- Auditing anywhere in a response ------------------------------------------

def test_audit_passes_a_clean_response():
    response = {
        "segments": [{"title": "a", "grounding": ["S1"]}, {"title": "b", "grounding": []}],
        "learning_objectives": [{"text": "o", "grounding": ["S3"]}],
    }
    assert audit(response, window_size=3) == []


def test_audit_finds_a_violation_in_any_field():
    """A new citable field cannot bypass enforcement by not being registered."""
    for field in ("segments", "misconceptions", "activities", "anything_at_all"):
        response = {field: [{"text": "x", "grounding": ["S99"]}]}
        assert audit(response, window_size=3) == ["S99"], field


def test_audit_reaches_arbitrarily_deep():
    response = {"a": {"b": [{"c": {"items": [{"text": "x", "grounding": ["S42"]}]}}]}}
    assert audit(response, window_size=3) == ["S42"]


def test_audit_handles_a_top_level_grounding_list():
    """A chat reply grounds the whole message, not a field inside it."""
    assert audit({"reply": "hello", "grounding": ["S7"]}, window_size=2) == ["S7"]
    assert audit({"reply": "hello", "grounding": ["S1"]}, window_size=2) == []


# --- Scrubbing ----------------------------------------------------------------

def test_scrub_resolves_valid_tags_and_drops_invented_ones():
    response = {
        "segments": [
            {"title": "real", "grounding": ["S1"]},
            {"title": "invented", "grounding": ["S99"]},
            {"title": "mixed", "grounding": ["S2", "S42"]},
        ]
    }
    scrubbed = scrub(response, window_chunk_ids=[501, 502, 503])
    got = [s["grounding"] for s in scrubbed["segments"]]

    assert got[0] == [501]
    # An entirely fabricated citation leaves the item honestly ungrounded rather
    # than citing something the professor never selected.
    assert got[1] == []
    assert got[2] == [502]


def test_scrub_with_no_retrieved_chunks_grounds_nothing():
    scrubbed = scrub({"segments": [{"grounding": ["S1", "S2"]}]}, window_chunk_ids=[])
    assert scrubbed["segments"][0]["grounding"] == []


def test_scrub_never_leaves_a_string_tag_behind():
    """Whatever reaches the database must be chunk ids, never model text."""
    response = {"segments": [{"grounding": ["S1", "S77", "p. 3"]}]}
    scrubbed = scrub(response, window_chunk_ids=[900, 901])
    assert scrubbed["segments"][0]["grounding"] == [900]


def test_scrub_does_not_mutate_the_input():
    response = {"segments": [{"grounding": ["S1"]}]}
    scrub(response, window_chunk_ids=[7])
    assert response["segments"][0]["grounding"] == ["S1"]


def test_scrub_preserves_non_citable_content():
    response = {"reply": "text", "action": "none", "args": {"duration_min": 90}}
    assert scrub(response, [1, 2]) == response


def test_scrub_reaches_nested_items():
    response = {"groups": {"activities": [{"title": "t", "grounding": ["S2"]}]}}
    scrubbed = scrub(response, window_chunk_ids=[11, 22])
    assert scrubbed["groups"]["activities"][0]["grounding"] == [22]


# --- Collecting what was cited ------------------------------------------------

def test_cited_chunk_ids_collects_from_everywhere():
    scrubbed = {
        "segments": [{"grounding": [5]}, {"grounding": []}],
        "misconceptions": [{"grounding": [9, 5]}],
        "grounding": [1],
    }
    assert cited_chunk_ids(scrubbed) == [1, 5, 9]


def test_cited_chunk_ids_of_an_ungrounded_response_is_empty():
    assert cited_chunk_ids({"segments": [{"grounding": []}]}) == []
