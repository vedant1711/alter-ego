"""FR11: the public demo defends a shared LLM key (PRD section 13)."""

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.tests.conftest import ingest


@pytest.fixture
def limits(monkeypatch):
    """Tighten the (test-relaxed) limits back down to something checkable."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_per_min", 3)
    monkeypatch.setattr(settings, "max_requests_per_session", 5)
    monkeypatch.setattr(settings, "max_message_chars", 50)
    return settings


def test_rejects_overlong_messages(client: TestClient, session_id: str, limits) -> None:
    res = client.post(
        "/api/chat", json={"session_id": session_id, "message": "x" * (limits.max_message_chars + 1)}
    )
    assert res.status_code == 413
    assert str(limits.max_message_chars) in res.json()["detail"]


def test_rate_limit_kicks_in(client: TestClient, session_id: str, limits) -> None:
    for _ in range(limits.rate_limit_per_min):
        assert client.post(
            "/api/ingest", json={"session_id": session_id, "text": "a fact", "source": "fact"}
        ).status_code == 200

    res = client.post(
        "/api/ingest", json={"session_id": session_id, "text": "one too many", "source": "fact"}
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_lifetime_cap_is_enforced(client: TestClient, session_id: str, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_per_min", 1000)
    monkeypatch.setattr(settings, "max_requests_per_session", 3)

    for _ in range(3):
        assert client.post(
            "/api/ingest", json={"session_id": session_id, "text": "a fact", "source": "fact"}
        ).status_code == 200

    res = client.post(
        "/api/ingest", json={"session_id": session_id, "text": "a fact", "source": "fact"}
    )
    assert res.status_code == 429
    assert "budget" in res.json()["detail"]


def test_free_endpoints_are_not_metered(client: TestClient, session_id: str, limits) -> None:
    """Health, session and graph are pure reads and must not burn the budget."""
    ingest(client, session_id, "I work at Acme.")
    for _ in range(20):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/graph", params={"session_id": session_id}).status_code == 200


def test_limits_are_per_session(client: TestClient, limits) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]

    for _ in range(limits.rate_limit_per_min):
        client.post("/api/ingest", json={"session_id": alice, "text": "a fact", "source": "fact"})

    assert client.post(
        "/api/ingest", json={"session_id": alice, "text": "a fact", "source": "fact"}
    ).status_code == 429
    assert client.post(
        "/api/ingest", json={"session_id": bob, "text": "a fact", "source": "fact"}
    ).status_code == 200
