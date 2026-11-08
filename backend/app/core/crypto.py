"""Authenticated encryption for stored secrets (AI provider keys).

AES-256-GCM with versioned keys. Each ciphertext records the key ID that produced it, so keys can
be rotated: add a new key at the front of ENCRYPTION_KEYS, keep old keys for decryption, then
re-encrypt (or let credentials be re-entered) and finally remove the old key.

Associated data binds a ciphertext to its owning row so it cannot be swapped between records.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

logger = logging.getLogger(__name__)

_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
NONCE_BYTES = 12


class CryptoConfigError(ValueError):
    """ENCRYPTION_KEYS is missing or malformed."""


class DecryptionError(Exception):
    """Ciphertext could not be authenticated (wrong key, tampering or wrong row)."""


@dataclass(frozen=True, slots=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    key_id: str


def generate_key_entry(key_id: str = "v1") -> str:
    return f"{key_id}:{base64.urlsafe_b64encode(os.urandom(32)).decode()}"


def parse_keys(raw: str) -> list[tuple[str, bytes]]:
    keys: list[tuple[str, bytes]] = []
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        key_id, sep, encoded = entry.partition(":")
        if not sep or not _KEY_ID.match(key_id):
            raise CryptoConfigError("Each ENCRYPTION_KEYS entry must look like 'v1:<base64url>'.")
        try:
            key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except ValueError as exc:
            raise CryptoConfigError(f"Key '{key_id}' is not valid base64url.") from exc
        if len(key) != 32:
            raise CryptoConfigError(f"Key '{key_id}' must decode to 32 bytes (AES-256).")
        if any(existing == key_id for existing, _ in keys):
            raise CryptoConfigError(f"Duplicate key id '{key_id}'.")
        keys.append((key_id, key))
    if not keys:
        raise CryptoConfigError("ENCRYPTION_KEYS contains no keys.")
    return keys


class SecretCipher:
    def __init__(self, keys: list[tuple[str, bytes]]) -> None:
        if not keys:
            raise CryptoConfigError("At least one encryption key is required.")
        self._active_id = keys[0][0]
        self._keys = {key_id: AESGCM(key) for key_id, key in keys}

    @property
    def active_key_id(self) -> str:
        return self._active_id

    def encrypt(self, plaintext: str, *, associated_data: str) -> EncryptedSecret:
        nonce = secrets.token_bytes(NONCE_BYTES)
        ciphertext = self._keys[self._active_id].encrypt(
            nonce, plaintext.encode("utf-8"), associated_data.encode("utf-8")
        )
        return EncryptedSecret(ciphertext=ciphertext, nonce=nonce, key_id=self._active_id)

    def decrypt(self, secret: EncryptedSecret, *, associated_data: str) -> str:
        aead = self._keys.get(secret.key_id)
        if aead is None:
            raise DecryptionError(f"Encryption key '{secret.key_id}' is not configured.")
        try:
            plaintext = aead.decrypt(
                secret.nonce, secret.ciphertext, associated_data.encode("utf-8")
            )
        except InvalidTag as exc:
            raise DecryptionError("Stored secret failed authentication.") from exc
        return plaintext.decode("utf-8")


def build_cipher(settings: Settings) -> SecretCipher:
    if settings.encryption_keys:
        return SecretCipher(parse_keys(settings.encryption_keys.get_secret_value()))
    if settings.is_production:  # also enforced by Settings validation
        raise CryptoConfigError("ENCRYPTION_KEYS is required in production.")

    # Development/test: a generated key persisted locally so stored credentials survive restarts.
    path = Path(settings.dev_encryption_key_file).expanduser().resolve()
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = generate_key_entry("dev1")
        path.write_text(raw + "\n", encoding="utf-8")
        logger.warning("ENCRYPTION_KEYS not set; generated a development key file at %s", path)
    return SecretCipher(parse_keys(raw))
