"""The professor's chat turn.

The model is stubbed throughout. What is under test is what the system does with
a model response - which is the part that has to hold regardless of what the
model says on a given day.
"""
from __future__ import annotations

import pytest

from app.models import ChatMessage, LecturePlan
from app.services import chat, planner


def _response(**overrides):
    base = {
        "reply": "Right.",
        "grounding": [],
        "action": "none",
        "args": {},
        "clarification": "",
    }
    base.update(overrides)
    return base


@pytest.fixture
def stub(monkeypatch, chunks):
    """Stub retrieval and the model. Returns a handle for setting the response."""
    monkeypatch.setattr(
        planner, "retrieve_for_query", lambda db, course_id, query, top_k=None: chunks
    )

    state = {"response": _response(), "prompts": []}

    def fake(prompt, response_schema, system_instruction=None, temperature=0.4):
        state["prompts"].append(prompt)
        return state["response"]

    monkeypatch.setattr("app.services.llm.generate_json", fake)
    return state


# --- Conversation -------------------------------------------------------------

def test_both_messages_are_stored(db, course, stub):
    chat.send(db, course, "Hello", None)
    rows = db.query(ChatMessage).order_by(ChatMessage.id).all()

    assert [r.role for r in rows] == ["professor", "assistant"]
    assert rows[0].content == "Hello"


def test_earlier_turns_are_replayed_into_the_prompt(db, course, stub):
    """Phase 1 chat-continuity test: the assistant keeps the thread's context."""
    chat.send(db, course, "Cover paging first", None)
    chat.send(db, course, "Why?", None)

    assert "Cover paging first" in stub["prompts"][1]


def test_the_current_message_is_not_duplicated_into_history(db, course, stub):
    chat.send(db, course, "Only once please", None)
    prompt = stub["prompts"][0]
    assert prompt.count("Only once please") == 1


def test_the_open_lecture_and_its_plan_reach_the_prompt(db, course, lecture, plan, stub):
    chat.send(db, course, "Tighten this up", lecture)
    prompt = stub["prompts"][0]

    assert lecture.topic in prompt
    assert "Round robin" in prompt


def test_with_no_lecture_open_the_prompt_says_so(db, course, stub):
    chat.send(db, course, "Shorten it", None)
    assert "ask which one" in stub["prompts"][0]


# --- Grounding ----------------------------------------------------------------

def test_a_grounded_reply_keeps_its_citation(db, course, stub, chunks):
    stub["response"] = _response(grounding=["S1"])
    result = chat.send(db, course, "What is round robin?", None)
    assert result.message.citations == [chunks[0].id]


def test_a_fabricated_citation_is_stripped_from_a_reply(db, course, stub):
    """The professor's core complaint, applied to chat."""
    stub["response"] = _response(grounding=["S99"])
    result = chat.send(db, course, "What is round robin?", None)
    assert result.message.citations == []


def test_a_model_written_page_reference_is_not_a_citation(db, course, stub):
    stub["response"] = _response(grounding=["Silberschatz p. 214"])
    result = chat.send(db, course, "Where is this covered?", None)
    assert result.message.citations == []


# --- Acting -------------------------------------------------------------------

def test_it_changes_the_lecture_when_asked(db, course, lecture, stub):
    stub["response"] = _response(action="update_lecture", args={"duration_min": 90})
    result = chat.send(db, course, "Make this 90 minutes", lecture)

    db.refresh(lecture)
    assert lecture.duration_min == 90
    assert result.lecture_changed is True
    assert result.message.action["action"] == "update_lecture"


def test_a_duration_change_re_fits_the_existing_plan(db, course, lecture, plan, stub):
    """Otherwise the panel would show a plan totalling the old class length."""
    stub["response"] = _response(action="update_lecture", args={"duration_min": 90})
    result = chat.send(db, course, "Make this 90 minutes", lecture)

    latest = (
        db.query(LecturePlan)
        .filter_by(lecture_id=lecture.id)
        .order_by(LecturePlan.version.desc())
        .first()
    )
    assert sum(s["minutes"] for s in latest.plan_json["segments"]) == 90
    assert result.plan_changed is True


