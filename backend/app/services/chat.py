"""One turn of the professor's conversation.

Shape of a turn: retrieve -> one model call -> enforce citations -> validate the
requested action -> execute it through existing services -> persist both messages.

The security boundary is step four. Whatever the model asks for is re-validated
through the same Pydantic schemas the REST API uses and executed through the same
service functions, so chat can do nothing the buttons could not do. An action the
schemas reject is refused with an explanation rather than partly applied.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatMessage, Course, Lecture
from app.prompts import chat as prompt_mod
from app.schemas import CourseUpdate, LectureCreate, LectureUpdate, PlanEdit
from app.services import grounding, lecture_ops, plan_edits, planner, teaching_support, resource_verification

log = logging.getLogger(__name__)

HISTORY_TURNS = 10
NO_ACTION = "none"


class ActionRefused(Exception):
    """The model asked for something invalid. The message is shown to the professor."""


@dataclass
class TurnResult:
    message: ChatMessage
    focus_lecture_id: int | None
    plan_changed: bool
    lecture_changed: bool
    course_changed: bool
    support_changed: bool


# --- Context assembly ---------------------------------------------------------

def _history(db: Session, course_id: int) -> list[tuple[str, str]]:
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.course_id == course_id)
        .order_by(ChatMessage.id.desc())
        .limit(HISTORY_TURNS)
    ).scalars().all()
    return [(m.role, m.content) for m in reversed(rows)]


def _lecture_lines(db: Session, course_id: int) -> list[str]:
    rows = db.execute(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.seq_no)
    ).scalars()
    return [f"{l.seq_no}. {l.topic} ({l.duration_min} min)" for l in rows]


# --- Argument hygiene ---------------------------------------------------------

def _clean(args: dict | None) -> dict:
    """Drop fields the model filled in with nothing.

    Structured-output models tend to emit every property in the schema, including
    ones the instructions told them to omit. Passing an empty string through to
    `update_lecture` would blank the professor's topic, so empties never count as
    an intended change.
    """
    if not isinstance(args, dict):
        return {}
    out = {}
    for key, value in args.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        out[key] = value
    return out


def _subset(args: dict, keys: tuple[str, ...]) -> dict:
    return {k: v for k, v in args.items() if k in keys}


# --- Action execution ---------------------------------------------------------

def _execute(
    db: Session, course: Course, lecture: Lecture | None, action: str, args: dict
) -> tuple[str, Lecture | None, set[str]]:
    """Run the requested action. Returns (summary, focus lecture, what changed)."""
    changed: set[str] = set()

    if action in (NO_ACTION, "", None):
        return "", lecture, changed

    if action == "update_course":
        fields = _subset(
            args,
            ("title", "code", "objectives", "student_level", "lecture_duration_min"),
        )
        if not fields:
            raise ActionRefused("no course fields were given to change")
        payload = _validate(CourseUpdate, fields)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(course, key, value)
        db.commit()
        changed.add("course")
        return f"Updated the course ({', '.join(sorted(fields))}).", lecture, changed

    if action == "create_lecture":
        fields = _subset(args, ("topic", "duration_min", "notes"))
        if not fields.get("topic"):
            raise ActionRefused("a lecture needs a topic")
        payload = _validate(LectureCreate, fields)
        created = lecture_ops.create_lecture(
            db, course, payload.model_dump(exclude_unset=True)
        )
        changed.add("lecture")
        return (
            f"Added lecture {created.seq_no}: {created.topic} "
            f"({created.duration_min} min).",
            created,
            changed,
        )

    # Everything below needs a lecture in focus.
    if lecture is None:
        raise ActionRefused("no lecture is open, so I could not tell which one you meant")

    if action == "update_lecture":
        fields = _subset(
            args, ("topic", "duration_min", "notes", "student_level_override")
        )
        if not fields:
            raise ActionRefused("no lecture fields were given to change")
        payload = _validate(LectureUpdate, fields)
        lecture_ops.update_lecture(
            db, lecture, payload.model_dump(exclude_unset=True)
        )
        changed.add("lecture")
        summary = f"Updated the lecture ({', '.join(sorted(fields))})."

        # A duration change leaves the stored plan adding up to the old length.
        # Re-apportion it so the panel never shows 50/90.
        if "duration_min" in fields and plan_edits.latest_plan(db, lecture.id):
            plan_edits.apply_plan_edits(db, lecture, [], [])
            changed.add("plan")
            summary += f" The plan now fits {lecture.duration_min} minutes."
        return summary, lecture, changed

    if action == "generate_plan":
        planner.generate_plan(db, lecture)
        changed.update({"plan"})
        return "Generated a new lecture plan.", lecture, changed

    if action == "generate_teaching_support":
        teaching_support.generate(db, lecture)
        changed.add("support")
        return "Generated teaching support for this lecture.", lecture, changed

    if action == "recommend_resources":
        resources = args.get("resources") or []
        if not resources:
            raise ActionRefused("no resources were provided to recommend")
        added = resource_verification.verify_and_add_resources(db, course, resources)
        if not added:
            raise ActionRefused("none of the recommended resources could be verified (they might be broken links or invalid identifiers)")
        changed.add("course")
        return f"Added verified external resources: {', '.join(added)}.", lecture, changed

    if action == "edit_segments":
        segments = args.get("segments") or []
        if not segments:
            raise ActionRefused("no segment changes were given")
        payload = _validate(PlanEdit, {"segments": segments})
        _apply_edits(db, lecture, payload)
        changed.add("plan")
        ordinals = ", ".join(str(s.ordinal) for s in payload.segments)
        return f"Edited segment {ordinals}.", lecture, changed

    if action == "drop_segments":
        ordinals = args.get("drop_ordinals") or []
        if not ordinals:
            raise ActionRefused("no segments were named to remove")
        payload = _validate(PlanEdit, {"drop_ordinals": ordinals})
        _apply_edits(db, lecture, payload)
        changed.add("plan")
        listed = ", ".join(str(o) for o in payload.drop_ordinals)
        return f"Removed segment {listed} and re-balanced the time.", lecture, changed

    raise ActionRefused(f"'{action}' is not something I can do")


def _validate(model, fields: dict):
    try:
        return model(**fields)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "input"
        raise ActionRefused(f"{where}: {first['msg']}") from exc


def _apply_edits(db: Session, lecture: Lecture, payload: PlanEdit) -> None:
    try:
        plan_edits.apply_plan_edits(
            db, lecture, payload.segments, payload.drop_ordinals
        )
    except plan_edits.PlanEditError as exc:
        raise ActionRefused(str(exc)) from exc


# --- The turn -----------------------------------------------------------------

def send(
    db: Session, course: Course, message: str, lecture: Lecture | None
) -> TurnResult:
    from app.services.llm import generate_json

    db.add(
        ChatMessage(
            course_id=course.id,
            lecture_id=lecture.id if lecture else None,
            role="professor",
            content=message,
        )
    )
    db.commit()

    chunks = planner.retrieve_for_query(db, course.id, message)
    window_chunk_ids = [c.id for c in chunks]

    current_plan = plan_edits.latest_plan(db, lecture.id) if lecture else None
    prompt = prompt_mod.build_prompt(
        course_title=course.title,
        course_code=course.code,
        objectives=course.objectives,
        student_level=course.student_level,
        lectures=_lecture_lines(db, course.id),
        focus_lecture=(
            f"Lecture {lecture.seq_no}: {lecture.topic} ({lecture.duration_min} min)"
            if lecture
            else None
        ),
        plan_outline=teaching_support.plan_outline(
            current_plan.plan_json if current_plan else None
        ),
        has_support=bool(lecture and teaching_support.latest(db, lecture.id)),
        history=_history(db, course.id)[:-1],  # exclude the message just stored
        message=message,
        excerpts=[f"[S{i}] {c.text}" for i, c in enumerate(chunks, start=1)],
    )

    response = generate_json(
        prompt=prompt,
        response_schema=prompt_mod.RESPONSE_SCHEMA,
        system_instruction=prompt_mod.SYSTEM_INSTRUCTION,
        temperature=0.3,
    )
    response = grounding.scrub(response, window_chunk_ids)

    reply = (response.get("reply") or "").strip()
    clarification = (response.get("clarification") or "").strip()
    action = response.get("action") or NO_ACTION
    args = _clean(response.get("args"))

    # A clarification means the model is unsure, so nothing gets changed on the
    # strength of a guess.
    if clarification:
        action = NO_ACTION

    summary, focus, changed = "", lecture, set()
    record: dict | None = None
    try:
        summary, focus, changed = _execute(db, course, lecture, action, args)
        if summary:
            record = {"action": action, "summary": summary}
    except ActionRefused as exc:
        log.info("chat action refused (%s): %s", action, exc)
        reply = f"{reply}\n\nI did not make that change - {exc}.".strip()
        record = {"action": action, "refused": str(exc)}

    assistant = ChatMessage(
        course_id=course.id,
        lecture_id=focus.id if focus else None,
        role="assistant",
        content=reply or "(no reply)",
        citations=grounding.cited_chunk_ids(response),
        action=record,
        clarification=clarification,
    )
    db.add(assistant)
    db.commit()
    db.refresh(assistant)

    return TurnResult(
        message=assistant,
        focus_lecture_id=focus.id if focus else None,
        plan_changed="plan" in changed,
        lecture_changed="lecture" in changed,
        course_changed="course" in changed,
        support_changed="support" in changed,
    )
