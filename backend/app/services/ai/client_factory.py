"""Builds a provider adapter for a stored connection (decrypting its key only at call time)."""

from __future__ import annotations

from app.core.config import Settings
from app.core.crypto import DecryptionError, EncryptedSecret, SecretCipher
from app.infrastructure.database.models import AIProviderConnection
from app.services.ai.base import AIProvider
from app.services.ai.exceptions import CredentialMissingError, CredentialUnreadableError
from app.services.ai.registry import ProviderRegistry


def credential_aad(connection_id: object) -> str:
    """Associated data binding a ciphertext to its connection row."""
    return f"ai_provider:{connection_id}"


class ProviderClientFactory:
    def __init__(
        self, settings: Settings, registry: ProviderRegistry, cipher: SecretCipher
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._cipher = cipher

    def api_key_for(self, connection: AIProviderConnection) -> str | None:
        credential = connection.credential
        if credential is None:
            if self._registry.get(connection.provider_type).requires_api_key:
                raise CredentialMissingError()
            return None
        try:
            return self._cipher.decrypt(
                EncryptedSecret(credential.ciphertext, credential.nonce, credential.key_id),
                associated_data=credential_aad(connection.id),
            )
        except DecryptionError as exc:
            raise CredentialUnreadableError() from exc

    def build(self, connection: AIProviderConnection) -> AIProvider:
        return self._registry.create(
            connection.provider_type,
            api_key=self.api_key_for(connection),
            base_url=connection.base_url,
            config=dict(connection.config or {}),
            timeout_seconds=self._settings.ai_request_timeout_seconds,
        )
