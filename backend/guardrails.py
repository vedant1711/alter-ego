"""Per-session guardrails (PRD section 13).

The demo is public and the Gemini key is shared by everyone who visits, so the
budget has to be defended per session: a sliding-window rate limit, a hard
lifetime cap, and a maximum message length.

Only the endpoints that spend LLM or embedding quota are metered. /health,
/session and /graph are pure reads and stay free, so the live graph can refresh
after every turn without eating into anyone's allowance.
"""

from __future__ import annotations

import time

from fastapi import HTTPException

from backend.config import get_settings
from backend.sessions import SessionState

WINDOW_S = 60.0


def enforce(state: SessionState, *, text: str | None = None, cost: int = 1) -> None:
    """Raise if this request would breach a limit; otherwise record it."""
    settings = get_settings()

    if text is not None and len(text) > settings.max_message_chars:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Message is {len(text)} characters; the limit is "
                f"{settings.max_message_chars}. Try sending it in smaller pieces."
            ),
        )

    now = time.time()
    cutoff = now - WINDOW_S
    state.recent_requests = [t for t in state.recent_requests if t > cutoff]

    if len(state.recent_requests) + cost > settings.rate_limit_per_min:
        oldest = min(state.recent_requests, default=now)
        retry_after = max(1, int(WINDOW_S - (now - oldest)) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Slow down — {settings.rate_limit_per_min} requests per minute per session.",
            headers={"Retry-After": str(retry_after)},
        )

    if state.request_count + cost > settings.max_requests_per_session:
        raise HTTPException(
            status_code=429,
            detail=(
                f"This session has used its {settings.max_requests_per_session}-request budget. "
                "Reload the page to start a new twin."
            ),
        )

    state.recent_requests.extend([now] * cost)
    state.request_count += cost
