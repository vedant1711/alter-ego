"""FR8: every store access is scoped to one session (acceptance criterion 5)."""

from fastapi.testclient import TestClient

from backend.memory.graph_store import get_graph_store
from backend.memory.keyword_store import get_keyword_store
from backend.memory.vector_store import get_vector_store
from backend.tests.conftest import ingest, say


def test_sessions_do_not_share_memories_or_graph(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]

    ingest(client, alice, "I work at Acme and my dog is called Biscuit.")
    ingest(client, bob, "I work at Globex and I sail every weekend.")

    # Bob's graph is checked before he chats, so nothing he says himself can
    # be mistaken for a leak from Alice.
    bob_graph = client.get("/api/graph", params={"session_id": bob}).json()
    labels = {n["label"].lower() for n in bob_graph["nodes"]}
    assert "globex" in labels
    assert "acme" not in labels and "biscuit" not in labels

    _, meta = say(client, bob, "what was that dog called?")
    recalled = " ".join(m["text"] for m in meta["retrieved_memories"]).lower()
    assert "biscuit" not in recalled
    assert "acme" not in recalled


async def test_vector_search_filters_by_session(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]
    ingest(client, alice, "The passphrase is orange marmalade.")

    store = get_vector_store()
    # Query with alice's own vector, but from bob's session.
    vector = (await store.list_session(alice))[0]
    from backend.ingestion.embed import embed_one

    query = await embed_one("passphrase orange marmalade")
    assert vector.text
    assert await store.search(alice, query, 5)
    assert await store.search(bob, query, 5) == []


async def test_keyword_search_filters_by_session(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]
    ingest(client, alice, "The passphrase is orange marmalade.")

    store = get_keyword_store()
    assert await store.search(alice, "marmalade", 5)
    assert await store.search(bob, "marmalade", 5) == []


async def test_graph_traversal_filters_by_session(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]
    ingest(client, alice, "I work at Acme.")
    ingest(client, bob, "I work at Globex.")

    store = get_graph_store()
    assert "acme" in await store.entity_keys(alice)
    assert "acme" not in await store.entity_keys(bob)

    # Seeding bob's traversal with one of alice's node keys must return nothing.
    assert await store.neighbourhood(bob, ["acme"]) == []
