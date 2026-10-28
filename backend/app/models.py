"""ORM tables.

Design note: page numbers, document titles and authors live HERE and only here.
The language model never supplies them - it may only point at a Chunk by id.
That is what makes a wrong page number structurally impossible rather than
merely unlikely.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Professor(Base):
    __tablename__ = "professor"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Professor")
    email: Mapped[str] = mapped_column(String(200), default="")

    courses: Mapped[list["Course"]] = relationship(back_populates="professor")


class Course(Base):
    __tablename__ = "course"

    id: Mapped[int] = mapped_column(primary_key=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("professor.id"), default=1, index=True)

    title: Mapped[str] = mapped_column(String(300))
    code: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    objectives: Mapped[str] = mapped_column(Text, default="")
    student_level: Mapped[str] = mapped_column(String(100), default="")
    total_lectures: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lecture_duration_min: Mapped[int] = mapped_column(Integer, default=50)
        # Week 5: the teaching calendar, used for schedule re-calibration.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    meeting_days: Mapped[list] = mapped_column(JSON, default=list)  # 0=Mon .. 6=Sun
    # [{"date": "YYYY-MM-DD", "reason": "..."}] - holidays and missed classes
    blocked_dates: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    professor: Mapped[Professor] = relationship(back_populates="courses")
    sources: Mapped[list["Source"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    lectures: Mapped[list["Lecture"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class Source(Base):
    """A citable source registered against a course.

    Uploaded files are created already 'approved'. External suggestions (books,
    papers, videos found by the assistant) enter as 'pending' and cannot be cited
    until the professor approves them - the literal implementation of asking the
    professor to select sources from the ones the assistant found.
    """

    __tablename__ = "source"

    KINDS = ("uploaded", "book", "paper", "video", "web")
    STATUSES = ("pending", "approved", "rejected")

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)

    kind: Mapped[str] = mapped_column(String(20), default="uploaded")
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str] = mapped_column(String(500), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identifier: Mapped[str] = mapped_column(String(500), default="")  # DOI / ISBN / URL

    status: Mapped[str] = mapped_column(String(20), default="approved", index=True)
    # Which stages this source may be used for, per the professor's request to
    # tag what sources can be used for what: lecture_content, teaser, assignment,
    # project_idea, question_paper, quiz, debate.
    allowed_uses: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    course: Mapped[Course] = relationship(back_populates="sources")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "document"

    INGEST_STATUSES = ("pending", "processing", "ready", "failed")

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), index=True)

    filename: Mapped[str] = mapped_column(String(500))
    path: Mapped[str] = mapped_column(String(1000))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    ingest_status: Mapped[str] = mapped_column(String(20), default="pending")
    ingest_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    source: Mapped[Source] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(Base):
    """A slice of a document. Never straddles a page boundary, so page_no is exact."""

    __tablename__ = "chunk"
    __table_args__ = (UniqueConstraint("document_id", "ordinal", name="uq_chunk_doc_ordinal"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("document.id"), index=True)

    page_no: Mapped[int] = mapped_column(Integer)  # 1-based, as recorded by the parser
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="chunks")


class Lecture(Base):
    __tablename__ = "lecture"

    STATUSES = ("planned", "delivered", "cancelled", "merged")

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)

    seq_no: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str] = mapped_column(String(500))
    duration_min: Mapped[int] = mapped_column(Integer, default=50)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    student_level_override: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    course: Mapped[Course] = relationship(back_populates="lectures")
    plans: Mapped[list["LecturePlan"]] = relationship(
        back_populates="lecture", cascade="all, delete-orphan", order_by="LecturePlan.version"
    )
    support_versions: Mapped[list["TeachingSupport"]] = relationship(
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="TeachingSupport.version",
    )


class LecturePlan(Base):
    __tablename__ = "lecture_plan"
    __table_args__ = (UniqueConstraint("lecture_id", "version", name="uq_plan_lecture_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lecture_id: Mapped[int] = mapped_column(ForeignKey("lecture.id"), index=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    plan_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(100), default="")
    # Chunk ids that were in the retrieval window for this generation, in S-tag
    # order: retrieved_chunk_ids[0] is S1. The audit trail for every citation.
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    lecture: Mapped[Lecture] = relationship(back_populates="plans")
    items: Mapped[list["PlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanItem.ordinal"
    )


class PlanItem(Base):
    __tablename__ = "plan_item"

    KINDS = ("recap", "concept", "example", "activity", "check", "summary")

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("lecture_plan.id"), index=True)

    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="concept")
    title: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    # Chunk ids (resolved from S-tags at enforcement time). Empty = ungrounded.
    grounding: Mapped[list] = mapped_column(JSON, default=list)
    edited_by_professor: Mapped[bool] = mapped_column(default=False)

    plan: Mapped[LecturePlan] = relationship(back_populates="items")


class TeachingSupport(Base):
    """Week 3 teaching support for a lecture: examples, activities, explanations.

    Generated on demand rather than folded into the lecture plan, so that
    regenerating a plan does not re-spend quota on material the professor was
    happy with, and so they can enrich only the lectures that need it.
    """

    __tablename__ = "teaching_support"
    __table_args__ = (
        UniqueConstraint("lecture_id", "version", name="uq_support_lecture_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lecture_id: Mapped[int] = mapped_column(ForeignKey("lecture.id"), index=True)

    version: Mapped[int] = mapped_column(Integer, default=1)
    support_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(100), default="")
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    lecture: Mapped["Lecture"] = relationship(back_populates="support_versions")


class ChatMessage(Base):
    """One turn in the professor's conversation about a course.

    The thread is course-scoped so the assistant can help before any lecture
    exists; `lecture_id` records which lecture was in focus for that turn.
    """

    __tablename__ = "chat_message"

    ROLES = ("professor", "assistant")

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("course.id"), index=True)
    lecture_id: Mapped[int | None] = mapped_column(
        ForeignKey("lecture.id"), nullable=True
    )

    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    # Chunk ids, resolved from S-tags by the same enforcement the plans use.
    citations: Mapped[list] = mapped_column(JSON, default=list)
    # What the assistant actually did, if anything: {"action": ..., "summary": ...}
    action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    clarification: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
