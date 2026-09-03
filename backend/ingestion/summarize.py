"""Recursive summarization (PRD section 6.3).

Once a session accumulates more than SUMMARY_THRESHOLD live memories of a given
kind, the oldest SUMMARY_BATCH of them are compressed into a single `summary`
memory and marked `summarized`, which removes them from vector and BM25 recall
without deleting anything.

It is recursive because summaries are compacted by the same rule: enough of
them and they collapse into a summary-of-summaries. Old context therefore
decays in resolution rather than disappearing.
"""

from __future__ import annotations

import logging

from backend import prompts
from backend.config import get_settings
from backend.deps import get_llm
from backend.ingestion.embed import embed_one
from backend.memory.keyword_store import get_keyword_store
from backend.memory.vector_store import MemoryRecord, get_vector_store

log = logging.getLogger(__name__)

# Compaction walks message memories first, then the summaries they produced.
_LEVELS = ("message", "summary")


async def maybe_summarize(session_id: str) -> list[MemoryRecord]:
    """Compact whatever has grown past threshold. Returns the summaries created."""
    created: list[MemoryRecord] = []
    for level in _LEVELS:
        record = await _compact(session_id, level)
        if record is not None:
            created.append(record)
    return created


async def _compact(session_id: str, source_type: str) -> MemoryRecord | None:
    settings = get_settings()
    store = get_vector_store()

    live = await store.list_session(session_id, source_types=[source_type])
    if len(live) <= settings.summary_threshold:
        return None

    batch = live[: settings.summary_batch]  # list_session returns oldest first
    if len(batch) < 2:
        return None

    joined = "\n".join(f"- {r.text}" for r in batch)
    try:
        summary_text = (
            await get_llm().complete(
                prompts.render("summarize", batch=joined.replace('"""', "'''")),
                temperature=0.2,
            )
        ).strip()
    except Exception:  # noqa: BLE001 - compaction is best-effort, retried next turn
        log.exception("summarization failed for session %s", session_id)
        return None

    if not summary_text:
        return None

    record = MemoryRecord(session_id=session_id, text=summary_text, source_type="summary")
    vector = await embed_one(summary_text)
    await store.add([record], [vector])

    # Only retire the originals once the summary is safely stored.
    await store.set_summarized(session_id, [r.id for r in batch])
    get_keyword_store().invalidate(session_id)

    log.info(
        "compacted %d %s memories into summary %s (session %s)",
        len(batch),
        source_type,
        record.id,
        session_id,
    )
    return record
