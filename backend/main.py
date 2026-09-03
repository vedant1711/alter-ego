"""ALTER EGO — FastAPI application entrypoint."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend import sessions
from backend.config import get_settings
from backend.deps import get_llm
from backend.generation.style_transfer import build_prompt, fetch_style_samples
from backend.ingestion.embed import embed_one
from backend.ingestion.extract import extract
from backend.ingestion.summarize import maybe_summarize
from backend.memory.graph_store import GraphDelta, get_graph_store
from backend.memory.keyword_store import get_keyword_store
from backend.memory.vector_store import MemoryRecord, get_vector_store
from backend.retrieval.hybrid import estimate_tokens, retrieve
from backend.schemas import ChatIn, IngestIn, IngestOut, SessionOut

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alter_ego")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Warm both stores up front so the first request is not slowed by setup.
    await get_vector_store().ensure_ready()
    await get_graph_store().ensure_ready()
    yield
    await get_graph_store().close()


app = FastAPI(
    title="ALTER EGO",
    description="A digital twin with hybrid (graph + vector + keyword) memory.",
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, object]:
    """Liveness probe. Also used by the frontend as a cold-start warm-up ping."""
    return {"status": "ok", "offline": get_llm().offline}


@api.post("/session", response_model=SessionOut)
def create_session() -> SessionOut:
    state = sessions.create_session()
    log.info("session created: %s", state.session_id)
    return SessionOut(session_id=state.session_id)


@api.post("/ingest", response_model=IngestOut)
async def ingest(body: IngestIn) -> IngestOut:
    sessions.get_or_create(body.session_id)
    record, delta = await remember(body.session_id, body.text, body.source)
    entities, relations = delta.counts
    return IngestOut(
        memory_id=record.id, entities_added=entities, relationships_added=relations
    )


@api.get("/graph")
async def graph(session_id: str = Query(min_length=1)) -> dict[str, list[dict[str, str]]]:
    """The session's whole knowledge graph, for the live visualisation."""
    return (await get_graph_store().get_graph(session_id)).to_dict()


@api.post("/chat")
async def chat(body: ChatIn) -> EventSourceResponse:
    """Stream a reply as SSE: `token` events, then one terminal `meta` event."""
    state = sessions.get_or_create(body.session_id)

    hits = await retrieve(body.session_id, body.message)
    samples = await fetch_style_samples(body.session_id)
    prompt = build_prompt(body.message, hits, samples, state)
    log.info(
        "chat: %d memories, %d style samples (~%d tokens of context)",
        len(hits),
        len(samples),
        estimate_tokens(hits),
    )

    async def events() -> AsyncIterator[dict[str, str]]:
        reply: list[str] = []
        try:
            async for chunk in get_llm().stream(prompt):
                reply.append(chunk)
                yield {"event": "token", "data": json.dumps({"text": chunk})}
        except Exception as exc:  # noqa: BLE001 - surface any provider failure to the UI
            log.exception("chat generation failed")
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            return

        # Remember the turn only after a successful reply.
        delta = GraphDelta([], [])
        try:
            _, delta = await remember(body.session_id, body.message, "message")
            state.message_count += 1
            state.record_turn(body.message, "".join(reply).strip())
        except Exception:  # noqa: BLE001 - a failed write must not break the reply
            log.exception("failed to persist message memory")

        yield {
            "event": "meta",
            "data": json.dumps(
                {
                    "retrieved_memories": [m.model_dump() for m in hits],
                    "graph_delta": delta.to_dict(),
                }
            ),
        }

        # Compaction runs after the client has the whole reply, so its LLM call
        # never sits between the last token and the memory panel updating. If
        # the client disconnected first this is skipped, and the next turn
        # retries — the threshold is still exceeded.
        try:
            await maybe_summarize(body.session_id)
        except Exception:  # noqa: BLE001 - never let compaction break a turn
            log.exception("summarization pass failed")

    return EventSourceResponse(events())


async def remember(
    session_id: str, text: str, source_type: str
) -> tuple[MemoryRecord, GraphDelta]:
    """Ingest one piece of text into both the vector store and the graph."""
    clean = text.strip()
    record = MemoryRecord(session_id=session_id, text=clean, source_type=source_type)  # type: ignore[arg-type]

    vector = await embed_one(clean)
    await get_vector_store().add([record], [vector])

    entities, relationships = await extract(clean)
    delta = await get_graph_store().add(session_id, entities, relationships)

    # New text means the BM25 index for this session is stale.
    get_keyword_store().invalidate(session_id)
    return record, delta


app.include_router(api)
