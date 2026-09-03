"""ALTER EGO — FastAPI application entrypoint."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend import sessions
from backend.config import get_settings
from backend.deps import get_llm
from backend.schemas import ChatIn, SessionOut

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("alter_ego")

settings = get_settings()

app = FastAPI(
    title="ALTER EGO",
    description="A digital twin with hybrid (graph + vector + keyword) memory.",
    version="0.1.0",
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


@api.post("/chat")
async def chat(body: ChatIn) -> EventSourceResponse:
    """Stream a reply as SSE: `token` events, then one terminal `meta` event."""
    state = sessions.get_or_create(body.session_id)
    state.message_count += 1

    async def events() -> AsyncIterator[dict[str, str]]:
        try:
            async for chunk in get_llm().stream(_prompt(body.message)):
                yield {"event": "token", "data": json.dumps({"text": chunk})}
        except Exception as exc:  # noqa: BLE001 - surface any provider failure to the UI
            log.exception("chat generation failed")
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}
            return
        yield {"event": "meta", "data": json.dumps({"retrieved_memories": [], "graph_delta": None})}

    return EventSourceResponse(events())


def _prompt(message: str) -> str:
    # Phase 1 placeholder: no memory yet, so the twin has nothing to ground in.
    return (
        "You are the user's digital twin. Reply to the new message AS the user, in first person.\n"
        "Keep it to a few sentences. Do not mention that you are an AI or a twin.\n\n"
        f"New message: {message}"
    )


app.include_router(api)
