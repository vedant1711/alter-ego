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


class IngestOut(BaseModel):
    memory_id: str
    entities_added: int = 0
    relationships_added: int = 0


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


class RetrievedMemory(BaseModel):
    text: str
    # A memory can surface from more than one retrieval leg, so this lists all
    # of them: any of "graph", "vector", "keyword".
    source: list[str]
    score: float
    source_type: str
