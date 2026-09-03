from fastapi.testclient import TestClient

from backend.tests.conftest import ingest, say


def test_health_reports_ok(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    # No GEMINI_API_KEY in the test environment.
    assert body["offline"] is True


def test_session_ids_are_unique(client: TestClient) -> None:
    ids = {client.post("/api/session").json()["session_id"] for _ in range(5)}
    assert len(ids) == 5


def test_ingest_reports_graph_growth(client: TestClient, session_id: str) -> None:
    result = ingest(client, session_id, "I work at Acme as a product designer.")
    assert result["memory_id"]
    assert result["entities_added"] >= 2
    assert result["relationships_added"] >= 1


def test_chat_streams_tokens_then_meta(client: TestClient, session_id: str) -> None:
    ingest(client, session_id, "I live in Lisbon.")
    reply, meta = say(client, session_id, "where do you live?")

    assert reply.strip()
    assert "retrieved_memories" in meta
    assert meta["retrieved_memories"], "expected the reply to be grounded in memories"
    assert meta["graph_delta"] is not None


def test_chat_rejects_empty_message(client: TestClient, session_id: str) -> None:
    res = client.post("/api/chat", json={"session_id": session_id, "message": ""})
    assert res.status_code == 422


def test_graph_endpoint_shape(client: TestClient, session_id: str) -> None:
    ingest(client, session_id, "I work at Acme.")
    graph = client.get("/api/graph", params={"session_id": session_id}).json()

    assert {n["label"] for n in graph["nodes"]} >= {"User", "Acme"}
    assert all({"id", "label", "type"} == set(n) for n in graph["nodes"])
    assert all({"source", "target", "type"} == set(e) for e in graph["edges"])


def test_retrieved_memories_are_tagged_by_leg(client: TestClient, session_id: str) -> None:
    ingest(client, session_id, "My side project is Tidepool, a tide-forecasting app.")
    _, meta = say(client, session_id, "tell me about Tidepool")

    legs = {leg for m in meta["retrieved_memories"] for leg in m["source"]}
    assert legs <= {"graph", "vector", "keyword"}
    assert legs & {"vector", "keyword"}
    assert any("graph" in m["source"] for m in meta["retrieved_memories"])