def test_it_drops_a_segment_when_asked(db, course, lecture, plan, stub):
    stub["response"] = _response(action="drop_segments", args={"drop_ordinals": [3]})
    result = chat.send(db, course, "Drop segment 3", lecture)

    latest = (
        db.query(LecturePlan)
        .filter_by(lecture_id=lecture.id)
        .order_by(LecturePlan.version.desc())
        .first()
    )
    assert len(latest.plan_json["segments"]) == 3
    assert sum(s["minutes"] for s in latest.plan_json["segments"]) == lecture.duration_min
    assert result.plan_changed is True


def test_it_creates_a_lecture_and_moves_focus_to_it(db, course, stub):
    stub["response"] = _response(action="create_lecture", args={"topic": "Deadlock"})
    result = chat.send(db, course, "Add a lecture on deadlock", None)

    assert result.focus_lecture_id is not None
    assert result.lecture_changed is True


def test_most_turns_change_nothing(db, course, lecture, plan, stub):
    result = chat.send(db, course, "What should I emphasise?", lecture)
    assert (result.plan_changed, result.lecture_changed) == (False, False)
    assert result.message.action is None


# --- Refusing bad actions -----------------------------------------------------

def test_an_out_of_range_value_is_refused_not_applied(db, course, lecture, stub):
    """LectureUpdate caps duration at 300; chat must not bypass that."""
    stub["response"] = _response(action="update_lecture", args={"duration_min": 9999})
    result = chat.send(db, course, "Make it 9999 minutes", lecture)

    db.refresh(lecture)
    assert lecture.duration_min == 50
    assert "did not make that change" in result.message.content


def test_a_segment_that_does_not_exist_is_refused(db, course, lecture, plan, stub):
    stub["response"] = _response(action="drop_segments", args={"drop_ordinals": [99]})
    result = chat.send(db, course, "Drop segment 99", lecture)

    assert db.query(LecturePlan).filter_by(lecture_id=lecture.id).count() == 1
    assert "did not make that change" in result.message.content


def test_an_edit_with_no_lecture_open_is_refused(db, course, stub):
    stub["response"] = _response(action="update_lecture", args={"duration_min": 90})
    result = chat.send(db, course, "Make it 90", None)
    assert "no lecture is open" in result.message.content


def test_an_unknown_action_is_refused(db, course, lecture, stub):
    stub["response"] = _response(action="delete_everything", args={})
    result = chat.send(db, course, "wipe it", lecture)
    assert "did not make that change" in result.message.content


def test_empty_strings_are_not_treated_as_edits(db, course, lecture, stub):
    """Structured-output models fill in every property; blanks must not erase data."""
    stub["response"] = _response(
        action="update_lecture", args={"topic": "", "notes": "", "duration_min": 90}
    )
    chat.send(db, course, "Make it 90 minutes", lecture)

    db.refresh(lecture)
    assert lecture.topic == "CPU Scheduling"  # not blanked
    assert lecture.duration_min == 90


def test_a_refusal_still_records_the_turn(db, course, lecture, stub):
    stub["response"] = _response(action="update_lecture", args={"duration_min": -5})
    chat.send(db, course, "Make it -5 minutes", lecture)

    assistant = db.query(ChatMessage).filter_by(role="assistant").one()
    assert assistant.action["refused"]


# --- Asking back --------------------------------------------------------------

def test_a_clarification_is_surfaced(db, course, lecture, stub):
    stub["response"] = _response(clarification="Which segment did you mean?")
    result = chat.send(db, course, "Shorten that bit", lecture)
    assert result.message.clarification == "Which segment did you mean?"


def test_nothing_is_changed_while_the_assistant_is_still_unsure(
    db, course, lecture, stub
):
    """Two-sided interaction: ask, do not act on a guess."""
    stub["response"] = _response(
        action="update_lecture",
        args={"duration_min": 90},
        clarification="Did you mean this lecture or the next one?",
    )
    chat.send(db, course, "Make it longer", lecture)

    db.refresh(lecture)
    assert lecture.duration_min == 50
