"""Week 5: schedule re-calibration.

Phase 1 re-calibration test: "Create an initial course schedule and then
introduce a missed lecture or holiday. Verify that the remaining schedule,
topics, and time allocation are recalculated correctly."

Everything here is deterministic, so these tests need no model stub except the
chat ones at the bottom.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.models import Lecture
from app.schemas import BlockedDate, RecalibrateRequest
from app.services import chat, planner, schedule
from app.services.plan_edits import latest_plan

MON = date(2026, 10, 5)  # a Monday
WED = date(2026, 10, 7)
TODAY = date(2026, 10, 1)


@pytest.fixture
def calendar(db, course):
    """Course meets Mondays and Wednesdays from 5 Oct 2026, no end date."""
    course.start_date = MON
    course.meeting_days = [0, 2]
    db.commit()
    return course


def add_lectures(db, course, seqs, duration=50):
    rows = [
        Lecture(course_id=course.id, seq_no=s, topic=f"Topic {s}", duration_min=duration)
        for s in seqs
    ]
    db.add_all(rows)
    db.commit()
    return rows


def run(db, course, *, apply=True, today=TODAY, **fields):
    request = RecalibrateRequest(apply=apply, **fields)
    proposal = schedule.propose(
        course, schedule.lectures_of(db, course.id), request, today=today
    )
    if apply:
        schedule.apply(db, course, proposal)
    return proposal


def dates(db, course) -> dict[int, date | None]:
    db.expire_all()
    return {l.seq_no: l.scheduled_date for l in schedule.lectures_of(db, course.id)}


# --- Building the schedule ----------------------------------------------------

def test_class_dates_skip_non_class_days_and_blocked_dates():
    got = schedule.class_dates(MON, date(2026, 10, 14), [0, 2], {WED})
    assert got == [MON, date(2026, 10, 12), date(2026, 10, 14)]


def test_initial_schedule_follows_class_days_in_lecture_order(db, calendar):
    add_lectures(db, calendar, [1, 2, 3, 4])
    run(db, calendar, from_date=MON)
    assert dates(db, calendar) == {
        1: MON, 2: WED, 3: date(2026, 10, 12), 4: date(2026, 10, 14),
    }


def test_missing_class_days_is_refused_not_guessed(db, course):
    """Two-sided interaction: no calendar means ask, not assume."""
    course.start_date = MON
    db.commit()
    add_lectures(db, course, [1])
    with pytest.raises(schedule.ScheduleError, match="days of the week"):
        run(db, course)


# --- Disruptions ----------------------------------------------------------------

def test_holiday_shifts_the_remaining_lectures_and_keeps_their_order(db, calendar):
    add_lectures(db, calendar, [1, 2, 3])
    run(db, calendar, from_date=MON)

    run(db, calendar, from_date=MON, blocked_dates=[BlockedDate(date=WED, reason="Dussehra")])

    assert dates(db, calendar) == {1: MON, 2: date(2026, 10, 12), 3: date(2026, 10, 14)}
    assert {"date": "2026-10-07", "reason": "Dussehra"} in calendar.blocked_dates


def test_missed_lecture_is_still_taught_and_its_date_is_blocked(db, calendar):
    rows = add_lectures(db, calendar, [1, 2, 3])
    run(db, calendar, from_date=MON)
    rows[0].status = "delivered"
    db.commit()

    run(db, calendar, missed_seq_nos=[2], today=date(2026, 10, 8))

    assert dates(db, calendar) == {1: MON, 2: date(2026, 10, 12), 3: date(2026, 10, 14)}
    assert any(b["date"] == "2026-10-07" for b in calendar.blocked_dates)


def test_delivered_lectures_never_move(db, calendar):
    rows = add_lectures(db, calendar, [1, 2])
    run(db, calendar, from_date=MON)
    rows[0].status = "delivered"
    db.commit()

    run(db, calendar, from_date=MON, blocked_dates=[BlockedDate(date=MON)])

    assert dates(db, calendar)[1] == MON

def test_new_lecture_takes_the_next_free_date_without_double_booking(db, calendar):
    rows = add_lectures(db, calendar, [1, 2])
    run(db, calendar, from_date=MON)  # 1: Mon 5 Oct, 2: Wed 7 Oct
    rows[0].status = "delivered"
    db.commit()
    add_lectures(db, calendar, [3])

    run(db, calendar, today=date(2026, 10, 4))

    assert dates(db, calendar) == {1: MON, 2: WED, 3: date(2026, 10, 12)}

def test_preview_changes_nothing(db, calendar):
    add_lectures(db, calendar, [1, 2])
    proposal = run(db, calendar, apply=False, from_date=MON)

    assert [g.new_date for g in proposal.groups] == [MON, WED]
    assert dates(db, calendar) == {1: None, 2: None}
    assert calendar.blocked_dates in (None, [])


# --- Time allocation after a change ---------------------------------------------

def test_shorter_classes_reapportion_an_existing_plan(db, calendar, lecture, plan):
    run(db, calendar, from_date=MON, new_duration_min=40)

    db.expire_all()
    new_plan = latest_plan(db, lecture.id)
    assert new_plan.version == plan.version + 1
    assert lecture.duration_min == 40
    assert sum(s["minutes"] for s in new_plan.plan_json["segments"]) == 40
    assert calendar.lecture_duration_min == 40


def test_too_few_classes_merges_lectures_and_the_merged_plan_fits(db, calendar, lecture, plan):
    add_lectures(db, calendar, [2])
    calendar.end_date = MON  # only one class left for two lectures
    db.commit()

    proposal = run(db, calendar, from_date=MON)

    assert proposal.groups[0].seq_nos == [1, 2]
    db.expire_all()
    absorbed = db.query(Lecture).filter_by(course_id=calendar.id, seq_no=2).one()
    assert absorbed.status == "merged" and absorbed.scheduled_date is None
    assert lecture.topic == "CPU Scheduling + Topic 2"
    merged_plan = latest_plan(db, lecture.id)
    assert sum(s["minutes"] for s in merged_plan.plan_json["segments"]) == lecture.duration_min


def test_spare_classes_are_reported_not_filled(db, calendar):
    add_lectures(db, calendar, [1])
    calendar.end_date = date(2026, 10, 14)
    db.commit()

    proposal = run(db, calendar, apply=False, from_date=MON)

    assert len(proposal.spare_dates) == 3
    assert any("free" in w for w in proposal.warnings)


# --- Through the chat -----------------------------------------------------------

@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(
        planner, "retrieve_for_query", lambda db, course_id, query, top_k=None: []
    )
    state = {"response": None}

    def fake(prompt, response_schema, system_instruction=None, temperature=0.4):
        return state["response"]

    monkeypatch.setattr("app.services.llm.generate_json", fake)
    return state


def _reply(apply: bool) -> dict:
    return {
        "reply": "Wednesday is a holiday.",
        "grounding": [],
        "action": "recalibrate_schedule",
        "args": {
            "blocked_dates": [{"date": "2026-10-07", "reason": "holiday"}],
            "from_date": "2026-10-05",
            "apply": apply,
        },
        "clarification": "",
    }


def test_chat_previews_first_and_applies_only_when_told(db, calendar, stub):
    add_lectures(db, calendar, [1, 2])
    run(db, calendar, from_date=MON)

    stub["response"] = _reply(apply=False)
    result = chat.send(db, calendar, "No class on Wednesday", None)
    assert "Preview" in result.message.action["summary"]
    assert dates(db, calendar)[2] == WED

    stub["response"] = _reply(apply=True)
    result = chat.send(db, calendar, "Yes, apply it", None)
    assert result.lecture_changed
    assert dates(db, calendar)[2] == date(2026, 10, 12)