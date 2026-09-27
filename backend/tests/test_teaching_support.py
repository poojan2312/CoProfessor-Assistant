"""Week 3 teaching support generation."""
from __future__ import annotations

import pytest

from app.models import TeachingSupport
from app.prompts import teaching_support as prompt_mod
from app.services import grounding, planner
from app.services import teaching_support as service


def _support(**overrides):
    base = {
        "industry_applications": [
            {"title": "Container schedulers", "text": "...", "grounding": []}
        ],
        "activities": [
            {
                "title": "Trace the queue",
                "format": "pair",
                "minutes": 10,
                "instructions": "...",
                "grounding": ["S1"],
            }
        ],
        "interactive_techniques": [{"text": "...", "grounding": []}],
        "alt_explanations": [
            {"concept": "Quantum", "explanation": "...", "analogy": "...", "grounding": []}
        ],
    }
    base.update(overrides)
    return base


@pytest.fixture
def stub(monkeypatch, chunks):
    monkeypatch.setattr(
        planner, "retrieve_for_query", lambda db, course_id, query, top_k=None: chunks
    )
    state = {"responses": [_support()], "prompts": []}

    def fake(prompt, response_schema, system_instruction=None, temperature=0.4):
        state["prompts"].append(prompt)
        queue = state["responses"]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("app.services.llm.generate_json", fake)
    return state


# --- Schema -------------------------------------------------------------------

def test_every_group_is_citable():
    """All four groups carry grounding, so all four are enforced."""
    for name, spec in prompt_mod.RESPONSE_SCHEMA["properties"].items():
        assert "grounding" in spec["items"]["properties"], name


def test_the_schema_never_asks_for_a_page_or_a_source():
    flat = str(prompt_mod.RESPONSE_SCHEMA)
    for forbidden in ("'page'", "'page_no'", "'url'", "'source_title'", "'isbn'"):
        assert forbidden not in flat


def test_activity_formats_are_a_closed_set():
    formats = prompt_mod.RESPONSE_SCHEMA["properties"]["activities"]["items"][
        "properties"
    ]["format"]
    assert formats["enum"] == prompt_mod.ACTIVITY_FORMATS


# --- Generation ---------------------------------------------------------------

def test_it_stores_a_version(db, lecture, stub):
    row = service.generate(db, lecture)

    assert row.version == 1
    assert db.query(TeachingSupport).filter_by(lecture_id=lecture.id).count() == 1
    assert row.retrieved_chunk_ids


def test_regenerating_adds_a_version(db, lecture, stub):
    service.generate(db, lecture)
    second = service.generate(db, lecture)

    assert second.version == 2
    assert service.latest(db, lecture.id).version == 2


def test_tags_become_chunk_ids(db, lecture, stub, chunks):
    row = service.generate(db, lecture)
    assert row.support_json["activities"][0]["grounding"] == [chunks[0].id]


def test_a_fabricated_citation_is_stripped(db, lecture, stub):
    """Enforcement reaches teaching support without registering its field names."""
    stub["responses"] = [
        _support(
            industry_applications=[
                {"title": "x", "text": "y", "grounding": ["S99"]}
            ]
        )
    ]
    row = service.generate(db, lecture)
    assert row.support_json["industry_applications"][0]["grounding"] == []


def test_a_fabricated_citation_triggers_a_corrective_retry(db, lecture, stub):
    dirty = _support(interactive_techniques=[{"text": "t", "grounding": ["S42"]}])
    stub["responses"] = [dirty, _support()]

    service.generate(db, lecture)

    assert len(stub["prompts"]) == 2
    assert "Correction required" in stub["prompts"][1]
    assert "S42" in stub["prompts"][1]


def test_an_unusable_activity_format_is_normalised(db, lecture, stub):
    stub["responses"] = [
        _support(
            activities=[
                {
                    "title": "t",
                    "format": "interpretive-dance",
                    "minutes": 900,
                    "instructions": "i",
                    "grounding": [],
                }
            ]
        )
    ]
    activity = service.generate(db, lecture).support_json["activities"][0]

    assert activity["format"] in prompt_mod.ACTIVITY_FORMATS
    assert 1 <= activity["minutes"] <= 60


def test_the_lecture_plan_is_given_as_context(db, lecture, plan, stub):
    service.generate(db, lecture)
    assert "Round robin" in stub["prompts"][0]


def test_it_works_before_a_plan_exists(db, lecture, stub):
    service.generate(db, lecture)
    assert "No lecture plan has been generated yet" in stub["prompts"][0]


def test_with_no_material_nothing_is_cited(db, lecture, monkeypatch, stub):
    monkeypatch.setattr(
        planner, "retrieve_for_query", lambda db, course_id, query, top_k=None: []
    )
    row = service.generate(db, lecture)

    assert row.retrieved_chunk_ids == []
    assert grounding.cited_chunk_ids(row.support_json) == []


# --- Plan outline helper ------------------------------------------------------

def test_plan_outline_renders_segments(plan):
    lines = service.plan_outline(plan.plan_json)
    assert len(lines) == 4
    assert "Round robin" in lines[1]


def test_plan_outline_of_nothing_is_empty():
    assert service.plan_outline(None) == []
    assert service.plan_outline({}) == []
