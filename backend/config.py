"""Application settings, loaded from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    # Gemini 3.x thinking level: MINIMAL, LOW, MEDIUM or HIGH. Thinking tokens
    # count against max_output_tokens and dominate latency, and neither
    # extraction nor voice-matching benefits from deep reasoning. Set empty to
    # omit the field entirely, which older models (2.5) require.
    gemini_thinking_level: str = "LOW"
    max_output_tokens: int = 2048

    # --- Knowledge graph ---
    neo4j_uri: str = ""
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""

    # --- Vector store ---
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "memories"

    # --- Crypto ---
    fernet_key: str = ""

    # --- CORS ---
    frontend_origin: str = "http://localhost:5173"

    # --- Guardrails ---
    rate_limit_per_min: int = 8
    max_message_chars: int = 2000
    max_requests_per_session: int = 60

    # --- Retrieval / summarization ---
    summary_threshold: int = 12
    summary_batch: int = 8
    retrieval_top_k: int = 6
    max_context_chars: int = 6000

    @property
    def cors_origins(self) -> list[str]:
        """FRONTEND_ORIGIN is a comma-separated list; '*' allows everything."""
        raw = [o.strip() for o in self.frontend_origin.split(",") if o.strip()]
        return raw or ["*"]

    @property
    def neo4j_enabled(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_password)

    @property
    def qdrant_enabled(self) -> bool:
        return bool(self.qdrant_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
