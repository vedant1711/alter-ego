"""Hybrid retrieval: merge graph, vector and BM25 results into one ranked context.

The three legs produce scores on incomparable scales — cosine similarity, BM25
saturation, and graph adjacency — so they are fused by *rank* rather than by
score, using Reciprocal Rank Fusion:

    score(doc) = sum over legs of  weight(leg) / (RRF_K + rank(doc, leg))

RRF needs no per-leg normalisation and no tuning to be reasonable, and a memory
found by two legs naturally outranks one found by a single leg.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.config import get_settings
from backend.ingestion.embed import embed_one
from backend.memory.graph_store import get_graph_store
from backend.memory.keyword_store import get_keyword_store
from backend.memory.vector_store import get_vector_store
from backend.schemas import RetrievedMemory

RRF_K = 60

# Relative trust in each leg. Graph facts are precise but terse, so they are not
# allowed to crowd out the verbatim memories that carry the user's own wording.
LEG_WEIGHTS = {"vector": 1.0, "keyword": 0.9, "graph": 0.8}

# Rough characters-per-token for the context budget; Gemini averages ~4.
CHARS_PER_TOKEN = 4


@dataclass
class Candidate:
    text: str
    source_type: str
    legs: list[str] = field(default_factory=list)
    fused: float = 0.0


def _norm(text: str) -> str:
    """Dedupe key: same wording modulo whitespace, case and trailing punctuation."""
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")


def select_seeds(query: str, entities: dict[str, str]) -> list[str]:
    """Entities named in the query seed the traversal; 'User' anchors it otherwise."""
    lowered = query.lower()
    seeds = [key for key, name in entities.items() if name and name.lower() in lowered]
    if not seeds and "user" in entities:
        seeds = ["user"]
    return seeds[:6]


async def retrieve(session_id: str, query: str) -> list[RetrievedMemory]:
    """Run all three legs and return the fused, budget-capped top memories."""
    settings = get_settings()
    per_leg = max(settings.retrieval_top_k, 6)

    legs: dict[str, list[tuple[str, str]]] = {
        "vector": await _vector_leg(session_id, query, per_leg),
        "keyword": await _keyword_leg(session_id, query, per_leg),
        "graph": await _graph_leg(session_id, query, per_leg),
    }

    merged: dict[str, Candidate] = {}
    for leg, results in legs.items():
        weight = LEG_WEIGHTS[leg]
        for rank, (text, source_type) in enumerate(results):
            key = _norm(text)
            if not key:
                continue
            candidate = merged.get(key)
            if candidate is None:
                candidate = Candidate(text=text, source_type=source_type)
                merged[key] = candidate
            if leg not in candidate.legs:
                candidate.legs.append(leg)
            candidate.fused += weight / (RRF_K + rank + 1)

    ordered = sorted(merged.values(), key=lambda c: c.fused, reverse=True)
    return _cap(ordered, settings.retrieval_top_k, settings.max_context_chars)


def _cap(candidates: list[Candidate], top_k: int, max_chars: int) -> list[RetrievedMemory]:
    """Take the best `top_k`, stopping early if the context budget runs out."""
    out: list[RetrievedMemory] = []
    used = 0
    for candidate in candidates[:top_k]:
        cost = len(candidate.text) + 3  # the "- " bullet and newline
        if out and used + cost > max_chars:
            break
        used += cost
        out.append(
            RetrievedMemory(
                text=candidate.text,
                source=candidate.legs,
                score=round(candidate.fused, 5),
                source_type=candidate.source_type,
            )
        )
    return out


def estimate_tokens(memories: list[RetrievedMemory]) -> int:
    return sum(len(m.text) for m in memories) // CHARS_PER_TOKEN


async def _vector_leg(session_id: str, query: str, limit: int) -> list[tuple[str, str]]:
    vector = await embed_one(query)
    hits = await get_vector_store().search(session_id, vector, limit)
    return [(h.record.text, h.record.source_type) for h in hits]


async def _keyword_leg(session_id: str, query: str, limit: int) -> list[tuple[str, str]]:
    hits = await get_keyword_store().search(session_id, query, limit)
    return [(h.record.text, h.record.source_type) for h in hits]


async def _graph_leg(session_id: str, query: str, limit: int) -> list[tuple[str, str]]:
    store = get_graph_store()
    seeds = select_seeds(query, await store.entity_keys(session_id))
    if not seeds:
        return []
    triples = await store.neighbourhood(session_id, seeds)
    return [(t, "graph") for t in triples[:limit]]
