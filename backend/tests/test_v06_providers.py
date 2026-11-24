"""Provider adapters share one contract: typed plan out, instrumented attempts, safe failure."""

import json

import httpx
import pytest
from app.config import settings
from app.rental_planner import capture_calls

from .test_v05 import QUERY, customer


def anthropic(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(settings, "ai_mode", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "mock")
    monkeypatch.setattr(settings, "anthropic_model", "mock-claude")


def tool_use(plan, **extra):
    return httpx.Response(
        200,
        json={
            "model": "mock-claude",
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 812, "output_tokens": 41},
            "content": [{"type": "tool_use", "id": "t1", "name": "rental_followup", "input": plan}],
            **extra,
        },
    )


def test_anthropic_request_contract_and_usage(client, monkeypatch):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content), headers=dict(request.headers))
        return tool_use({"operation": "edit", "min_seats": 7})

    ask, snapshot = customer(client)
    anthropic(monkeypatch, handler)
    with capture_calls() as events:
        data = ask("Keep my budget and require seven seats").json()
    assert data["ids"] == [] and snapshot()[2] == {**QUERY, "min_seats": 7}
    assert seen["tool_choice"] == {"type": "tool", "name": "rental_followup"}
    assert seen["tools"][0]["input_schema"]["required"] == ["operation"]
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert "Display context" in seen["system"] and '"ids": [6, 7]' in seen["system"]
    (event,) = events
    assert event["provider"] == "anthropic" and event["validated"] and event["completed"]
    assert event["usage"] == {"input_tokens": 812, "output_tokens": 41, "total_tokens": 853}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=[]),
        httpx.Response(
            200, json={"content": [{"type": "text", "text": "Booked! Enjoy the RAV4."}]}
        ),
        httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "name": "rental_followup", "input": {"operation": "edit"}},
                    {
                        "type": "tool_use",
                        "name": "rental_followup",
                        "input": {"operation": "quote", "position": 1},
                    },
                ]
            },
        ),
        httpx.Response(
            200, json={"content": [{"type": "tool_use", "name": "book_now", "input": {}}]}
        ),
        httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "name": "rental_followup",
                        "input": {"operation": "delete_all"},
                    }
                ]
            },
        ),
        httpx.Response(429, json={"error": {"type": "rate_limit_error"}}),
        httpx.Response(529, json={"error": {"type": "overloaded_error"}}),
    ],
)
def test_anthropic_malformed_or_failed_output_is_safe(client, monkeypatch, response):
    ask, snapshot = customer(client)
    before = snapshot()
    anthropic(monkeypatch, lambda _: response)
    with capture_calls() as events:
        assert ask("Quote the first car").status_code == 502
    assert (
        len(events) == 1
        and events[0]["attempted"]
        and not events[0]["validated"]
        and events[0]["error"]
    )
    assert snapshot() == before


def test_missing_credentials_record_zero_calls(client, monkeypatch):
    ask, snapshot = customer(client)
    monkeypatch.setattr(settings, "ai_mode", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with capture_calls() as events:
        assert ask("Compare the first two").status_code == 503
    assert events == []
