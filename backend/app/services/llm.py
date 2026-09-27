"""Gemini client.

Model ids are pinned in config after being checked against the live API - on this
key gemini-2.5-flash returns 404 and the google_search grounding tool returns 429,
so neither is used anywhere in this codebase.
"""
from __future__ import annotations

import json
import logging
import random
import time

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

MAX_ATTEMPTS = 4
TIMEOUT_SECONDS = 120.0

# The free tier allows 5 generate_content requests per minute per model, and
# Google signals that pressure as either 429 or 503. Backing off in single-digit
# seconds just burns the retry budget inside the same quota window, so the floor
# here is deliberately larger than a normal exponential backoff would suggest.
RATE_LIMIT_FLOOR_SECONDS = 8.0
MAX_BACKOFF_SECONDS = 45.0


def auth_headers(api_key: str) -> dict[str, str]:
    """Send the key as a header, never as a URL parameter.

    httpx logs request URLs at INFO, so a key in the query string ends up in
    plain text in every log file and traceback.
    """
    return {"x-goog-api-key": api_key, "Content-Type": "application/json"}


class LLMError(RuntimeError):
    """Generation failed for a reason the caller should surface to the professor."""


class QuotaExceeded(LLMError):
    """The Gemini free tier is rate limiting us. Worth its own type so the API can
    return a clear message instead of a generic 500 - this will happen during
    development."""


def _sleep_for(attempt: int, retry_after: float | None) -> float:
    """Seconds to wait before the next attempt.

    Google's own RetryInfo wins when it is present and longer; otherwise back off
    exponentially from the rate-limit floor, with jitter so concurrent callers do
    not line up on the same retry instant.
    """
    backoff = RATE_LIMIT_FLOOR_SECONDS * (2**attempt) + random.random()
    if retry_after is not None:
        backoff = max(backoff, retry_after + 1.0)
    return min(backoff, MAX_BACKOFF_SECONDS)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        for detail in response.json().get("error", {}).get("details", []):
            if detail.get("@type", "").endswith("RetryInfo"):
                return float(detail.get("retryDelay", "0s").rstrip("s"))
    except (ValueError, AttributeError, TypeError):
        pass
    return None


def generate_json(
    prompt: str,
    response_schema: dict,
    system_instruction: str | None = None,
    temperature: float = 0.4,
) -> dict:
    """Run a single generation constrained to a JSON schema, with backoff.

    Returns the parsed object. Raises QuotaExceeded or LLMError.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set in .env")

    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = f"{API_ROOT}/{settings.gemini_model}:generateContent"
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(url, headers=auth_headers(settings.gemini_api_key), json=payload)
        except httpx.RequestError as exc:
            last_error = exc
            log.warning("Gemini request failed (attempt %s): %s", attempt + 1, exc)
            time.sleep(_sleep_for(attempt, None))
            continue

        if response.status_code == 200:
            return _parse(response.json())

        if response.status_code in (429, 500, 503):
            delay = _sleep_for(attempt, _retry_after(response))
            log.warning(
                "Gemini %s on attempt %s, retrying in %.1fs",
                response.status_code, attempt + 1, delay,
            )
            last_error = LLMError(f"HTTP {response.status_code}")
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(delay)
            continue

        raise LLMError(f"Gemini HTTP {response.status_code}: {response.text[:400]}")

    detail = str(last_error)
    # On the free tier Google signals the same 5-requests-per-minute ceiling as
    # either 429 or 503, so both point the professor at the same real cause.
    if "429" in detail or "503" in detail:
        raise QuotaExceeded(
            "Gemini's free tier allows only 5 requests per minute for this model, "
            "and that limit is currently exhausted. Wait about a minute and "
            "generate again, or enable billing on the API key to remove the limit."
        )
    if "500" in detail:
        raise LLMError(
            "Gemini returned a server error and did not recover after "
            f"{MAX_ATTEMPTS} attempts. This is an outage on Google's side, not a "
            "problem with your course or material - try again in a moment."
        )
    raise LLMError(f"Gemini did not respond after {MAX_ATTEMPTS} attempts: {detail}")


def _parse(body: dict) -> dict:
    candidates = body.get("candidates") or []
    if not candidates:
        feedback = body.get("promptFeedback", {})
        raise LLMError(f"Gemini returned no candidates (feedback: {feedback})")

    candidate = candidates[0]
    finish = candidate.get("finishReason")
    if finish not in (None, "STOP"):
        raise LLMError(f"Gemini stopped early: {finish}")

    parts = candidate.get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise LLMError("Gemini returned an empty response")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc
