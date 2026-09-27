"""The shared plan-edit service.

Both the REST endpoint and the chat action executor go through this, so its
behaviour is pinned here rather than only at the HTTP layer.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models import LecturePlan, PlanItem
from app.services import plan_edits


@dataclass
class Edit:
    """Stands in for schemas.SegmentUpdate; the service is duck-typed on purpose."""

    ordinal: int
    title: str | None = None
    body: str | None = None
    kind: str | None = None
    minutes: int | None = None


def _minutes(plan: LecturePlan) -> list[int]:
    return [s["minutes"] for s in plan.plan_json["segments"]]


def test_edit_creates_a_new_version_and_keeps_the_old_one(db, lecture, plan):
    updated = plan_edits.apply_plan_edits(db, lecture, [Edit(2, title="Renamed")], [])

    assert updated.version == 2
    assert db.query(LecturePlan).filter_by(lecture_id=lecture.id).count() == 2
    # The original text is still on disk, untouched.
    assert plan.plan_json["segments"][1]["title"] == "Round robin"


def test_edited_segment_is_flagged_as_the_professors(db, lecture, plan):
    updated = plan_edits.apply_plan_edits(db, lecture, [Edit(2, title="Mine")], [])
    segment = updated.plan_json["segments"][1]

    assert segment["title"] == "Mine"
    assert segment["edited_by_professor"] is True


def test_editing_prose_does_not_disturb_its_citation(db, lecture, plan, chunks):
    """The professor rewording a segment does not make it uncited."""
    updated = plan_edits.apply_plan_edits(db, lecture, [Edit(2, body="New words")], [])
    assert updated.plan_json["segments"][1]["grounding"] == [chunks[0].id]


def test_dropping_a_segment_renumbers_and_refills_the_hour(db, lecture, plan):
    updated = plan_edits.apply_plan_edits(db, lecture, [], [3])

    assert [s["ordinal"] for s in updated.plan_json["segments"]] == [1, 2, 3]
    assert sum(_minutes(updated)) == lecture.duration_min


def test_pinned_minutes_are_respected_exactly(db, lecture, plan):
    updated = plan_edits.apply_plan_edits(db, lecture, [Edit(1, minutes=25)], [])

    assert updated.plan_json["segments"][0]["minutes"] == 25
    assert sum(_minutes(updated)) == lecture.duration_min


def test_a_duration_change_is_absorbed_by_an_empty_edit(db, lecture, plan):
    """Re-apportion after the class length changes, without touching content."""
    lecture.duration_min = 90
    db.commit()

    updated = plan_edits.apply_plan_edits(db, lecture, [], [])

    assert sum(_minutes(updated)) == 90
    assert updated.plan_json["duration_min"] == 90
    assert [s["title"] for s in updated.plan_json["segments"]] == [
        "Recap", "Round robin", "Worked example", "Wrap up"
    ]


def test_plan_items_are_written_for_the_new_version(db, lecture, plan):
    updated = plan_edits.apply_plan_edits(db, lecture, [], [4])
    items = db.query(PlanItem).filter_by(plan_id=updated.id).all()

    assert len(items) == 3
    assert sorted(i.ordinal for i in items) == [1, 2, 3]


def test_removing_every_segment_is_refused(db, lecture, plan):
    with pytest.raises(plan_edits.PlanEditError):
        plan_edits.apply_plan_edits(db, lecture, [], [1, 2, 3, 4])


def test_editing_a_segment_that_does_not_exist_is_refused(db, lecture, plan):
    """Guards the chat path, where an ordinal can be a model's guess."""
    with pytest.raises(plan_edits.PlanEditError) as exc:
        plan_edits.apply_plan_edits(db, lecture, [Edit(99, title="x")], [])
    assert "99" in str(exc.value)


def test_dropping_a_segment_that_does_not_exist_is_refused(db, lecture, plan):
    with pytest.raises(plan_edits.PlanEditError):
        plan_edits.apply_plan_edits(db, lecture, [], [42])


def test_a_refused_edit_writes_nothing(db, lecture, plan):
    with pytest.raises(plan_edits.PlanEditError):
        plan_edits.apply_plan_edits(db, lecture, [Edit(99)], [])
    assert db.query(LecturePlan).filter_by(lecture_id=lecture.id).count() == 1


def test_editing_without_a_plan_is_refused(db, lecture):
    with pytest.raises(plan_edits.PlanEditError):
        plan_edits.apply_plan_edits(db, lecture, [], [])
