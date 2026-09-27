"""Test fixtures.

Every test runs against its own in-memory database. Nothing here touches the
network: the LLM and embedding calls are stubbed by the tests that need them, so
the suite is runnable with no API key and no quota.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Chunk, Course, Document, Lecture, Professor, Source


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    session.add(Professor(id=1, name="Test Professor", email=""))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def course(db) -> Course:
    row = Course(
        professor_id=1,
        title="Operating Systems",
        code="CS301",
        objectives="Understand processes, scheduling and memory management.",
        student_level="3rd year B.Tech",
        lecture_duration_min=50,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def lecture(db, course) -> Lecture:
    row = Lecture(
        course_id=course.id, seq_no=1, topic="CPU Scheduling", duration_min=50
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def chunks(db, course) -> list[Chunk]:
    """Two chunks on known pages, for asserting what citations render."""
    source = Source(
        course_id=course.id,
        kind="uploaded",
        title="Operating System Concepts",
        authors="Silberschatz, Galvin, Gagne",
        year=2018,
        status="approved",
    )
    db.add(source)
    db.flush()

    document = Document(
        source_id=source.id,
        filename="os-concepts.pdf",
        path="/nowhere/os-concepts.pdf",
        page_count=900,
        ingest_status="ready",
    )
    db.add(document)
    db.flush()

    rows = [
        Chunk(
            document_id=document.id,
            page_no=214,
            ordinal=0,
            text="Round-robin scheduling is designed especially for time-sharing systems.",
        ),
        Chunk(
            document_id=document.id,
            page_no=266,
            ordinal=1,
            text="A semaphore S is an integer variable accessed via wait() and signal().",
        ),
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


@pytest.fixture
def plan(db, lecture, chunks):
    """A stored v1 plan with four segments totalling the lecture duration."""
    from app.models import LecturePlan, PlanItem

    segments = [
        {"ordinal": 1, "kind": "recap", "title": "Recap", "body": "b",
         "minutes": 10, "grounding": []},
        {"ordinal": 2, "kind": "concept", "title": "Round robin", "body": "b",
         "minutes": 20, "grounding": [chunks[0].id]},
        {"ordinal": 3, "kind": "example", "title": "Worked example", "body": "b",
         "minutes": 12, "grounding": []},
        {"ordinal": 4, "kind": "summary", "title": "Wrap up", "body": "b",
         "minutes": 8, "grounding": []},
    ]
    row = LecturePlan(
        lecture_id=lecture.id,
        version=1,
        model="test-model",
        retrieved_chunk_ids=[c.id for c in chunks],
        plan_json={
            "topic": lecture.topic,
            "summary": "s",
            "duration_min": lecture.duration_min,
            "total_allocated_min": sum(s["minutes"] for s in segments),
            "learning_objectives": [],
            "prerequisites": [],
            "segments": segments,
            "misconceptions": [],
            "clarifications_needed": [],
        },
    )
    db.add(row)
    db.flush()
    for segment in segments:
        db.add(PlanItem(plan_id=row.id, **segment))
    db.commit()
    db.refresh(row)
    return row
