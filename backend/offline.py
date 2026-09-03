"""Deterministic stand-ins for Gemini, used when GEMINI_API_KEY is unset.

Offline mode exists so the app is runnable and testable end to end before any
external service is provisioned. It is *not* a fallback for production: the
replies are templated, not generated. `/api/health` reports `offline: true` and
the UI shows a banner so nobody mistakes it for the real thing.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator

# Words that are capitalised but carry no entity meaning.
_STOPWORDS = {
    "i", "a", "an", "and", "the", "my", "me", "we", "you", "it", "is", "am",
    "are", "was", "were", "be", "been", "of", "to", "in", "on", "at", "for",
    "with", "as", "by", "from", "that", "this", "but", "so", "if", "then",
    "there", "here", "when", "what", "how", "why", "who", "no", "not", "do",
    "does", "did", "have", "has", "had", "will", "would", "can", "could",
}


def hashed_embedding(text: str, dim: int) -> list[float]:
    """A deterministic bag-of-words hash embedding, L2-normalised.

    Not semantic, but two texts sharing vocabulary land near each other under
    cosine distance, which is enough to exercise the vector leg of retrieval.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        # Empty text still needs a valid unit vector.
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


def offline_completion(prompt: str) -> str:
    """Route a prompt to the right templated response by looking at its shape."""
    if "STRICT JSON" in prompt or "knowledge graph" in prompt:
        return _offline_extraction(prompt)
    if "Summarize the following memories" in prompt:
        return _offline_summary(prompt)
    return _offline_reply(prompt)


async def offline_stream(prompt: str) -> AsyncIterator[str]:
    """Yield the templated reply word by word so the UI's streaming path runs."""
    text = offline_completion(prompt)
    for word in text.split(" "):
        yield word + " "


def _extract_block(prompt: str, marker: str) -> str:
    """Pull the text that follows `marker` up to the next all-caps section head."""
    idx = prompt.find(marker)
    if idx == -1:
        return ""
    tail = prompt[idx + len(marker) :]
    stop = re.search(r"\n[A-Z][A-Z ']{6,}", tail)
    return (tail[: stop.start()] if stop else tail).strip()


def _offline_extraction(prompt: str) -> str:
    """Heuristic entity/relationship extraction: enough to grow a visible graph."""
    import json

    text = _extract_block(prompt, 'Text: """').split('"""')[0].strip() or prompt
    nodes: list[dict[str, str]] = [{"name": "User", "type": "Person"}]
    rels: list[dict[str, str]] = []
    seen = {"user"}

    patterns = [
        (r"\bwork(?:s|ed)?\s+(?:at|for)\s+([A-Z][\w&.\- ]{1,40})", "Organization", "WORKS_AT"),
        (r"\bliv(?:e|es|ed)\s+in\s+([A-Z][\w.\- ]{1,40})", "Place", "LIVES_IN"),
        (r"\b(?:based|located)\s+in\s+([A-Z][\w.\- ]{1,40})", "Place", "LIVES_IN"),
        (r"\b(?:like|love|enjoy|prefer)s?\s+([a-zA-Z][\w\- ]{2,40})", "Preference", "LIKES"),
        (r"\bbuil(?:t|ding)\s+([A-Z][\w.\- ]{1,40})", "Project", "WORKED_ON"),
        (r"\bknow(?:s)?\s+([A-Z][\w.\- ]{1,40})", "Person", "KNOWS"),
    ]
    for pattern, node_type, rel_type in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip().rstrip(".,;:").split(" and ")[0].strip()
            if not name or name.lower() in _STOPWORDS or len(name) < 2:
                continue
            if name.lower() not in seen:
                seen.add(name.lower())
                nodes.append({"name": name, "type": node_type})
            rels.append({"source": "User", "type": rel_type, "target": name})

    # Any remaining proper nouns become Concepts so the graph is not empty.
    for match in re.finditer(r"\b([A-Z][a-zA-Z]{2,})\b", text[1:]):
        name = match.group(1)
        if name.lower() in _STOPWORDS or name.lower() in seen or len(seen) > 12:
            continue
        seen.add(name.lower())
        nodes.append({"name": name, "type": "Concept"})
        rels.append({"source": "User", "type": "MENTIONS", "target": name})

    return json.dumps({"nodes": nodes, "relationships": rels})


def _offline_summary(prompt: str) -> str:
    batch = _extract_block(prompt, 'Memories: """').split('"""')[0].strip()
    lines = [ln.strip("- ").strip() for ln in batch.splitlines() if ln.strip()]
    joined = " ".join(lines)[:400]
    return f"[offline summary] The user previously discussed: {joined}"


def _offline_reply(prompt: str) -> str:
    message = _extract_block(prompt, "New message:").split("\n")[0].strip()
    context = _extract_block(prompt, "GROUND YOUR REPLY in these retrieved memories (do not invent facts):")
    facts = [ln.strip("- ").strip() for ln in context.splitlines() if ln.strip()][:3]
    if facts:
        recalled = " ".join(f"I remember: {f}" for f in facts)
        return (
            f"[offline mode] You asked: \"{message}\". {recalled} "
            "Set GEMINI_API_KEY to get a real, style-matched reply."
        )
    return (
        f"[offline mode] You asked: \"{message}\", but I have no memories to ground a reply in yet. "
        "Add a writing sample or load the example persona, and set GEMINI_API_KEY for real generation."
    )
