"""Lecture plan generation: retrieve, generate, enforce, apportion, persist.

The order matters. Enforcement sits between the model and the database, so no
fabricated citation is ever stored, let alone shown.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Course, Lecture, LecturePlan, PlanItem, Source
from app.prompts import lecture_plan as prompt_mod
from app.services import embeddings, grounding
from app.services.timealloc import allocate
from app.services.vectorstore import get_store

log = logging.getLogger(__name__)

MAX_GENERATION_ATTEMPTS = 2  # one honest try, one corrective retry


def approved_source_ids(db: Session, course_id: int) -> list[int]:
    return list(
        db.execute(
            select(Source.id).where(
                Source.course_id == course_id, Source.status == "approved"
            )
        ).scalars()
    )


def retrieve_for_query(
    db: Session, course_id: int, query: str, top_k: int | None = None
) -> list[Chunk]:
    """Fetch the chunks that form a citation window, best match first.

    Restricted to approved sources at the vector-store level, so an unapproved or
    rejected source cannot reach the model and therefore cannot be cited. Shared
    by lecture planning, chat and teaching support.
    """
    settings = get_settings()
    source_ids = approved_source_ids(db, course_id)
    if not source_ids or not query.strip():
        return []

    vector = embeddings.embed_query(query)
    chunk_ids = get_store().query(
        embedding=vector,
        course_id=course_id,
        source_ids=source_ids,
        top_k=top_k or settings.retrieval_top_k,
    )
    if not chunk_ids:
        return []

    rows = db.execute(select(Chunk).where(Chunk.id.in_(chunk_ids))).scalars().all()
    by_id = {c.id: c for c in rows}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]  # preserve rank order


def retrieve(db: Session, lecture: Lecture, top_k: int | None = None) -> list[Chunk]:
    """The citation window for a lecture: its topic plus the course framing."""
    course = lecture.course
    query = " ".join(
        part for part in (lecture.topic, course.title, course.objectives) if part
    )
    return retrieve_for_query(db, course.id, query, top_k)


def _format_excerpts(db: Session, chunks: list[Chunk]) -> list[str]:
    """Number the chunks as [S1]..[Sk].

    The excerpt header carries no bibliographic detail on purpose: if the model
    never sees a page number or title, it cannot echo a wrong one back.
    """
    return [f"[S{i}] {chunk.text}" for i, chunk in enumerate(chunks, start=1)]


def _previous_topics(db: Session, lecture: Lecture) -> list[str]:
    rows = db.execute(
        select(Lecture.topic)
        .where(
            Lecture.course_id == lecture.course_id,
            Lecture.seq_no < lecture.seq_no,
            Lecture.status != "cancelled",
        )
        .order_by(Lecture.seq_no)
    ).scalars()
    return [t for t in rows if t]


def generate_plan(db: Session, lecture: Lecture) -> LecturePlan:
    """Generate, validate and store a new plan version for a lecture."""
    course: Course = lecture.course
    chunks = retrieve(db, lecture)
    window_chunk_ids = [c.id for c in chunks]
    excerpts = _format_excerpts(db, chunks)

    base_prompt = prompt_mod.build_prompt(
        course_title=course.title,
        course_code=course.code,
        course_description=course.description,
        objectives=course.objectives,
        student_level=lecture.student_level_override or course.student_level,
        topic=lecture.topic,
        duration_min=lecture.duration_min,
        seq_no=lecture.seq_no,
        notes=lecture.notes,
        previous_topics=_previous_topics(db, lecture),
        excerpts=excerpts,
    )

    plan_json = _generate_with_enforcement(base_prompt, len(chunks))
    plan_json = grounding.scrub(plan_json, window_chunk_ids)
    plan_json = _apportion(plan_json, lecture.duration_min)

    return _persist(db, lecture, plan_json, window_chunk_ids)


def _generate_with_enforcement(base_prompt: str, window_size: int) -> dict:
    """Generate, and if the model fabricated a tag, tell it so and try once more.

    Whatever survives is scrubbed by the caller, so a model that keeps inventing
    citations degrades to honest ungrounded content rather than false citations.
    """
    from app.services.llm import generate_json

    prompt = base_prompt
    plan: dict = {}

    for attempt in range(MAX_GENERATION_ATTEMPTS):
        plan = generate_json(
            prompt=prompt,
            response_schema=prompt_mod.RESPONSE_SCHEMA,
            system_instruction=prompt_mod.SYSTEM_INSTRUCTION,
        )
        invalid = grounding.audit(plan, window_size)
        if not invalid:
            return plan

        log.warning(
            "grounding violation on attempt %s: %s (window size %s)",
            attempt + 1, invalid, window_size,
        )
        valid_range = f"S1 to S{window_size}" if window_size else "no tags at all"
        prompt = (
            f"{base_prompt}\n\n## Correction required\n"
            f"Your previous answer cited {', '.join(sorted(set(invalid)))}, which "
            f"do not exist. The only valid tags are {valid_range}. Regenerate the "
            "plan. Where you have no genuine supporting excerpt, use an empty "
            "grounding array [] - that is the correct answer, not a guess."
        )

    return plan


def _apportion(plan: dict, duration_min: int) -> dict:
    """Replace model weights with minutes that sum to exactly the class length."""
    settings = get_settings()
    segments = [s for s in (plan.get("segments") or []) if isinstance(s, dict)]

    if segments:
        minutes = allocate(
            [s.get("weight", 1) for s in segments],
            duration_min,
            floor_minutes=settings.min_segment_minutes,
        )
        for ordinal, (segment, mins) in enumerate(zip(segments, minutes), start=1):
            segment["ordinal"] = ordinal
            segment["minutes"] = mins
            segment.pop("weight", None)
            if segment.get("kind") not in PlanItem.KINDS:
                segment["kind"] = "concept"

    plan["segments"] = segments
    plan["duration_min"] = duration_min
    plan["total_allocated_min"] = sum(s["minutes"] for s in segments)
    return plan


def _persist(
    db: Session, lecture: Lecture, plan_json: dict, window_chunk_ids: list[int]
) -> LecturePlan:
    settings = get_settings()
    next_version = 1 + (
        db.execute(
            select(LecturePlan.version)
            .where(LecturePlan.lecture_id == lecture.id)
            .order_by(LecturePlan.version.desc())
            .limit(1)
        ).scalar()
        or 0
    )

    plan = LecturePlan(
        lecture_id=lecture.id,
        version=next_version,
        plan_json=plan_json,
        model=settings.gemini_model,
        retrieved_chunk_ids=window_chunk_ids,
    )
    db.add(plan)
    db.flush()

    for segment in plan_json.get("segments") or []:
        db.add(
            PlanItem(
                plan_id=plan.id,
                ordinal=segment["ordinal"],
                kind=segment.get("kind", "concept"),
                title=segment.get("title", ""),
                body=segment.get("body", ""),
                minutes=segment.get("minutes", 0),
                grounding=segment.get("grounding") or [],
            )
        )

    db.commit()
    db.refresh(plan)
    return plan
