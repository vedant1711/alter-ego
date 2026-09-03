"""Prompt templates, kept as files so they can be tuned without touching code."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load(name: str) -> str:
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    """Fill a template's {placeholders}.

    Uses str.replace rather than str.format so that braces inside user text or
    inside a JSON example in the template are never treated as fields.
    """
    text = load(name)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
