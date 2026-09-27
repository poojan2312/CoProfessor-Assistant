"""Week 3 teaching support generation.

Mirrors the planner: retrieve a window of approved passages, generate against it,
enforce the citation contract, then persist a new version.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Lecture, TeachingSupport
from app.prompts import teaching_support as prompt_mod
from app.services import grounding, planner

log = logging.getLogger(__name__)

MAX_GENERATION_ATTEMPTS = 2  # one honest try, one corrective retry


def latest(db: Session, lecture_id: int) -> TeachingSupport | None:
    return db.execute(
        select(TeachingSupport)
        .where(TeachingSupport.lecture_id == lecture_id)
        .order_by(TeachingSupport.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def plan_outline(plan_json: dict | None) -> list[str]:
    """A compact rendering of the lecture plan for use as prompt context."""
    if not plan_json:
        return []
    return [
        f"{s.get('ordinal')}. [{s.get('kind', 'concept')}] {s.get('title', '')}"
        f" ({s.get('minutes', 0)} min)"
        for s in plan_json.get("segments") or []
    ]


def generate(db: Session, lecture: Lecture) -> TeachingSupport:
    from app.services.llm import generate_json

    settings = get_settings()
    course = lecture.course

    # Bias retrieval towards the parts of the material that discuss applications
    # and worked examples, not just the topic definition.
    query = " ".join(
        part
        for part in (
            lecture.topic,
            course.title,
            "examples applications practice exercises",
        )
        if part
    )
    chunks = planner.retrieve_for_query(db, course.id, query)
    window_chunk_ids = [c.id for c in chunks]
    excerpts = [f"[S{i}] {c.text}" for i, c in enumerate(chunks, start=1)]

    current_plan = next(reversed(lecture.plans), None) if lecture.plans else None
    base_prompt = prompt_mod.build_prompt(
        course_title=course.title,
        objectives=course.objectives,
        student_level=lecture.student_level_override or course.student_level,
        topic=lecture.topic,
        duration_min=lecture.duration_min,
        plan_outline=plan_outline(current_plan.plan_json if current_plan else None),
        excerpts=excerpts,
    )

    prompt = base_prompt
    support: dict = {}
    for attempt in range(MAX_GENERATION_ATTEMPTS):
        support = generate_json(
            prompt=prompt,
            response_schema=prompt_mod.RESPONSE_SCHEMA,
            system_instruction=prompt_mod.SYSTEM_INSTRUCTION,
        )
        invalid = grounding.audit(support, len(chunks))
        if not invalid:
            break
        log.warning("teaching support grounding violation: %s", invalid)
        valid_range = f"S1 to S{len(chunks)}" if chunks else "no tags at all"
        prompt = (
            f"{base_prompt}\n\n## Correction required\n"
            f"Your previous answer cited {', '.join(sorted(set(invalid)))}, which do "
            f"not exist. The only valid tags are {valid_range}. Regenerate. Where no "
            "excerpt genuinely supports an item, use an empty grounding array [] - "
            "that is the correct answer for most industry examples, not a failure."
        )

    support = grounding.scrub(support, window_chunk_ids)
    _normalise(support)

    next_version = 1 + (
        db.execute(
            select(TeachingSupport.version)
            .where(TeachingSupport.lecture_id == lecture.id)
            .order_by(TeachingSupport.version.desc())
            .limit(1)
        ).scalar()
        or 0
    )
    row = TeachingSupport(
        lecture_id=lecture.id,
        version=next_version,
        support_json=support,
        model=settings.gemini_model,
        retrieved_chunk_ids=window_chunk_ids,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _normalise(support: dict) -> None:
    """Clamp anything the model could get wrong that the schema cannot express."""
    for activity in support.get("activities") or []:
        if activity.get("format") not in prompt_mod.ACTIVITY_FORMATS:
            activity["format"] = "group"
        minutes = activity.get("minutes")
        if not isinstance(minutes, int) or not 1 <= minutes <= 60:
            activity["minutes"] = 10
