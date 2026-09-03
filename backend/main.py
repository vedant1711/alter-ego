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
from backend.ingestion.embed import embed_one
from backend.ingestion.extract import extract
from backend.memory.graph_store import GraphDelta, get_graph_store
from backend.memory.vector_store import MemoryRecord, get_vector_store
from backend.schemas import ChatIn, IngestIn, IngestOut, RetrievedMemory, SessionOut

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
    version="0.3.0",
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
    prompt = build_prompt(body.message, hits)

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for chunk in get_llm().stream(prompt):
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
    return record, delta


async def retrieve(session_id: str, query: str) -> list[RetrievedMemory]:
    """Phase 3: semantic recall plus graph traversal. Phase 4 adds keyword + rerank."""
    out: list[RetrievedMemory] = []

    vector = await embed_one(query)
    for hit in await get_vector_store().search(session_id, vector, settings.retrieval_top_k):
        out.append(
            RetrievedMemory(
                text=hit.record.text,
                source=["vector"],
                score=round(hit.score, 4),
                source_type=hit.record.source_type,
            )
        )

    store = get_graph_store()
    seeds = select_seeds(query, await store.entity_keys(session_id))
    if seeds:
        for triple in await store.neighbourhood(session_id, seeds):
            out.append(
                RetrievedMemory(text=triple, source=["graph"], score=1.0, source_type="graph")
            )

    return out


def select_seeds(query: str, entities: dict[str, str]) -> list[str]:
    """Entities named in the query seed the traversal; 'User' anchors it otherwise."""
    lowered = query.lower()
    seeds = [key for key, name in entities.items() if name and name.lower() in lowered]
    if not seeds and "user" in entities:
        seeds = ["user"]
    return seeds[:6]


def build_prompt(message: str, hits: list[RetrievedMemory]) -> str:
    context = "\n".join(f"- {h.text}" for h in hits) or "(nothing remembered yet)"
    return (
        "You are the user's digital twin. Reply to the new message AS the user, in first person.\n"
        "Keep it to a few sentences. Do not mention that you are an AI or a twin.\n\n"
        "GROUND YOUR REPLY in these retrieved memories (do not invent facts):\n"
        f"{context}\n\n"
        f"New message: {message}"
    )


app.include_router(api)
