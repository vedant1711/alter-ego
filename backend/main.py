"""ALTER EGO — FastAPI application entrypoint."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend import sessions
from backend.config import get_settings
from backend.deps import get_llm
from backend.ingestion.embed import embed_one
from backend.memory.vector_store import MemoryRecord, ScoredMemory, get_vector_store
from backend.schemas import ChatIn, IngestIn, IngestOut, RetrievedMemory, SessionOut

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alter_ego")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Create the Qdrant collection up front so the first chat is not slowed by it.
    await get_vector_store().ensure_ready()
    yield


app = FastAPI(
    title="ALTER EGO",
    description="A digital twin with hybrid (graph + vector + keyword) memory.",
    version="0.2.0",
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
    record = await store_memory(body.session_id, body.text, body.source)
    return IngestOut(memory_id=record.id)


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
        try:
            await store_memory(body.session_id, body.message, "message")
            state.message_count += 1
        except Exception:  # noqa: BLE001 - a failed write must not break the reply
            log.exception("failed to persist message memory")

        yield {
            "event": "meta",
            "data": json.dumps(
                {
                    "retrieved_memories": [m.model_dump() for m in as_retrieved(hits)],
                    "graph_delta": None,
                }
            ),
        }

    return EventSourceResponse(events())


async def store_memory(session_id: str, text: str, source_type: str) -> MemoryRecord:
    """Embed one piece of text and file it in the session's vector memory."""
    record = MemoryRecord(session_id=session_id, text=text.strip(), source_type=source_type)  # type: ignore[arg-type]
    vector = await embed_one(record.text)
    await get_vector_store().add([record], [vector])
    return record


async def retrieve(session_id: str, query: str) -> list[ScoredMemory]:
    """Phase 2: semantic recall only. Phases 3-4 add the graph and keyword legs."""
    vector = await embed_one(query)
    return await get_vector_store().search(session_id, vector, settings.retrieval_top_k)


def as_retrieved(hits: list[ScoredMemory]) -> list[RetrievedMemory]:
    return [
        RetrievedMemory(
            text=h.record.text,
            source=["vector"],
            score=round(h.score, 4),
            source_type=h.record.source_type,
        )
        for h in hits
    ]


def build_prompt(message: str, hits: list[ScoredMemory]) -> str:
    context = "\n".join(f"- {h.record.text}" for h in hits) or "(nothing remembered yet)"
    return (
        "You are the user's digital twin. Reply to the new message AS the user, in first person.\n"
        "Keep it to a few sentences. Do not mention that you are an AI or a twin.\n\n"
        "GROUND YOUR REPLY in these retrieved memories (do not invent facts):\n"
        f"{context}\n\n"
        f"New message: {message}"
    )


app.include_router(api)
