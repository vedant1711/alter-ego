"""In-process registry of anonymous sessions.

Sessions are ephemeral by design (PRD non-goal: no accounts). Restarting the
backend drops them; the durable memories in Neo4j/Qdrant are keyed by
`session_id`, so a client holding its id keeps its twin across restarts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

# Sessions idle for longer than this are pruned to bound memory on Render Free.
SESSION_TTL_S = 60 * 60 * 6


@dataclass
class SessionState:
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    request_count: int = 0
    # Sliding window of request timestamps, for the per-minute rate limit.
    recent_requests: list[float] = field(default_factory=list)
    # Set once /load-example has seeded this session, so a double click does
    # not ingest the persona twice.
    example_loaded: bool = False
    # Short rolling transcript for conversational continuity. Long-term recall
    # is the retriever's job; this only keeps the last few turns coherent.
    recent_turns: list[tuple[str, str]] = field(default_factory=list)

    def record_turn(self, user_text: str, twin_text: str, keep: int = 4) -> None:
        self.recent_turns.append((user_text, twin_text))
        del self.recent_turns[:-keep]


_SESSIONS: dict[str, SessionState] = {}


def create_session() -> SessionState:
    _prune()
    state = SessionState(session_id=uuid.uuid4().hex)
    _SESSIONS[state.session_id] = state
    return state


def get_session(session_id: str) -> SessionState | None:
    state = _SESSIONS.get(session_id)
    if state is not None:
        state.last_seen = time.time()
    return state


def get_or_create(session_id: str) -> SessionState:
    """Adopt a client-supplied id after a backend restart rather than 404ing."""
    state = get_session(session_id)
    if state is None:
        state = SessionState(session_id=session_id)
        _SESSIONS[session_id] = state
    return state


def _prune() -> None:
    cutoff = time.time() - SESSION_TTL_S
    for sid in [s for s, st in _SESSIONS.items() if st.last_seen < cutoff]:
        _SESSIONS.pop(sid, None)


def clear_all() -> None:
    """Test helper."""
    _SESSIONS.clear()
