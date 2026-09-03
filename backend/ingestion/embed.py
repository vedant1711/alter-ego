"""Text → embedding vectors (gemini-embedding-001, MRL-truncated to EMBED_DIM)."""

from __future__ import annotations

from backend.deps import get_llm

# The embeddings endpoint accepts batches; keep them modest so a single failure
# does not cost a large slice of the free daily request budget.
_BATCH = 32


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    llm = get_llm()
    out: list[list[float]] = []
    for start in range(0, len(texts), _BATCH):
        out.extend(await llm.embed(texts[start : start + _BATCH]))
    return out


async def embed_one(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]
