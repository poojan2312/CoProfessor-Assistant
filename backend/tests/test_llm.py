"""LLM client behaviour: secrets, retries and error mapping.

No network. httpx is stubbed so the retry policy is tested deterministically.
"""
from __future__ import annotations

import httpx
import pytest

from app.services import llm


def test_api_key_travels_in_a_header_not_a_url():
    """A key in the query string ends up in every log line and traceback."""
    headers = llm.auth_headers("SECRET")
    assert headers["x-goog-api-key"] == "SECRET"


def test_backoff_clears_the_rate_limit_window():
    """Single-digit backoff burns the retry budget inside one quota minute."""
    delays = [llm._sleep_for(attempt, None) for attempt in range(llm.MAX_ATTEMPTS)]
    assert delays[0] >= llm.RATE_LIMIT_FLOOR_SECONDS
    assert delays == sorted(delays)
    assert sum(delays) > 60  # outlasts the per-minute window
    assert max(delays) <= llm.MAX_BACKOFF_SECONDS


def test_google_retry_hint_wins_when_it_is_longer():
    assert llm._sleep_for(0, retry_after=40.0) > 40.0


def test_backoff_is_always_capped():
    assert llm._sleep_for(99, retry_after=9999.0) == llm.MAX_BACKOFF_SECONDS


def test_retry_after_is_read_from_google_retry_info():
    response = httpx.Response(
        429,
        json={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "5.7s",
                    }
                ]
            }
        },
    )
    assert llm._retry_after(response) == pytest.approx(5.7)


def test_retry_after_absent_is_none():
    assert llm._retry_after(httpx.Response(503, text="upstream down")) is None


def _stub_transport(monkeypatch, status_codes):
    """Return a fake httpx.Client yielding the given statuses in order."""
    remaining = list(status_codes)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    monkeypatch.setattr(llm, "get_settings", lambda: _Settings())

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *_args, **_kwargs):
            code = remaining.pop(0)
            if code == 200:
                return httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"parts": [{"text": '{"ok": true}'}]},
                            }
                        ]
                    },
                )
            return httpx.Response(code, json={"error": {"code": code}})

    monkeypatch.setattr(llm.httpx, "Client", lambda **_: FakeClient())


class _Settings:
    gemini_api_key = "test-key"
    gemini_model = "gemini-3.8-flash"


def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    _stub_transport(monkeypatch, [503, 200])
    assert llm.generate_json("p", {"type": "object"}) == {"ok": True}


def test_exhausted_rate_limit_raises_quota_exceeded(monkeypatch):
    _stub_transport(monkeypatch, [429] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.QuotaExceeded) as exc:
        llm.generate_json("p", {"type": "object"})
    assert "5 requests per minute" in str(exc.value)


def test_persistent_503_is_reported_as_the_rate_limit_it_usually_is(monkeypatch):
    """Google returns 503 for free-tier pressure, not only for real outages."""
    _stub_transport(monkeypatch, [503] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.QuotaExceeded):
        llm.generate_json("p", {"type": "object"})


def test_client_error_is_not_retried(monkeypatch):
    _stub_transport(monkeypatch, [400])
    with pytest.raises(llm.LLMError) as exc:
        llm.generate_json("p", {"type": "object"})
    assert "400" in str(exc.value)


def test_missing_api_key_fails_fast(monkeypatch):
    class Empty:
        gemini_api_key = ""
        gemini_model = "gemini-3.8-flash"

    monkeypatch.setattr(llm, "get_settings", lambda: Empty())
    with pytest.raises(llm.LLMError) as exc:
        llm.generate_json("p", {"type": "object"})
    assert "GEMINI_API_KEY" in str(exc.value)


def test_invalid_json_from_the_model_is_an_error_not_a_crash():
    body = {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}
        ]
    }
    with pytest.raises(llm.LLMError):
        llm._parse(body)


def test_truncated_response_is_rejected():
    body = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
    with pytest.raises(llm.LLMError):
        llm._parse(body)
