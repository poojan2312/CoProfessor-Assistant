"""Planner pipeline tests.

The model is stubbed throughout: these assert what the system does with model
output, which is the part that has to be trustworthy regardless of what the model
returns on any given day. No network, no API key, no quota.
"""
from __future__ import annotations

import pytest

from app.models import LecturePlan, PlanItem
from app.prompts import lecture_plan as prompt_mod
from app.services import grounding, planner


def _plan(segments, **extra):
    base = {
        "topic": "CPU Scheduling",
        "summary": "A lecture on scheduling.",
        "learning_objectives": [],
        "prerequisites": [],
        "segments": segments,
        "misconceptions": [],
        "clarifications_needed": [],
    }
    base.update(extra)
    return base


@pytest.fixture
def stub_retrieval(monkeypatch, chunks):
    monkeypatch.setattr(planner, "retrieve", lambda db, lecture, top_k=None: chunks)
    return chunks


def _stub_llm(monkeypatch, responses):
    """Feed the planner a fixed sequence of model responses."""
    calls = {"prompts": []}
    queue = list(responses)

    def fake(prompt, response_schema, system_instruction=None, temperature=0.4):
        calls["prompts"].append(prompt)
        return queue.pop(0) if queue else queue_last

    queue_last = responses[-1]
    monkeypatch.setattr("app.services.llm.generate_json", fake)
    return calls


# --- Schema and enforcement wiring -------------------------------------------

def test_every_citable_schema_field_is_enforced():
    """Enforcement must reach every field the schema lets the model cite in.

    Checked against the real schema rather than a registry of field names, so a
    citable field added later cannot quietly escape the audit.
    """
    citable = [
        name
        for name, spec in prompt_mod.RESPONSE_SCHEMA["properties"].items()
        if spec.get("type") == "array"
        and "grounding" in spec.get("items", {}).get("properties", {})
    ]
    assert citable, "the lecture plan schema should have citable fields"

    for name in citable:
        response = {name: [{"grounding": ["S99"]}]}
        assert grounding.audit(response, window_size=3) == ["S99"], name


def test_schema_never_asks_the_model_for_minutes_or_pages():
    """If the model is never asked, it can never answer wrongly."""
    segment_props = prompt_mod.RESPONSE_SCHEMA["properties"]["segments"]["items"][
        "properties"
    ]
    assert "weight" in segment_props
    for forbidden in ("minutes", "page", "page_no", "source", "citation", "url"):
        assert forbidden not in segment_props


# --- Generation pipeline ------------------------------------------------------

def test_generated_plan_fits_the_class_exactly(db, lecture, stub_retrieval, monkeypatch):
    _stub_llm(
        monkeypatch,
        [_plan([
            {"kind": "recap", "title": "Recap", "body": "b", "weight": 1, "grounding": []},
            {"kind": "concept", "title": "RR", "body": "b", "weight": 5, "grounding": ["S1"]},
            {"kind": "check", "title": "Check", "body": "b", "weight": 2, "grounding": []},
        ])],
    )
    plan = planner.generate_plan(db, lecture)
    minutes = [s["minutes"] for s in plan.plan_json["segments"]]

    assert sum(minutes) == lecture.duration_min == 50
    assert plan.plan_json["total_allocated_min"] == 50
    assert all("weight" not in s for s in plan.plan_json["segments"])


@pytest.mark.parametrize("duration", [30, 50, 90])
def test_plan_fits_whatever_duration_the_professor_sets(
    db, lecture, stub_retrieval, monkeypatch, duration
):
    lecture.duration_min = duration
    db.commit()
    _stub_llm(
        monkeypatch,
        [_plan([
            {"kind": "concept", "title": "A", "body": "b", "weight": 3, "grounding": []},
            {"kind": "example", "title": "B", "body": "b", "weight": 2, "grounding": []},
        ])],
    )
    plan = planner.generate_plan(db, lecture)
    assert sum(s["minutes"] for s in plan.plan_json["segments"]) == duration


