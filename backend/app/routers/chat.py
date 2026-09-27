"""The professor's chat thread for a course."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChatMessage
from app.routers.courses import get_course_or_404
from app.routers.lectures import get_lecture_or_404
from app.schemas import ChatMessageOut, ChatSend, ChatTurnOut
from app.services import chat as chat_service
from app.services import citations
from app.services.llm import LLMError, QuotaExceeded

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/courses/{course_id}/chat", response_model=ChatTurnOut)
def send_message(
    course_id: int, payload: ChatSend, db: Session = Depends(get_db)
) -> ChatTurnOut:
    course = get_course_or_404(db, course_id)

    lecture = None
    if payload.lecture_id is not None:
        lecture = get_lecture_or_404(db, payload.lecture_id)
        if lecture.course_id != course.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "That lecture belongs to a different course",
            )

    try:
        result = chat_service.send(db, course, payload.message.strip(), lecture)
    except QuotaExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return ChatTurnOut(
        message=ChatMessageOut.model_validate(result.message),
        citations=citations.build(db, result.message.citations),
        focus_lecture_id=result.focus_lecture_id,
        plan_changed=result.plan_changed,
        lecture_changed=result.lecture_changed,
        course_changed=result.course_changed,
        support_changed=result.support_changed,
    )


@router.get("/courses/{course_id}/chat", response_model=list[ChatMessageOut])
def get_history(course_id: int, db: Session = Depends(get_db)) -> list[ChatMessage]:
    get_course_or_404(db, course_id)
    return list(
        db.execute(
            select(ChatMessage)
            .where(ChatMessage.course_id == course_id)
            .order_by(ChatMessage.id)
        ).scalars()
    )


@router.get("/courses/{course_id}/chat/citations", response_model=dict)
def get_history_citations(course_id: int, db: Session = Depends(get_db)) -> dict:
    """Every citation referenced anywhere in the thread, for rendering history."""
    get_course_or_404(db, course_id)
    rows = db.execute(
        select(ChatMessage.citations).where(ChatMessage.course_id == course_id)
    ).scalars()
    chunk_ids = sorted({cid for row in rows for cid in (row or [])})
    return citations.build(db, chunk_ids)


@router.delete("/courses/{course_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
def clear_thread(course_id: int, db: Session = Depends(get_db)):
    get_course_or_404(db, course_id)
    db.execute(delete(ChatMessage).where(ChatMessage.course_id == course_id))
    db.commit()
