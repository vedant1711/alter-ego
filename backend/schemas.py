"""Request/response models for the public API (PRD section 8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    session_id: str


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class IngestIn(BaseModel):
    session_id: str
    text: str = Field(min_length=1)
    source: Literal["sample", "fact"]


class Warning(BaseModel):
    """A degradation the user should know about, but which did not fail the request.

    `code` is for the UI to key off; `message` and `action` are shown verbatim,
    so they are written for the person reading them, not for a log.
    """

    code: str
    message: str
    action: str | None = None


class IngestOut(BaseModel):
    memory_id: str
    entities_added: int = 0
    relationships_added: int = 0
    warnings: list[Warning] = []


class LoadExampleIn(BaseModel):
    session_id: str


class LoadExampleOut(BaseModel):
    name: str
    tagline: str
    memories_added: int
    entities_added: int
    relationships_added: int
    suggested_questions: list[str]
    already_loaded: bool = False
    warnings: list[Warning] = []


class RetrievedMemory(BaseModel):
    text: str
    # A memory can surface from more than one retrieval leg, so this lists all
    # of them: any of "graph", "vector", "keyword".
    source: list[str]
    score: float
    source_type: str
