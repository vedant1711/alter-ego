"""Request/response models for the public API (PRD section 8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionOut(BaseModel):
    session_id: str


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1)
