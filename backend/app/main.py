"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import chat, courses, lectures, materials

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
# httpx logs full request URLs at INFO. Keys travel in headers now, but keep the
# noise down and remove any chance of a URL-borne secret reaching a log file.
logging.getLogger("httpx").setLevel(logging.WARNING)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logging.getLogger(__name__).info(
        "Co-Professor API ready (model=%s, embeddings=%s)",
        settings.gemini_model,
        settings.gemini_embed_model,
    )
    yield


app = FastAPI(
    title="Co-Professor AI Assistant",
    version="0.1.0",
    description=(
        "Phase 1: course and lecture preparation support. Every citation is "
        "resolved from parsed source metadata, never from model output."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router)
app.include_router(materials.router)
app.include_router(lectures.router)
app.include_router(chat.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "model": settings.gemini_model,
        "embed_model": settings.gemini_embed_model,
        "api_key_configured": bool(settings.gemini_api_key),
    }
