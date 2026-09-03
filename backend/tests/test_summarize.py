"""FR6: old memories compress into summaries and stay recallable (criterion 7)."""

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.ingestion.summarize import maybe_summarize
from backend.memory.vector_store import get_vector_store
from backend.tests.conftest import say


async def test_below_threshold_nothing_is_compacted(client: TestClient, session_id: str) -> None:
    for i in range(3):
        say(client, session_id, f"message {i}")
    assert await maybe_summarize(session_id) == []


async def test_oldest_messages_compact_into_a_summary(
    client: TestClient, session_id: str
) -> None:
    settings = get_settings()
    store = get_vector_store()

    turns = settings.summary_threshold + 1
    for i in range(turns):
        say(client, session_id, f"memory number {i} concerns topic {i}")

    live = await store.list_session(session_id)
    everything = await store.list_session(session_id, include_summarized=True)

    summaries = [r for r in live if r.source_type == "summary"]
    assert len(summaries) == 1
    assert summaries[0].text

    # The batch is retired from recall, not deleted.
    live_messages = [r for r in live if r.source_type == "message"]
    assert len(live_messages) == turns - settings.summary_batch
    assert len(everything) == turns + 1

    retired = [r for r in everything if r.summarized]
    assert len(retired) == settings.summary_batch
    # The oldest messages are the ones retired.
    assert {r.text for r in retired} == {f"memory number {i} concerns topic {i}" for i in range(settings.summary_batch)}


async def test_summary_remains_retrievable(client: TestClient, session_id: str) -> None:
    from backend.retrieval.hybrid import retrieve

    for i in range(get_settings().summary_threshold + 1):
        say(client, session_id, f"memory number {i} concerns topic {i}")

    hits = await retrieve(session_id, "what did we discuss earlier?")
    assert any(h.source_type == "summary" for h in hits)


async def test_compaction_is_scoped_to_one_session(client: TestClient) -> None:
    alice = client.post("/api/session").json()["session_id"]
    bob = client.post("/api/session").json()["session_id"]

    for i in range(get_settings().summary_threshold + 1):
        say(client, alice, f"alice memory {i}")
    say(client, bob, "bob's single memory")

    store = get_vector_store()
    bob_records = await store.list_session(bob, include_summarized=True)
    assert len(bob_records) == 1
    assert not bob_records[0].summarized
