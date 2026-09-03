"""FR9: one click gives a stranger a working twin (acceptance criterion 1)."""

from fastapi.testclient import TestClient

from backend.tests.conftest import say


def test_load_example_seeds_memories_and_graph(client: TestClient, session_id: str) -> None:
    result = client.post("/api/load-example", json={"session_id": session_id}).json()

    assert result["name"] and result["tagline"]
    assert result["memories_added"] >= 10
    assert result["entities_added"] >= 3
    assert result["relationships_added"] >= 2
    assert result["suggested_questions"]
    assert result["already_loaded"] is False

    graph = client.get("/api/graph", params={"session_id": session_id}).json()
    assert len(graph["nodes"]) >= 3
    assert len(graph["edges"]) >= 2


def test_loading_twice_is_a_no_op(client: TestClient, session_id: str) -> None:
    client.post("/api/load-example", json={"session_id": session_id})
    second = client.post("/api/load-example", json={"session_id": session_id}).json()

    assert second["already_loaded"] is True
    assert second["memories_added"] == 0


def test_first_reply_is_grounded_in_the_persona(client: TestClient, session_id: str) -> None:
    client.post("/api/load-example", json={"session_id": session_id})
    reply, meta = say(client, session_id, "Tell me about Tidepool.")

    assert reply.strip()
    assert meta["retrieved_memories"]
    recalled = " ".join(m["text"] for m in meta["retrieved_memories"]).lower()
    assert "tidepool" in recalled


def test_persona_is_isolated_to_its_session(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]
    client.post("/api/load-example", json={"session_id": alice})

    assert client.get("/api/graph", params={"session_id": bob}).json()["nodes"] == []
