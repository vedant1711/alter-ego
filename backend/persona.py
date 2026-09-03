"""The bundled example persona (FR9).

Ships pre-written so a visitor with no context can click one button, get a
working twin, and understand the project before deciding whether to build their
own. It is loaded in bulk — one batched embedding call and one extraction call
over all the facts at once — because ingesting fourteen items one at a time
would take a minute against the free tier's requests-per-minute ceiling.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).parent / "data" / "example_persona.json"


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(_PATH.read_text(encoding="utf-8"))


def texts() -> list[tuple[str, str]]:
    """(text, source_type) pairs, in the order they should be stored."""
    persona = load()
    return [(s, "sample") for s in persona["samples"]] + [
        (f, "fact") for f in persona["facts"]
    ]
