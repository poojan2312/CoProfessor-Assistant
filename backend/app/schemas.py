"""Request and response models."""
from __future__ import annotations

import datetime as _dt
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Weekday = Annotated[int, Field(ge=0, le=6)]  # 0=Mon .. 6=Sun


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Courses -----------------------------------------------------------------

class BlockedDate(BaseModel):
    """A date the course does not meet: a holiday, or a class that was missed."""

    date: _dt.date
    reason: str = Field(default="", max_length=200)

class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    code: str = ""
    description: str = ""
    objectives: str = ""
    student_level: str = ""
    total_lectures: int | None = Field(default=None, ge=1, le=200)
    lecture_duration_min: int = Field(default=50, ge=5, le=300)
    start_date: date | None = None
    end_date: date | None = None
    meeting_days: list[Weekday] = []
    blocked_dates: list[BlockedDate] = []


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    code: str | None = None
    description: str | None = None
    objectives: str | None = None
    student_level: str | None = None
    total_lectures: int | None = Field(default=None, ge=1, le=200)
    lecture_duration_min: int | None = Field(default=None, ge=5, le=300)
    start_date: date | None = None
    end_date: date | None = None
    meeting_days: list[Weekday] | None = None
    blocked_dates: list[BlockedDate] | None = None


class CourseOut(ORMModel):
    id: int
    title: str
    code: str
    description: str
    objectives: str
    student_level: str
    total_lectures: int | None
    lecture_duration_min: int
    start_date: date | None = None
    end_date: date | None = None
    meeting_days: list[int] = []
    blocked_dates: list[BlockedDate] = []
    created_at: datetime

# --- Schedule re-calibration (Week 5) ------------------------------------------

class RecalibrateRequest(BaseModel):
    """What changed. With apply=false (the default) nothing is written."""

    from_date: date | None = None  # re-plan from this date; default today
    blocked_dates: list[BlockedDate] = []  # new holidays / cancelled classes
    missed_seq_nos: list[int] = []  # lectures that did not happen on their date
    new_duration_min: int | None = Field(default=None, ge=5, le=300)
    apply: bool = False


class ScheduleChange(BaseModel):
    lecture_ids: list[int]
    seq_nos: list[int]
    topic: str
    old_date: date | None
    new_date: date | None
    old_duration_min: int
    new_duration_min: int
    merged: bool
    changed: bool


class RecalibrateOut(BaseModel):
    applied: bool
    from_date: date
    available_slots: int | None
    changes: list[ScheduleChange]
    added_blocked_dates: list[BlockedDate]
    spare_dates: list[date]
    warnings: list[str]
# --- Materials ---------------------------------------------------------------

class DocumentOut(ORMModel):
    id: int
    filename: str
    page_count: int
    chunk_count: int
    ingest_status: str
    ingest_error: str
    created_at: datetime


class SourceOut(ORMModel):
    id: int
    kind: str
    title: str
    authors: str
    year: int | None
    identifier: str
    status: str
    allowed_uses: list
    documents: list[DocumentOut] = []


# --- Lectures ----------------------------------------------------------------

class LectureCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    seq_no: int | None = Field(default=None, ge=1, le=500)
    duration_min: int | None = Field(default=None, ge=5, le=300)
    scheduled_date: date | None = None
    student_level_override: str = ""
    notes: str = ""


class LectureUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=500)
    seq_no: int | None = Field(default=None, ge=1, le=500)
    duration_min: int | None = Field(default=None, ge=5, le=300)
    scheduled_date: date | None = None
    student_level_override: str | None = None
    notes: str | None = None
    status: Literal["planned", "delivered", "cancelled"] | None = None


class LectureOut(ORMModel):
    id: int
    course_id: int
    seq_no: int
    topic: str
    duration_min: int
    scheduled_date: date | None
    student_level_override: str
    notes: str
    status: str
    created_at: datetime
    has_plan: bool = False


# --- Plans -------------------------------------------------------------------

class Citation(BaseModel):
    """Built entirely from database metadata. See services/citations.py."""

    chunk_id: int
    source_id: int
    source_title: str
    authors: str
    year: int | None
    kind: str
    identifier: str
    document_filename: str
    page_no: int
    snippet: str
    display: str


class SegmentUpdate(BaseModel):
    ordinal: int
    title: str | None = None
    body: str | None = None
    kind: str | None = None
    minutes: int | None = Field(default=None, ge=0, le=300)


class PlanEdit(BaseModel):
    """A professor's edits to the current plan version."""

    segments: list[SegmentUpdate] = []
    drop_ordinals: list[int] = []


class PlanOut(BaseModel):
    id: int
    lecture_id: int
    version: int
    model: str
    created_at: datetime
    plan: dict
    # chunk_id -> citation. The UI resolves grounding arrays against this.
    citations: dict[int, Citation]
    grounded_segment_count: int
    total_segment_count: int
    retrieved_chunk_count: int


# --- Teaching support (Week 3) -----------------------------------------------

class TeachingSupportOut(BaseModel):
    id: int
    lecture_id: int
    version: int
    model: str
    created_at: datetime
    support: dict
    citations: dict[int, Citation]
    retrieved_chunk_count: int


# --- Chat ---------------------------------------------------------------------

class ChatSend(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # The lecture the professor currently has open, so "this lecture" resolves.
    lecture_id: int | None = None


class ChatMessageOut(ORMModel):
    id: int
    role: str
    content: str
    lecture_id: int | None
    citations: list[int]
    action: dict | None
    clarification: str
    created_at: datetime


class ChatTurnOut(BaseModel):
    message: ChatMessageOut
    citations: dict[int, Citation]
    focus_lecture_id: int | None
    # What the UI should refetch after this turn.
    plan_changed: bool
    lecture_changed: bool
    course_changed: bool
    support_changed: bool
