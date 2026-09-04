"""FR7: memory text is encrypted at rest (acceptance criterion 6)."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.crypto.vault import Vault, get_vault
from backend.memory.vector_store import get_vector_store
from backend.tests.conftest import ingest


def test_round_trip() -> None:
    vault = Vault(Fernet.generate_key().decode(), persistent=True)
    token = vault.encrypt("s1", "I work at Acme.")
    assert token != "I work at Acme."
    assert vault.decrypt("s1", token) == "I work at Acme."


def test_per_session_keys_do_not_cross_decrypt() -> None:
    vault = Vault(Fernet.generate_key().decode(), persistent=True)
    token = vault.encrypt("alice", "the passphrase is orange marmalade")
    # Derived per session, so alice's ciphertext is opaque to bob's key.
    assert vault.decrypt("bob", token) == ""


def test_undecryptable_text_is_dropped_not_raised() -> None:
    vault = Vault(Fernet.generate_key().decode(), persistent=True)
    assert vault.decrypt("s1", "not-a-token") == ""
    assert vault.decrypt("s1", "") == ""


def test_master_key_must_be_32_bytes() -> None:
    with pytest.raises(ValueError):
        Vault("c2hvcnQ=", persistent=True)  # b"short"


async def test_stored_payload_is_ciphertext(client: TestClient, session_id: str) -> None:
    secret = "My passphrase is orange marmalade."
    ingest(client, session_id, secret)

    store = get_vector_store()
    points, _ = await store._client.scroll(store._collection, limit=100, with_payload=True)
    payloads = [p.payload for p in points if p.payload["session_id"] == session_id]

    assert payloads
    for payload in payloads:
        assert "text" not in payload
        assert secret not in str(payload)
        assert payload["text_encrypted"].startswith("gAAAAA")

    # ...and it is still readable through the store's own decrypting read path.
    assert secret in [r.text for r in await store.list_session(session_id)]


def test_configured_key_is_persistent() -> None:
    assert get_vault().persistent is True


def test_missing_key_falls_back_to_an_ephemeral_one(monkeypatch) -> None:
    """Without FERNET_KEY the app still encrypts, but only for this process."""
    monkeypatch.setattr(get_settings(), "fernet_key", "")
    get_vault.cache_clear()
    try:
        vault = get_vault()
        assert vault.persistent is False
        assert vault.decrypt("s1", vault.encrypt("s1", "still encrypted")) == "still encrypted"
    finally:
        get_vault.cache_clear()