def test_fabricated_citation_triggers_a_corrective_retry(
    db, lecture, stub_retrieval, monkeypatch
):
    dirty = _plan([
        {"kind": "concept", "title": "A", "body": "b", "weight": 3, "grounding": ["S99"]}
    ])
    clean = _plan([
        {"kind": "concept", "title": "A", "body": "b", "weight": 3, "grounding": ["S1"]}
    ])
    calls = _stub_llm(monkeypatch, [dirty, clean])

    plan = planner.generate_plan(db, lecture)

    assert len(calls["prompts"]) == 2
    assert "Correction required" in calls["prompts"][1]
    assert "S99" in calls["prompts"][1]
    assert plan.plan_json["segments"][0]["grounding"] == [stub_retrieval[0].id]


def test_persistent_fabrication_degrades_to_ungrounded_not_false_citation(
    db, lecture, stub_retrieval, monkeypatch
):
    """The safety net: a model that keeps inventing gets published uncited."""
    dirty = _plan([
        {"kind": "concept", "title": "A", "body": "b", "weight": 3, "grounding": ["S99"]}
    ])
    _stub_llm(monkeypatch, [dirty, dirty])

    plan = planner.generate_plan(db, lecture)
    assert plan.plan_json["segments"][0]["grounding"] == []


def test_stored_grounding_is_chunk_ids_not_model_tags(
    db, lecture, stub_retrieval, monkeypatch
):
    _stub_llm(
        monkeypatch,
        [_plan([
            {"kind": "concept", "title": "A", "body": "b", "weight": 1, "grounding": ["S2"]}
        ])],
    )
    plan = planner.generate_plan(db, lecture)
    stored = db.query(PlanItem).filter_by(plan_id=plan.id).one()

    assert stored.grounding == [stub_retrieval[1].id]
    assert all(isinstance(g, int) for g in stored.grounding)


def test_invalid_segment_kind_is_normalised(db, lecture, stub_retrieval, monkeypatch):
    _stub_llm(
        monkeypatch,
        [_plan([
            {"kind": "interpretive-dance", "title": "A", "body": "b",
             "weight": 1, "grounding": []}
        ])],
    )
    plan = planner.generate_plan(db, lecture)
    assert plan.plan_json["segments"][0]["kind"] in PlanItem.KINDS


def test_clarifications_survive_to_the_professor(
    db, lecture, stub_retrieval, monkeypatch
):
    """Two-sided interaction: the assistant asks instead of assuming."""
    _stub_llm(
        monkeypatch,
        [_plan(
            [{"kind": "concept", "title": "A", "body": "b", "weight": 1, "grounding": []}],
            clarifications_needed=[
                {"field": "student_level", "question": "Have students seen interrupts?"}
            ],
        )],
    )
    plan = planner.generate_plan(db, lecture)
    assert plan.plan_json["clarifications_needed"][0]["field"] == "student_level"


def test_regenerating_adds_a_version_without_destroying_the_old_one(
    db, lecture, stub_retrieval, monkeypatch
):
    segments = [
        {"kind": "concept", "title": "A", "body": "b", "weight": 1, "grounding": []}
    ]
    _stub_llm(monkeypatch, [_plan(segments), _plan(segments)])

    first = planner.generate_plan(db, lecture)
    second = planner.generate_plan(db, lecture)

    assert (first.version, second.version) == (1, 2)
    assert db.query(LecturePlan).filter_by(lecture_id=lecture.id).count() == 2


# --- Retrieval isolation ------------------------------------------------------

def test_no_uploaded_material_means_no_citation_window(db, lecture, monkeypatch):
    """With nothing approved, retrieval returns nothing and nothing can be cited."""
    monkeypatch.setattr(planner, "retrieve", lambda db, lecture, top_k=None: [])
    _stub_llm(
        monkeypatch,
        [_plan([
            {"kind": "concept", "title": "A", "body": "b", "weight": 1, "grounding": ["S1"]}
        ])],
    )
    plan = planner.generate_plan(db, lecture)

    assert plan.retrieved_chunk_ids == []
    assert plan.plan_json["segments"][0]["grounding"] == []


def test_unapproved_sources_are_excluded_from_retrieval(db, course, chunks):
    """'Confine to limited sources', enforced in the query rather than the prompt."""
    assert planner.approved_source_ids(db, course.id)

    source = chunks[0].document.source
    source.status = "pending"
    db.commit()

    assert planner.approved_source_ids(db, course.id) == []
