"""ALTER EGO — FastAPI application entrypoint."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend import persona, sessions
from backend.config import get_settings
from backend.deps import get_llm, quota_message
from backend.guardrails import enforce
from backend.generation.style_transfer import build_prompt, fetch_style_samples
from backend.ingestion.embed import embed_one, embed_texts
from backend.ingestion.extract import extract
from backend.ingestion.summarize import maybe_summarize
from backend.memory.graph_store import (
    GraphDelta,
    classify_error,
    get_graph_store,
    warning_text,
)
from backend.memory.keyword_store import get_keyword_store
from backend.memory.vector_store import MemoryRecord, get_vector_store
from backend.retrieval.hybrid import estimate_tokens, retrieve
from backend.schemas import (
    ChatIn,
    IngestIn,
    IngestOut,
    LoadExampleIn,
    LoadExampleOut,
    SessionOut,
    Warning,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alter_ego")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Warm the stores so the first request is not slowed by setup — but never
    # let a sleeping one stop the app booting. A paused Neo4j Aura instance
    # should cost the graph, not the whole service.
    for name, warm in (
        ("vector", get_vector_store().ensure_ready),
        ("graph", get_graph_store().ensure_ready),
    ):
        try:
            await warm()
        except Exception as exc:  # noqa: BLE001 - degrade, never fail to start
            log.warning("%s store unavailable at startup: %s", name, exc)
    yield
    try:
        await get_graph_store().close()
    except Exception:  # noqa: BLE001 - shutdown is best-effort
        log.debug("graph store close failed", exc_info=True)


app = FastAPI(
    title="ALTER EGO",
    description="A digital twin with hybrid (graph + vector + keyword) memory.",
    version="1.0.0",
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
async def health() -> dict[str, object]:
    """Liveness probe, warm-up ping, and store-reachability report.

    The graph probe is what lets the UI say "Aura is paused, resume it" instead
    of leaving the graph mysteriously empty.
    """
    store = get_graph_store()
    graph_ok, graph_code = await store.probe()
    warnings: list[Warning] = []

    if not graph_ok:
        code = graph_code or "graph_error"
        message, action = warning_text(code)
        warnings.append(Warning(code=code, message=message, action=action))

    return {
        "status": "ok",
        "offline": get_llm().offline,
        "stores": {
            "graph": {"durable": store.remote, "reachable": graph_ok},
            "vector": {"durable": get_vector_store().remote, "reachable": True},
        },
        "warnings": [w.model_dump() for w in warnings],
    }


@api.post("/session", response_model=SessionOut)
def create_session() -> SessionOut:
    state = sessions.create_session()
    log.info("session created: %s", state.session_id)
    return SessionOut(session_id=state.session_id)


@api.post("/ingest", response_model=IngestOut)
async def ingest(body: IngestIn) -> IngestOut:
    state = sessions.get_or_create(body.session_id)
    enforce(state, text=body.text)
    record, delta, warnings = await remember(body.session_id, body.text, body.source)
    entities, relations = delta.counts
    return IngestOut(
        memory_id=record.id,
        entities_added=entities,
        relationships_added=relations,
        warnings=warnings,
    )


@api.get("/graph")
async def graph(session_id: str = Query(min_length=1)) -> dict[str, object]:
    """The session's whole knowledge graph, for the live visualisation.

    An unreachable graph returns an empty one with a warning rather than a 500,
    so the panel can explain itself instead of the UI silently failing.
    """
    try:
        payload: dict[str, object] = dict(
            (await get_graph_store().get_graph(session_id)).to_dict()
        )
        payload["warnings"] = []
        return payload
    except Exception as exc:  # noqa: BLE001 - degrade to an empty graph
        code = classify_error(exc)
        message, action = warning_text(code)
        log.warning("graph read failed (%s): %s", code, exc)
        return {
            "nodes": [],
            "edges": [],
            "warnings": [Warning(code=code, message=message, action=action).model_dump()],
        }


@api.post("/load-example", response_model=LoadExampleOut)
async def load_example(body: LoadExampleIn) -> LoadExampleOut:
    """Seed the session with the bundled persona (FR9)."""
    state = sessions.get_or_create(body.session_id)
    profile = persona.load()

    if state.example_loaded:
        return LoadExampleOut(
            name=profile["name"],
            tagline=profile["tagline"],
            memories_added=0,
            entities_added=0,
            relationships_added=0,
            suggested_questions=profile["suggested_questions"],
            already_loaded=True,
        )

    # Bulk loading costs about two model calls, so it is metered as two requests.
    enforce(state, cost=2)
    items = persona.texts()
    delta, warnings = await remember_many(body.session_id, items)
    state.example_loaded = True

    entities, relationships = delta.counts
    log.info("example persona loaded into session %s", body.session_id)
    return LoadExampleOut(
        name=profile["name"],
        tagline=profile["tagline"],
        memories_added=len(items),
        entities_added=entities,
        relationships_added=relationships,
        suggested_questions=profile["suggested_questions"],
        warnings=warnings,
    )


@api.post("/chat")
async def chat(body: ChatIn) -> EventSourceResponse:
    """Stream a reply as SSE: `token` events, then one terminal `meta` event."""
    state = sessions.get_or_create(body.session_id)
    enforce(state, text=body.message)

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
            # A raw provider error is a wall of JSON; quota failures get a
            # sentence the visitor can act on instead.
            message = quota_message(exc) or f"Generation failed: {exc}"
            yield {"event": "error", "data": json.dumps({"message": message})}
            return

        # Remember the turn only after a successful reply.
        delta, warnings = GraphDelta([], []), []
        try:
            _, delta, warnings = await remember(body.session_id, body.message, "message")
            state.record_turn(body.message, "".join(reply).strip())
        except Exception:  # noqa: BLE001 - a failed write must not break the reply
            log.exception("failed to persist message memory")

        yield {
            "event": "meta",
            "data": json.dumps(
                {
                    "retrieved_memories": [m.model_dump() for m in hits],
                    "graph_delta": delta.to_dict(),
                    "warnings": [w.model_dump() for w in warnings],
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
) -> tuple[MemoryRecord, GraphDelta, list[Warning]]:
    """Ingest one piece of text into both the vector store and the graph."""
    clean = text.strip()
    record = MemoryRecord(session_id=session_id, text=clean, source_type=source_type)  # type: ignore[arg-type]

    vector = await embed_one(clean)
    await get_vector_store().add([record], [vector])

    entities, relationships = await extract(clean)
    delta, warnings = await write_graph(session_id, entities, relationships)

    # New text means the BM25 index for this session is stale.
    get_keyword_store().invalidate(session_id)
    return record, delta, warnings


async def write_graph(session_id, entities, relationships) -> tuple[GraphDelta, list[Warning]]:
    """Write to the graph, downgrading a failure to a warning.

    The vector write has already succeeded by this point, so the memory is
    saved and will still be recalled — only the graph leg is degraded. Raising
    here would tell the user their memory was lost when it was not.
    """
    try:
        return await get_graph_store().add(session_id, entities, relationships), []
    except Exception as exc:  # noqa: BLE001 - any store failure degrades, never fails
        code = classify_error(exc)
        message, action = warning_text(code)
        log.warning("graph write failed (%s): %s", code, exc)
        return GraphDelta([], []), [Warning(code=code, message=message, action=action)]


async def remember_many(
    session_id: str, items: list[tuple[str, str]]
) -> tuple[GraphDelta, list[Warning]]:
    """Ingest many texts using one batched embedding call and one extraction call.

    Extracting each item separately would be more precise, but it would also be
    one model call per item — a minute of wall clock against the free tier's
    per-minute ceiling, on the very path a first-time visitor takes.
    """
    records = [
        MemoryRecord(session_id=session_id, text=text.strip(), source_type=source)  # type: ignore[arg-type]
        for text, source in items
    ]
    vectors = await embed_texts([r.text for r in records])
    await get_vector_store().add(records, vectors)

    facts = "\n".join(r.text for r in records if r.source_type == "fact")
    entities, relationships = await extract(facts)
    delta, warnings = await write_graph(session_id, entities, relationships)

    get_keyword_store().invalidate(session_id)
    return delta, warnings


app.include_router(api)
