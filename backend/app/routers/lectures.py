"""Lecture context, plan generation, professor edits, and teaching support."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lecture, LecturePlan, TeachingSupport
from app.routers.courses import get_course_or_404
from app.schemas import (
    LectureCreate,
    LectureOut,
    LectureUpdate,
    PlanEdit,
    PlanOut,
    TeachingSupportOut,
)
from app.services import citations, grounding, lecture_ops, plan_edits, planner
from app.services import teaching_support as support_service
from app.services.llm import LLMError, QuotaExceeded

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["lectures"])


def get_lecture_or_404(db: Session, lecture_id: int) -> Lecture:
    lecture = db.get(Lecture, lecture_id)
    if lecture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Lecture {lecture_id} not found")
    return lecture


def as_lecture_out(db: Session, lecture: Lecture) -> LectureOut:
    out = LectureOut.model_validate(lecture)
    out.has_plan = plan_edits.latest_plan(db, lecture.id) is not None
    return out


def plan_out(db: Session, plan: LecturePlan) -> PlanOut:
    """Attach citations resolved from the database, never from model output."""
    resolved = citations.build(db, grounding.cited_chunk_ids(plan.plan_json))
    segments = plan.plan_json.get("segments") or []
    return PlanOut(
        id=plan.id,
        lecture_id=plan.lecture_id,
        version=plan.version,
        model=plan.model,
        created_at=plan.created_at,
        plan=plan.plan_json,
        citations=resolved,
        grounded_segment_count=sum(1 for s in segments if s.get("grounding")),
        total_segment_count=len(segments),
        retrieved_chunk_count=len(plan.retrieved_chunk_ids or []),
    )


def support_out(db: Session, row: TeachingSupport) -> TeachingSupportOut:
    return TeachingSupportOut(
        id=row.id,
        lecture_id=row.lecture_id,
        version=row.version,
        model=row.model,
        created_at=row.created_at,
        support=row.support_json,
        citations=citations.build(db, grounding.cited_chunk_ids(row.support_json)),
        retrieved_chunk_count=len(row.retrieved_chunk_ids or []),
    )


def _generation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, QuotaExceeded):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


# --- Lecture context ---------------------------------------------------------

@router.post(
    "/courses/{course_id}/lectures",
    response_model=LectureOut,
    status_code=status.HTTP_201_CREATED,
)
def create_lecture(
    course_id: int, payload: LectureCreate, db: Session = Depends(get_db)
) -> LectureOut:
    course = get_course_or_404(db, course_id)
    lecture = lecture_ops.create_lecture(db, course, payload.model_dump())
    return as_lecture_out(db, lecture)


@router.get("/courses/{course_id}/lectures", response_model=list[LectureOut])
def list_lectures(course_id: int, db: Session = Depends(get_db)) -> list[LectureOut]:
    get_course_or_404(db, course_id)
    lectures = db.execute(
        select(Lecture).where(Lecture.course_id == course_id).order_by(Lecture.seq_no)
    ).scalars()
    return [as_lecture_out(db, lecture) for lecture in lectures]


@router.get("/lectures/{lecture_id}", response_model=LectureOut)
def get_lecture(lecture_id: int, db: Session = Depends(get_db)) -> LectureOut:
    return as_lecture_out(db, get_lecture_or_404(db, lecture_id))


@router.patch("/lectures/{lecture_id}", response_model=LectureOut)
def update_lecture(
    lecture_id: int, payload: LectureUpdate, db: Session = Depends(get_db)
) -> LectureOut:
    """Update lecture-specific information.

    Changing the duration re-apportions the existing plan so it never displays a
    total that no longer matches the class length.
    """
    lecture = get_lecture_or_404(db, lecture_id)
    fields = payload.model_dump(exclude_unset=True)
    lecture_ops.update_lecture(db, lecture, fields)

    if "duration_min" in fields and plan_edits.latest_plan(db, lecture.id):
        plan_edits.apply_plan_edits(db, lecture, [], [])

    return as_lecture_out(db, lecture)


@router.delete("/lectures/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lecture(lecture_id: int, db: Session = Depends(get_db)):
    db.delete(get_lecture_or_404(db, lecture_id))
    db.commit()


# --- Plans -------------------------------------------------------------------

@router.post("/lectures/{lecture_id}/plan/generate", response_model=PlanOut)
def generate(lecture_id: int, db: Session = Depends(get_db)) -> PlanOut:
    lecture = get_lecture_or_404(db, lecture_id)
    try:
        plan = planner.generate_plan(db, lecture)
    except LLMError as exc:
        raise _generation_error(exc) from exc
    return plan_out(db, plan)


@router.get("/lectures/{lecture_id}/plan", response_model=PlanOut)
def get_plan(lecture_id: int, db: Session = Depends(get_db)) -> PlanOut:
    get_lecture_or_404(db, lecture_id)
    plan = plan_edits.latest_plan(db, lecture_id)
    if plan is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No plan generated for this lecture yet"
        )
    return plan_out(db, plan)


@router.get("/lectures/{lecture_id}/plan/versions", response_model=list[int])
def list_plan_versions(lecture_id: int, db: Session = Depends(get_db)) -> list[int]:
    get_lecture_or_404(db, lecture_id)
    return list(
        db.execute(
            select(LecturePlan.version)
            .where(LecturePlan.lecture_id == lecture_id)
            .order_by(LecturePlan.version)
        ).scalars()
    )


@router.patch("/lectures/{lecture_id}/plan", response_model=PlanOut)
def edit_plan(
    lecture_id: int, payload: PlanEdit, db: Session = Depends(get_db)
) -> PlanOut:
    """Apply the professor's edits as a new plan version.

    Edits never call the model, so an edited segment keeps whatever grounding it
    had. Versions are additive: nothing the professor wrote is overwritten.
    """
    lecture = get_lecture_or_404(db, lecture_id)
    try:
        plan = plan_edits.apply_plan_edits(
            db, lecture, payload.segments, payload.drop_ordinals
        )
    except plan_edits.PlanEditError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return plan_out(db, plan)


# --- Teaching support (Week 3) -----------------------------------------------

@router.post("/lectures/{lecture_id}/teaching-support", response_model=TeachingSupportOut)
def generate_teaching_support(
    lecture_id: int, db: Session = Depends(get_db)
) -> TeachingSupportOut:
    lecture = get_lecture_or_404(db, lecture_id)
    try:
        row = support_service.generate(db, lecture)
    except LLMError as exc:
        raise _generation_error(exc) from exc
    return support_out(db, row)


@router.get("/lectures/{lecture_id}/teaching-support", response_model=TeachingSupportOut)
def get_teaching_support(
    lecture_id: int, db: Session = Depends(get_db)
) -> TeachingSupportOut:
    get_lecture_or_404(db, lecture_id)
    row = support_service.latest(db, lecture_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No teaching support generated for this lecture yet"
        )
    return support_out(db, row)
