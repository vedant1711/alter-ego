"""Qdrant-backed vector memory, always scoped to a single session.

With QDRANT_URL set this talks to a Qdrant Cloud free cluster. Without it the
client runs in local `:memory:` mode — the same API, no server — so the app is
usable before anything is provisioned.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from qdrant_client import AsyncQdrantClient, models

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

SourceType = Literal["sample", "fact", "message", "summary"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryRecord:
    session_id: str
    text: str
    source_type: SourceType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now)
    # Set once a record has been folded into a summary; excluded from recall
    # thereafter so the twin does not see the same content twice.
    summarized: bool = False


@dataclass
class ScoredMemory:
    record: MemoryRecord
    score: float


def _payload(record: MemoryRecord) -> dict[str, object]:
    return {
        "session_id": record.session_id,
        "text": record.text,
        "source_type": record.source_type,
        "created_at": record.created_at,
        "summarized": record.summarized,
    }


def _record(point_id: str, payload: dict) -> MemoryRecord:
    return MemoryRecord(
        id=str(point_id),
        session_id=payload["session_id"],
        text=payload.get("text", ""),
        source_type=payload.get("source_type", "message"),
        created_at=payload.get("created_at", ""),
        summarized=bool(payload.get("summarized", False)),
    )


def _session_filter(session_id: str, *, include_summarized: bool) -> models.Filter:
    """Session isolation lives here — no read path builds a filter without it."""
    must: list[models.Condition] = [
        models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id))
    ]
    if not include_summarized:
        must.append(
            models.FieldCondition(key="summarized", match=models.MatchValue(value=False))
        )
    return models.Filter(must=must)


class VectorStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._collection = settings.qdrant_collection
        self.remote = settings.qdrant_enabled
        if self.remote:
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                timeout=30,
            )
        else:
            log.warning("QDRANT_URL unset — using in-process Qdrant (memories are not durable)")
            self._client = AsyncQdrantClient(":memory:")
        self._ready = False
        self._lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    self._collection,
                    vectors_config=models.VectorParams(
                        size=self._settings.embed_dim, distance=models.Distance.COSINE
                    ),
                )
            # Cloud Qdrant needs explicit payload indexes for filtered search to
            # stay fast. Local mode ignores them, so only ask when remote.
            if self.remote:
                for key, schema in (
                    ("session_id", models.PayloadSchemaType.KEYWORD),
                    ("source_type", models.PayloadSchemaType.KEYWORD),
                ):
                    try:
                        await self._client.create_payload_index(self._collection, key, schema)
                    except Exception:  # noqa: BLE001 - already-indexed raises provider-specific errors
                        pass
            self._ready = True

    async def add(self, records: list[MemoryRecord], vectors: list[list[float]]) -> None:
        if not records:
            return
        await self.ensure_ready()
        await self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(id=r.id, vector=v, payload=_payload(r))
                for r, v in zip(records, vectors, strict=True)
            ],
        )

    async def search(
        self, session_id: str, vector: list[float], limit: int
    ) -> list[ScoredMemory]:
        await self.ensure_ready()
        res = await self._client.query_points(
            self._collection,
            query=vector,
            limit=limit,
            query_filter=_session_filter(session_id, include_summarized=False),
            with_payload=True,
        )
        return [ScoredMemory(_record(p.id, p.payload or {}), float(p.score)) for p in res.points]

    async def list_session(
        self,
        session_id: str,
        *,
        source_types: list[str] | None = None,
        include_summarized: bool = False,
        limit: int = 500,
    ) -> list[MemoryRecord]:
        await self.ensure_ready()
        flt = _session_filter(session_id, include_summarized=include_summarized)
        if source_types:
            flt.must.append(  # type: ignore[union-attr]
                models.FieldCondition(key="source_type", match=models.MatchAny(any=source_types))
            )
        points, _ = await self._client.scroll(
            self._collection, scroll_filter=flt, limit=limit, with_payload=True
        )
        records = [_record(p.id, p.payload or {}) for p in points]
        records.sort(key=lambda r: r.created_at)
        return records

    async def set_summarized(self, ids: list[str]) -> None:
        """Mark records as folded into a summary, which drops them from recall."""
        if not ids:
            return
        await self.ensure_ready()
        await self._client.set_payload(
            self._collection,
            payload={"summarized": True},
            points=ids,
        )

    async def delete_session(self, session_id: str) -> None:
        await self.ensure_ready()
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="session_id", match=models.MatchValue(value=session_id)
                        )
                    ]
                )
            ),
        )


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore(get_settings())
