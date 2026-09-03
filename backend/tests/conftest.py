"""Shared fixtures. The suite runs entirely offline: no Gemini key, no Neo4j,
no Qdrant server — the in-process backends stand in for all three."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import sessions
from backend.main import app


@pytest.fixture
def client() -> TestClient:
    sessions.clear_all()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session_id(client: TestClient) -> str:
    return client.post("/api/session").json()["session_id"]


def ingest(client: TestClient, session_id: str, text: str, source: str = "fact") -> dict:
    res = client.post(
        "/api/ingest", json={"session_id": session_id, "text": text, "source": source}
    )
    res.raise_for_status()
    return res.json()


def say(client: TestClient, session_id: str, message: str) -> tuple[str, dict]:
    """Drive one chat turn and return (reply text, meta payload)."""
    import json

    reply, meta = "", {}
    with client.stream(
        "POST", "/api/chat", json={"session_id": session_id, "message": message}
    ) as res:
        assert res.status_code == 200
        event = ""
        for line in res.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:])
                if event == "token":
                    reply += payload["text"]
                elif event == "meta":
                    meta = payload
    return reply, meta
