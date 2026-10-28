
"""Course CRUD and schedule re-calibration."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Course
from app.schemas import (
    CourseCreate,
    CourseOut,
    CourseUpdate,
    RecalibrateOut,
    RecalibrateRequest,
    ScheduleChange,
)
from app.services import schedule

router = APIRouter(prefix="/api/courses", tags=["courses"])

PROFESSOR_ID = 1  # single-professor build; the column exists for when auth lands


def get_course_or_404(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Course {course_id} not found")
    return course

def _course_fields(payload, exclude_unset: bool) -> dict:
    """Payload -> column values. Blocked dates are stored as JSON, so as ISO strings."""
    data = payload.model_dump(exclude_unset=exclude_unset)
    for key in ("meeting_days", "blocked_dates"):
        if key in data and data[key] is None:
            del data[key]  # "not given", not "clear it"
    if "blocked_dates" in data:
        data["blocked_dates"] = [
            {"date": b["date"].isoformat(), "reason": b.get("reason", "")}
            for b in data["blocked_dates"]
        ]
    if "meeting_days" in data:
        data["meeting_days"] = sorted(set(data["meeting_days"]))
    return data

@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseCreate, db: Session = Depends(get_db)) -> Course:
    course = Course(professor_id=PROFESSOR_ID, **_course_fields(payload, False))
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.get("", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db)) -> list[Course]:
    return list(
        db.execute(select(Course).order_by(Course.created_at.desc())).scalars()
    )


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: int, db: Session = Depends(get_db)) -> Course:
    return get_course_or_404(db, course_id)


@router.patch("/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)
) -> Course:
    course = get_course_or_404(db, course_id)
    for key, value in _course_fields(payload, True).items():
        setattr(course, key, value)
    db.commit()
    db.refresh(course)
    return course


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = get_course_or_404(db, course_id)
    db.delete(course)
    db.commit()

# --- Schedule re-calibration (Week 5) ------------------------------------------

def recalibrate_out(proposal: schedule.Proposal, applied: bool) -> RecalibrateOut:
    return RecalibrateOut(
        applied=applied,
        from_date=proposal.from_date,
        available_slots=proposal.available_slots,
        changes=[
            ScheduleChange(
                lecture_ids=g.lecture_ids,
                seq_nos=g.seq_nos,
                topic=" + ".join(g.topics),
                old_date=g.old_date,
                new_date=g.new_date,
                old_duration_min=g.old_duration,
                new_duration_min=g.new_duration,
                merged=g.merged,
                changed=g.changed,
            )
            for g in proposal.groups
        ],
        added_blocked_dates=proposal.new_blocked,
        spare_dates=proposal.spare_dates,
        warnings=proposal.warnings,
    )


@router.post("/{course_id}/recalibrate", response_model=RecalibrateOut)
def recalibrate(
    course_id: int, payload: RecalibrateRequest, db: Session = Depends(get_db)
) -> RecalibrateOut:
    """Work out the remaining schedule after a disruption.

    Previews by default. Send the same body with apply=true to accept it. With no
    disruption in the body this simply (re)builds the schedule from the calendar.
    """
    course = get_course_or_404(db, course_id)
    lectures = schedule.lectures_of(db, course.id)
    try:
        proposal = schedule.propose(course, lectures, payload, today=date.today())
    except schedule.ScheduleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if payload.apply:
        schedule.apply(db, course, proposal)
    return recalibrate_out(proposal, payload.apply)
