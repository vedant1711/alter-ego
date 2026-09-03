"""Few-shot styled generation: the twin's reply, in the user's voice."""

from __future__ import annotations

from backend import prompts
from backend.memory.vector_store import get_vector_store
from backend.schemas import RetrievedMemory
from backend.sessions import SessionState

# Section 10.3 calls for 2-4 samples. More would dominate the prompt and start
# leaking the samples' *content* into replies rather than just their tone.
MAX_SAMPLES = 4
MAX_SAMPLE_CHARS = 600


async def fetch_style_samples(session_id: str) -> list[str]:
    """The user's own writing, longest first — long samples carry more voice."""
    records = await get_vector_store().list_session(
        session_id, source_types=["sample"], include_summarized=True
    )
    samples = sorted((r.text.strip() for r in records if r.text.strip()), key=len, reverse=True)
    return [s[:MAX_SAMPLE_CHARS] for s in samples[:MAX_SAMPLES]]


def build_prompt(
    message: str,
    memories: list[RetrievedMemory],
    samples: list[str],
    state: SessionState | None = None,
) -> str:
    return prompts.render(
        "style_transfer",
        writing_samples=_bullets(samples, '(no samples yet — write plainly and briefly)'),
        retrieved_context=_bullets(
            [m.text for m in memories], "(nothing remembered about this yet)"
        ),
        conversation=_conversation(state),
        message=message.strip(),
    )


def _bullets(items: list[str], empty: str) -> str:
    return "\n".join(f"- {item}" for item in items) if items else empty


def _conversation(state: SessionState | None) -> str:
    if state is None or not state.recent_turns:
        return "(this is the first message)"
    lines = []
    for user_text, twin_text in state.recent_turns:
        lines.append(f"Them: {user_text}")
        lines.append(f"You: {twin_text}")
    return "\n".join(lines)
