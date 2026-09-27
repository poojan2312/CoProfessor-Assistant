"""Applying a professor's edits to a lecture plan.

Lives in a service rather than a route handler because two callers need it: the
REST endpoint `PATCH /api/lectures/{id}/plan` and the chat action executor. If
each had its own copy, pinned-minute handling and version semantics would drift
apart and the chat would quietly behave differently from the buttons.

No model call happens here. An edited segment keeps whatever grounding it already
had - the professor's own words are simply marked as theirs.
"""
from __future__ import annotations

import copy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lecture, LecturePlan, PlanItem
from app.services.timealloc import allocate


class PlanEditError(ValueError):
    """The edit cannot be applied. Carries a message meant for the professor."""


def latest_plan(db: Session, lecture_id: int) -> LecturePlan | None:
    return db.execute(
        select(LecturePlan)
        .where(LecturePlan.lecture_id == lecture_id)
        .order_by(LecturePlan.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def apply_plan_edits(
    db: Session,
    lecture: Lecture,
    segment_edits: list,
    drop_ordinals: list[int],
) -> LecturePlan:
    """Store the professor's edits as a new plan version.

    `segment_edits` are objects with `ordinal` plus optional `title`, `body`,
    `kind` and `minutes` (any shape with those attributes - the REST schema and
    the chat action schema both qualify).
    """
    current = latest_plan(db, lecture.id)
    if current is None:
        raise PlanEditError("No plan has been generated for this lecture yet.")

    plan_json = copy.deepcopy(current.plan_json)
    segments = plan_json.get("segments") or []
    edits = {edit.ordinal: edit for edit in segment_edits}
    dropped = set(drop_ordinals or [])

    known = {segment.get("ordinal") for segment in segments}
    unknown = sorted((set(edits) | dropped) - known)
    if unknown:
        raise PlanEditError(
            f"This plan has segments 1-{len(segments)}; there is no segment "
            f"{', '.join(str(o) for o in unknown)}."
        )

    kept: list[dict] = []
    pinned: set[int] = set()
    for segment in segments:
        ordinal = segment.get("ordinal")
        if ordinal in dropped:
            continue
        edit = edits.get(ordinal)
        if edit is not None:
            for key in ("title", "body", "kind"):
                value = getattr(edit, key, None)
                if value is not None:
                    segment[key] = value
            minutes = getattr(edit, "minutes", None)
            if minutes is not None:
                segment["minutes"] = minutes
                pinned.add(ordinal)
            segment["edited_by_professor"] = True
        kept.append(segment)

    if not kept:
        raise PlanEditError("A plan must keep at least one segment.")

    rebalance(kept, lecture.duration_min, pinned)
    for new_ordinal, segment in enumerate(kept, start=1):
        segment["ordinal"] = new_ordinal

    plan_json["segments"] = kept
    plan_json["duration_min"] = lecture.duration_min
    plan_json["total_allocated_min"] = sum(s.get("minutes", 0) for s in kept)

    new_plan = LecturePlan(
        lecture_id=lecture.id,
        version=current.version + 1,
        plan_json=plan_json,
        model=f"{current.model} + professor edits",
        retrieved_chunk_ids=current.retrieved_chunk_ids,
    )
    db.add(new_plan)
    db.flush()
    for segment in kept:
        db.add(
            PlanItem(
                plan_id=new_plan.id,
                ordinal=segment["ordinal"],
                kind=segment.get("kind", "concept"),
                title=segment.get("title", ""),
                body=segment.get("body", ""),
                minutes=segment.get("minutes", 0),
                grounding=segment.get("grounding") or [],
                edited_by_professor=bool(segment.get("edited_by_professor")),
            )
        )
    db.commit()
    db.refresh(new_plan)
    return new_plan


def rebalance(segments: list[dict], duration_min: int, pinned: set[int]) -> None:
    """Refill the class hour after edits, respecting minutes the professor pinned.

    A professor who typed an explicit duration meant it, so those are left alone
    and only the remaining time is redistributed. If their pinned totals already
    exceed the hour we leave the numbers as typed - the UI shows the overrun
    rather than silently overriding what they asked for.
    """
    free_segments = [s for s in segments if s.get("ordinal") not in pinned]
    pinned_total = sum(
        s.get("minutes", 0) for s in segments if s.get("ordinal") in pinned
    )
    remaining = duration_min - pinned_total

    if not free_segments or remaining < len(free_segments):
        return

    weights = [max(s.get("minutes", 1), 1) for s in free_segments]
    for segment, minutes in zip(
        free_segments, allocate(weights, remaining, floor_minutes=1)
    ):
        segment["minutes"] = minutes
