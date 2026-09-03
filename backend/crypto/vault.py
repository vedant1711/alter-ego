"""Encryption at rest for memory text (PRD section 6.4).

Every memory's raw text is Fernet-encrypted before it leaves the process and
decrypted only server-side, when assembling LLM context or the retrieved-
memories panel. The stored payload is ciphertext.

Keys are per-session, derived from the master key with HKDF using the session
id as salt (the section 6.4 stretch goal). One session's key cannot decrypt
another's, so a filter bug in the store cannot leak readable text.

Graph entity labels are deliberately left in plaintext — they drive the
visualisation and are low-sensitivity. That tradeoff is documented in the
README.
"""

from __future__ import annotations

import base64
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.config import get_settings

log = logging.getLogger(__name__)

_INFO = b"alter-ego/session-key/v1"
# Marks text this process could not decrypt (usually: written under a previous
# ephemeral key). Callers drop these rather than feeding them to the model.
UNREADABLE = ""


class Vault:
    def __init__(self, master_key: str, *, persistent: bool) -> None:
        self._master = self._coerce(master_key)
        self.persistent = persistent
        self._cache: dict[str, Fernet] = {}

    @staticmethod
    def _coerce(master_key: str) -> bytes:
        """Accept a Fernet key (urlsafe base64) and return its 32 raw bytes."""
        raw = base64.urlsafe_b64decode(master_key.encode("utf-8"))
        if len(raw) != 32:
            raise ValueError("FERNET_KEY must decode to 32 bytes")
        return raw

    def _cipher(self, session_id: str) -> Fernet:
        cipher = self._cache.get(session_id)
        if cipher is None:
            derived = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=session_id.encode("utf-8"),
                info=_INFO,
            ).derive(self._master)
            cipher = Fernet(base64.urlsafe_b64encode(derived))
            self._cache[session_id] = cipher
        return cipher

    def encrypt(self, session_id: str, text: str) -> str:
        return self._cipher(session_id).encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, session_id: str, token: str) -> str:
        if not token:
            return UNREADABLE
        try:
            return self._cipher(session_id).decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            log.warning("undecryptable memory in session %s — skipping", session_id)
            return UNREADABLE


@lru_cache(maxsize=1)
def get_vault() -> Vault:
    settings = get_settings()
    key = settings.fernet_key.strip()
    if key:
        return Vault(key, persistent=True)

    # No key configured: still encrypt, but with a key that dies with the
    # process. Fine against in-process stores, a footgun against a real Qdrant.
    level = log.error if settings.qdrant_enabled else log.warning
    level(
        "FERNET_KEY is unset — using an ephemeral key. Memories written now "
        "will be unreadable after a restart. Generate one with: "
        'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
    )
    return Vault(Fernet.generate_key().decode("ascii"), persistent=False)
