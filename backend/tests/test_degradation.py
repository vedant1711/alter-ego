"""A sleeping store degrades the feature that needs it, never the whole app.

Neo4j Aura Free pauses itself after about a week idle. Before these tests the
driver's ServiceUnavailable propagated out of startup and the app refused to
boot at all, and an ingest returned a 500 after the memory had already been
written to the vector store — telling the user their memory was lost when it
was not.
"""

import pytest
from fastapi.testclient import TestClient

from backend.memory.graph_store import classify_error, warning_text
from backend.tests.conftest import ingest, say


class Paused(Exception):
    """Stands in for what the driver raises against a paused Aura instance."""

    def __init__(self) -> None:
        super().__init__("Unable to retrieve routing information")


@pytest.fixture
def graph_down(monkeypatch):
    """Make every graph operation fail the way a paused instance does."""
    from backend.memory.graph_store import NetworkXGraphStore

    async def boom(*_args, **_kwargs):
        raise Paused()

    async def probe_fails(*_args, **_kwargs):
        return False, "graph_unavailable"

    for name in ("add", "get_graph", "entity_keys", "neighbourhood", "ensure_ready"):
        monkeypatch.setattr(NetworkXGraphStore, name, boom)
    monkeypatch.setattr(NetworkXGraphStore, "probe", probe_fails)


def codes(warnings) -> set[str]:
    return {w["code"] for w in warnings}


def test_paused_instance_is_named_not_just_reported() -> None:
    # "Unavailable" sends someone hunting a typo; "paused" points at the button
    # that fixes it.
    assert classify_error(Paused()) == "graph_unavailable"
    message, action = warning_text("graph_unavailable")
    assert "pause" in message.lower()
    assert "resume" in action.lower()


def test_app_still_starts_and_reports_the_outage(client: TestClient, graph_down) -> None:
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["stores"]["graph"]["reachable"] is False
    assert codes(body["warnings"]) == {"graph_unavailable"}


def test_ingest_keeps_the_memory_and_warns(client: TestClient, session_id: str, graph_down) -> None:
    res = client.post(
        "/api/ingest",
        json={"session_id": session_id, "text": "I work at Acme.", "source": "fact"},
    )
    assert res.status_code == 200, "a sleeping graph must not fail the whole ingest"

    body = res.json()
    assert body["memory_id"]
    assert body["entities_added"] == 0
    assert codes(body["warnings"]) == {"graph_unavailable"}


def test_the_memory_really_was_stored(client: TestClient, session_id: str, graph_down) -> None:
    ingest(client, session_id, "My passphrase is orange marmalade.")
    _, meta = say(client, session_id, "what is my passphrase?")

    recalled = " ".join(m["text"] for m in meta["retrieved_memories"]).lower()
    assert "marmalade" in recalled


def test_chat_still_answers_on_the_remaining_legs(
    client: TestClient, session_id: str, graph_down
) -> None:
    ingest(client, session_id, "I work at Acme as a designer.")
    reply, meta = say(client, session_id, "where do you work?")

    assert reply.strip()
    legs = {leg for m in meta["retrieved_memories"] for leg in m["source"]}
    assert legs, "vector and keyword should still contribute"
    assert "graph" not in legs
    assert codes(meta["warnings"]) == {"graph_unavailable"}


def test_graph_endpoint_returns_empty_rather_than_500(
    client: TestClient, session_id: str, graph_down
) -> None:
    res = client.get("/api/graph", params={"session_id": session_id})

    assert res.status_code == 200
    body = res.json()
    assert body["nodes"] == [] and body["edges"] == []
    assert codes(body["warnings"]) == {"graph_unavailable"}


def test_healthy_graph_reports_no_warnings(client: TestClient, session_id: str) -> None:
    assert client.get("/api/health").json()["warnings"] == []
    result = ingest(client, session_id, "I work at Acme.")
    assert result["warnings"] == []
    assert result["entities_added"] > 0
