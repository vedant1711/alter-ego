"""Text → entities and relationships for the knowledge graph.

The PRD offers two routes (section 10.1): LangChain's `LLMGraphTransformer`, or
a direct strict-JSON prompt. This takes the second. It is one LLM call instead
of a chain, it keeps `session_id` injection in our hands, and it avoids pulling
langchain-experimental onto a 512MB Render Free instance.
"""

from __future__ import annotations

import json
import logging
import re

from backend import prompts
from backend.deps import get_llm

log = logging.getLogger(__name__)

# Section 6.1. Anything the model invents outside this set is coerced to Concept.
ALLOWED_NODE_TYPES = {
    "Person",
    "Place",
    "Organization",
    "Project",
    "Preference",
    "Event",
    "Object",
    "Concept",
}

MAX_NODES = 16
MAX_RELATIONSHIPS = 24
_REL_RE = re.compile(r"[^A-Z0-9_]")


class Entity:
    __slots__ = ("name", "type")

    def __init__(self, name: str, type: str) -> None:
        self.name = name
        self.type = type

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Entity({self.name!r}, {self.type!r})"

    @property
    def key(self) -> str:
        return self.name.strip().lower()


class Relationship:
    __slots__ = ("source", "type", "target")

    def __init__(self, source: str, type: str, target: str) -> None:
        self.source = source
        self.type = type
        self.target = target

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Relationship({self.source!r}, {self.type!r}, {self.target!r})"


async def extract(text: str) -> tuple[list[Entity], list[Relationship]]:
    """Run extraction and return validated entities/relationships (never raises)."""
    prompt = prompts.render("extraction", input=text.replace('"""', "'''"))
    try:
        raw = await get_llm().complete(prompt, temperature=0.0, json_mode=True)
    except Exception:  # noqa: BLE001 - extraction is best-effort; ingestion must still succeed
        log.exception("graph extraction call failed")
        return [], []
    return parse(raw)


def parse(raw: str) -> tuple[list[Entity], list[Relationship]]:
    """Parse and sanitise the model's JSON. Tolerates fenced or padded output."""
    data = _loads(raw)
    if not isinstance(data, dict):
        return [], []

    entities: dict[str, Entity] = {}
    for item in _as_list(data.get("nodes"))[:MAX_NODES]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:60]
        if not name:
            continue
        node_type = str(item.get("type", "")).strip().title()
        if node_type not in ALLOWED_NODE_TYPES:
            node_type = "Concept"
        entities.setdefault(name.lower(), Entity(name, node_type))

    relationships: list[Relationship] = []
    seen: set[tuple[str, str, str]] = set()
    for item in _as_list(data.get("relationships"))[:MAX_RELATIONSHIPS]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip().lower()
        target = str(item.get("target", "")).strip().lower()
        rel_type = _normalise_type(str(item.get("type", "")))
        # Drop dangling edges: both endpoints must be real extracted nodes.
        if not rel_type or source not in entities or target not in entities or source == target:
            continue
        triple = (source, rel_type, target)
        if triple in seen:
            continue
        seen.add(triple)
        relationships.append(Relationship(source, rel_type, target))

    return list(entities.values()), relationships


def _normalise_type(value: str) -> str:
    """Coerce to a safe SCREAMING_SNAKE_CASE token.

    Relationship types cannot be Cypher parameters, so they get interpolated
    into the query string — this is the sanitiser that makes that safe.
    """
    token = _REL_RE.sub("_", value.strip().upper().replace(" ", "_")).strip("_")
    token = re.sub(r"_{2,}", "_", token)
    return token[:40]


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _loads(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text).removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab the outermost JSON object from a chatty response.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            log.warning("extraction returned unparseable output: %.120s", text)
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            log.warning("extraction returned unparseable output: %.120s", text)
            return None
