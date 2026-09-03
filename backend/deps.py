"""External service clients: Gemini (LLM + embeddings), Neo4j, Qdrant.

Every client is built lazily and cached, so importing the app never reaches the
network. Anything unconfigured degrades to an in-process equivalent rather than
crashing — see `offline.py` and the `*_store` modules.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from functools import lru_cache

from backend import offline
from backend.config import Settings, get_settings

log = logging.getLogger(__name__)

# Gemini's free tier is a low requests-per-minute budget shared by every visitor
# of this public demo, so generation calls are serialised process-wide.
_LLM_GATE = asyncio.Semaphore(1)

_MAX_ATTEMPTS = 4
_BASE_BACKOFF_S = 1.5


def _is_rate_limited(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 503):
        return True
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


async def _with_backoff(label: str, call):
    """Run `call()` (a coroutine factory) retrying 429/503 with jittered backoff."""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 - provider raises many shapes
            if attempt == _MAX_ATTEMPTS - 1 or not _is_rate_limited(exc):
                raise
            delay = _BASE_BACKOFF_S * (2**attempt) + random.uniform(0, 0.5)
            log.warning("%s rate-limited (attempt %d), retrying in %.1fs", label, attempt + 1, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


class LLM:
    """Gemini Flash wrapper, or a deterministic offline stub when no key is set."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.offline = not settings.gemini_api_key
        self._client = None
        if not self.offline:
            from google import genai

            self._client = genai.Client(api_key=settings.gemini_api_key)

    def _config(self, *, temperature: float, json_mode: bool, system: str | None):
        from google.genai import types

        return types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
            max_output_tokens=1024,
        )

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        system: str | None = None,
    ) -> str:
        if self.offline:
            return offline.offline_completion(prompt)

        async def _call():
            resp = await self._client.aio.models.generate_content(
                model=self._settings.gemini_chat_model,
                contents=prompt,
                config=self._config(temperature=temperature, json_mode=json_mode, system=system),
            )
            return resp.text or ""

        async with _LLM_GATE:
            return await _with_backoff("gemini.complete", _call)

    async def stream(
        self,
        prompt: str,
        *,
        temperature: float = 0.85,
        system: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield reply chunks. Backoff happens before the first chunk only."""
        if self.offline:
            async for chunk in offline.offline_stream(prompt):
                yield chunk
            return

        async def _open():
            return await self._client.aio.models.generate_content_stream(
                model=self._settings.gemini_chat_model,
                contents=prompt,
                config=self._config(temperature=temperature, json_mode=False, system=system),
            )

        async with _LLM_GATE:
            stream = await _with_backoff("gemini.stream", _open)
            async for event in stream:
                if event.text:
                    yield event.text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts to `EMBED_DIM` dimensions (MRL-truncated, then normalised)."""
        if not texts:
            return []
        dim = self._settings.embed_dim
        if self.offline:
            return [offline.hashed_embedding(t, dim) for t in texts]

        from google.genai import types

        async def _call():
            return await self._client.aio.models.embed_content(
                model=self._settings.gemini_embed_model,
                contents=texts,
                config=types.EmbedContentConfig(output_dimensionality=dim),
            )

        resp = await _with_backoff("gemini.embed", _call)
        return [_normalise(list(e.values or [])) for e in (resp.embeddings or [])]


def _normalise(vec: list[float]) -> list[float]:
    """MRL-truncated Gemini embeddings are no longer unit length; cosine wants them to be."""
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    return LLM(get_settings())
