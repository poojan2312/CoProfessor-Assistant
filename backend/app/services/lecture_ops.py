"""Creating and updating lectures.

Extracted from the router so the chat action executor and the REST endpoints run
the same code - in particular the sequence-number assignment, which would be easy
to get subtly different in two places.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Course, Lecture


def next_seq_no(db: Session, course_id: int) -> int:
    highest = db.execute(
        select(func.max(Lecture.seq_no)).where(Lecture.course_id == course_id)
    ).scalar()
    return (highest or 0) + 1


def create_lecture(db: Session, course: Course, data: dict) -> Lecture:
    """Create a lecture, defaulting sequence number and duration from the course."""
    data = dict(data)
    if data.get("seq_no") is None:
        data["seq_no"] = next_seq_no(db, course.id)
    if data.get("duration_min") is None:
        data["duration_min"] = course.lecture_duration_min

    lecture = Lecture(course_id=course.id, **data)
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    return lecture


def update_lecture(db: Session, lecture: Lecture, data: dict) -> Lecture:
    for key, value in data.items():
        setattr(lecture, key, value)
    db.commit()
    db.refresh(lecture)
    return lecture
