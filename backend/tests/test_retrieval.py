"""FR4: the three legs merge, dedupe, tag their sources, and stay in budget."""

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.retrieval.hybrid import (
    Candidate,
    _cap,
    _ensure_leg_coverage,
    _norm,
    retrieve,
    select_seeds,
)
from backend.tests.conftest import ingest


def test_norm_collapses_incidental_differences() -> None:
    assert _norm("  I work  at Acme.  ") == _norm("i work at acme")


def test_select_seeds_prefers_entities_named_in_the_query() -> None:
    entities = {"user": "User", "acme": "Acme", "lisbon": "Lisbon"}
    assert select_seeds("what do you do at Acme?", entities) == ["acme"]


def test_select_seeds_falls_back_to_the_user_node() -> None:
    assert select_seeds("how are you?", {"user": "User", "acme": "Acme"}) == ["user"]
    assert select_seeds("how are you?", {"acme": "Acme"}) == []


def test_cap_respects_the_context_budget() -> None:
    candidates = [Candidate(text="x" * 100, source_type="fact", legs=["vector"], fused=1.0 / (i + 1)) for i in range(10)]
    capped = _cap(candidates, top_k=10, max_chars=250)
    assert len(capped) == 2  # each costs 103 chars: 2 * 103 <= 250 < 3 * 103


def test_cap_always_returns_at_least_one_memory() -> None:
    """A single oversized memory is better than an empty context."""
    capped = _cap([Candidate(text="x" * 9000, source_type="fact", legs=["vector"])], 6, 100)
    assert len(capped) == 1


async def test_multi_leg_memories_outrank_single_leg_ones(
    client: TestClient, session_id: str
) -> None:
    ingest(client, session_id, "My side project is Tidepool, a tide-forecasting app.")
    ingest(client, session_id, "I drink too much coffee.")
    ingest(client, session_id, "I once ran a half marathon in Porto.")

    hits = await retrieve(session_id, "tell me about Tidepool")
    assert hits
    assert "Tidepool" in hits[0].text
    assert len(hits[0].source) > 1, "expected the top hit to be found by several legs"


async def test_results_are_deduped_across_legs(client: TestClient, session_id: str) -> None:
    ingest(client, session_id, "I live in Lisbon.")
    hits = await retrieve(session_id, "where do you live?")
    texts = [_norm(h.text) for h in hits]
    assert len(texts) == len(set(texts))


async def test_never_exceeds_top_k(client: TestClient, session_id: str) -> None:
    for i in range(12):
        ingest(client, session_id, f"Fact number {i} about topic {i}.")
    hits = await retrieve(session_id, "tell me a fact about topic 3")
    assert len(hits) <= get_settings().retrieval_top_k


async def test_empty_session_retrieves_nothing(client: TestClient, session_id: str) -> None:
    assert await retrieve(session_id, "who are you?") == []


def test_leg_coverage_promotes_an_unrepresented_leg() -> None:
    ordered = [
        Candidate(text=f"m{i}", source_type="fact", legs=["vector", "keyword"], fused=1.0 - i / 100)
        for i in range(4)
    ] + [Candidate(text="triple", source_type="graph", legs=["graph"], fused=0.01)]

    selected = _ensure_leg_coverage(ordered, top_k=4)
    assert len(selected) == 4
    assert "graph" in {leg for c in selected for leg in c.legs}
    # The strongest results survive; only the weakest displaceable one is swapped.
    assert selected[0].text == "m0"


def test_leg_coverage_never_drops_a_leg_to_add_another() -> None:
    """Swapping must not orphan the leg the displaced memory was carrying."""
    ordered = [
        Candidate(text="only-vector", source_type="fact", legs=["vector"], fused=0.9),
        Candidate(text="only-keyword", source_type="fact", legs=["keyword"], fused=0.8),
        Candidate(text="graph-triple", source_type="graph", legs=["graph"], fused=0.1),
    ]
    selected = _ensure_leg_coverage(ordered, top_k=2)
    assert {leg for c in selected for leg in c.legs} == {"vector", "keyword"}


def test_leg_coverage_is_a_no_op_when_nothing_is_left_over() -> None:
    ordered = [Candidate(text="a", source_type="fact", legs=["vector"], fused=1.0)]
    assert _ensure_leg_coverage(ordered, top_k=6) == ordered


async def test_all_three_legs_appear_for_the_example_persona(
    client: TestClient, session_id: str
) -> None:
    """The demo's transparency story depends on the graph leg staying visible."""
    client.post("/api/load-example", json={"session_id": session_id})
    hits = await retrieve(session_id, "Tell me about Tidepool.")

    legs = {leg for h in hits for leg in h.source}
    assert legs == {"vector", "keyword", "graph"}
