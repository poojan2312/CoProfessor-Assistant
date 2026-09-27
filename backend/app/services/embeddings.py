"""Gemini embeddings.

gemini-embedding-2 exposes embedContent (one text per call) on this key, not a
synchronous batch endpoint, so batching here means a small thread pool rather
than a single request. Vectors come back L2-normalised at 768 dimensions.
"""
from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.config import get_settings
from app.services.llm import LLMError, QuotaExceeded, auth_headers

log = logging.getLogger(__name__)
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

MAX_ATTEMPTS = 5
MAX_WORKERS = 4
TIMEOUT_SECONDS = 60.0

DOCUMENT = "RETRIEVAL_DOCUMENT"
QUERY = "RETRIEVAL_QUERY"


def _embed_one(client: httpx.Client, text: str, task_type: str) -> list[float]:
    settings = get_settings()
    url = f"{API_ROOT}/{settings.gemini_embed_model}:embedContent"
    payload = {
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": settings.embed_dimensions,
    }

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.post(url, headers=auth_headers(settings.gemini_api_key), json=payload)
        except httpx.RequestError as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise LLMError(f"embedding request failed: {exc}") from exc
            time.sleep(min(2**attempt + random.random(), 20.0))
            continue

        if response.status_code == 200:
            return response.json()["embedding"]["values"]

        if response.status_code in (429, 500, 503):
            if attempt == MAX_ATTEMPTS - 1:
                if response.status_code == 429:
                    raise QuotaExceeded(
                        "Gemini embedding rate limit reached. Wait a minute and re-upload, "
                        "or enable billing on the key."
                    )
                raise LLMError(f"embedding HTTP {response.status_code}")
            time.sleep(min(2**attempt + random.random(), 20.0))
            continue

        raise LLMError(f"embedding HTTP {response.status_code}: {response.text[:300]}")

    raise LLMError("embedding failed after retries")


def embed_texts(texts: list[str], task_type: str = DOCUMENT) -> list[list[float]]:
    """Embed many texts, preserving order."""
    if not texts:
        return []
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set in .env")

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        if len(texts) == 1:
            return [_embed_one(client, texts[0], task_type)]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            return list(pool.map(lambda t: _embed_one(client, t, task_type), texts))


def embed_query(text: str) -> list[float]:
    return embed_texts([text], task_type=QUERY)[0]
