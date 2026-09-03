"""BM25 keyword search over a session's memories — the third retrieval leg.

Runs in-process (`rank_bm25`), so it costs no external service. The index is
rebuilt from the vector store's payloads and cached until the session writes
again, which keeps a chat turn to one extra scroll at most.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from rank_bm25 import BM25Okapi

from backend.memory.vector_store import MemoryRecord, VectorStore, get_vector_store

_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Words too common to discriminate between memories.
_STOPWORDS = frozenset(
    """a an and are as at be but by do does did for from had has have he her his i
    if in is it its me my of on or our she that the their them then there they this
    to was we were what when where which who why will with you your""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


@dataclass
class ScoredMemory:
    record: MemoryRecord
    score: float


class KeywordStore:
    def __init__(self, vector_store: VectorStore) -> None:
        self._vectors = vector_store
        self._cache: dict[str, tuple[BM25Okapi, list[MemoryRecord], list[set[str]]]] = {}

    def invalidate(self, session_id: str) -> None:
        """Called after any write, so the next search reindexes."""
        self._cache.pop(session_id, None)

    async def _index(
        self, session_id: str
    ) -> tuple[BM25Okapi, list[MemoryRecord], list[set[str]]] | None:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached

        records = await self._vectors.list_session(session_id)
        corpus = [tokenize(r.text) for r in records]
        # BM25Okapi divides by the corpus average length, so an all-empty corpus
        # would blow up; treat it as "no index".
        if not any(corpus):
            return None

        index = (BM25Okapi(corpus), records, [set(doc) for doc in corpus])
        self._cache[session_id] = index
        return index

    async def search(self, session_id: str, query: str, limit: int) -> list[ScoredMemory]:
        tokens = tokenize(query)
        if not tokens:
            return []
        index = await self._index(session_id)
        if index is None:
            return []

        bm25, records, vocabularies = index
        scores = bm25.get_scores(tokens)
        wanted = set(tokens)

        # Relevance is decided by term overlap, not by the sign of the score.
        # BM25's IDF goes negative for a term that appears in every document,
        # so on a small corpus — which is every session's first few turns — a
        # "score > 0" filter would throw away the only real matches.
        hits = [
            ScoredMemory(record, float(score))
            for record, score, vocabulary in zip(records, scores, vocabularies, strict=True)
            if wanted & vocabulary
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]


@lru_cache(maxsize=1)
def get_keyword_store() -> KeywordStore:
    return KeywordStore(get_vector_store())
