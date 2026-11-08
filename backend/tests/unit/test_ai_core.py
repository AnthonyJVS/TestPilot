"""Credential encryption, URL policy, structured output parsing and capability merging."""

from __future__ import annotations

import base64
import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.crypto import (
    CryptoConfigError,
    DecryptionError,
    SecretCipher,
    build_cipher,
    generate_key_entry,
    parse_keys,
)
from app.services.ai import capabilities as caps
from app.services.ai.exceptions import UnsafeBaseUrlError
from app.services.ai.structured import StructuredOutputError, parse_structured, schema_for
from app.services.ai.types import Capability, CapabilitySource, CapabilityStatus, CapabilityValue
from app.services.ai.url_policy import validate_public_https_url
from tests.conftest import make_settings

# ------------------------------------------------------------------------- crypto


def test_encrypt_decrypt_roundtrip_with_associated_data() -> None:
    cipher = SecretCipher(parse_keys(generate_key_entry("v1")))
    secret = cipher.encrypt("sk-live-123", associated_data="ai_provider:A")
    assert b"sk-live-123" not in secret.ciphertext
    assert cipher.decrypt(secret, associated_data="ai_provider:A") == "sk-live-123"
    with pytest.raises(DecryptionError):  # ciphertext moved to another row
        cipher.decrypt(secret, associated_data="ai_provider:B")


def test_key_rotation_keeps_old_ciphertexts_readable() -> None:
    old = generate_key_entry("v1")
    secret = SecretCipher(parse_keys(old)).encrypt("key", associated_data="x")
    rotated = SecretCipher(parse_keys(f"{generate_key_entry('v2')},{old}"))
    assert rotated.active_key_id == "v2"
    assert rotated.decrypt(secret, associated_data="x") == "key"
    assert rotated.encrypt("new", associated_data="x").key_id == "v2"
    with pytest.raises(DecryptionError):  # old key removed too early
        SecretCipher(parse_keys(generate_key_entry("v2"))).decrypt(secret, associated_data="x")


@pytest.mark.parametrize(
    "raw",
    ["", "nocolon", "v1:" + base64.urlsafe_b64encode(b"short").decode(), "bad id!:" + "A" * 43],
)
def test_malformed_keys_are_rejected(raw: str) -> None:
    with pytest.raises(CryptoConfigError):
        parse_keys(raw)


def test_development_key_file_is_created_once(tmp_path: Path) -> None:
    key_file = tmp_path / "keys"
    settings = make_settings(
        "sqlite+aiosqlite:///:memory:", encryption_keys=None, dev_encryption_key_file=str(key_file)
    )
    first = build_cipher(settings).encrypt("value", associated_data="a")
    assert key_file.exists()
    assert build_cipher(settings).decrypt(first, associated_data="a") == "value"


# --------------------------------------------------------------------- URL policy


def _fake_resolver(address: str) -> Any:
    async def resolve(host: str, port: int, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://localhost/v1",
        "https://user:pass@api.example.com",
        "https://metadata.google.internal/",
        "ftp://api.example.com",
    ],
)
async def test_unsafe_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeBaseUrlError):
        await validate_public_https_url(url)


@pytest.mark.parametrize(
    "address", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "::1"]
)
async def test_hosts_resolving_to_private_addresses_are_rejected(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_resolver(address))
    with pytest.raises(UnsafeBaseUrlError):
        await validate_public_https_url("https://proxy.example.com/v1")


async def test_public_https_url_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", _fake_resolver("93.184.215.14"))
    assert (
        await validate_public_https_url("https://proxy.example.com/v1/")
        == "https://proxy.example.com/v1"
    )


# -------------------------------------------------------------- structured output


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Step]


def test_schema_inlines_references() -> None:
    schema = schema_for(Plan)
    assert "$defs" not in schema
    assert schema["properties"]["steps"]["items"]["properties"]["action"]["type"] == "string"
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "text",
    [
        '{"steps": [{"action": "click"}]}',
        '```json\n{"steps": [{"action": "click"}]}\n```',
        'Here you go: {"steps": [{"action": "click"}]} hope it helps',
    ],
)
def test_parse_tolerates_fences_and_chatter(text: str) -> None:
    assert parse_structured(text, Plan).steps[0].action == "click"


@pytest.mark.parametrize("text", ["no json here", '{"steps": "nope"}', '{"steps": [], "extra": 1}'])
def test_parse_rejects_invalid_output(text: str) -> None:
    with pytest.raises(StructuredOutputError):
        parse_structured(text, Plan)


# --------------------------------------------------------------------- capabilities


def test_metadata_never_overrides_probe_evidence() -> None:
    stored = caps.with_probe(None, Capability.VISION, CapabilityStatus.SUPPORTED)
    reported = {
        Capability.VISION: CapabilityValue(
            CapabilityStatus.UNSUPPORTED, CapabilitySource.PROVIDER_METADATA
        ),
        Capability.TEXT: CapabilityValue(
            CapabilityStatus.SUPPORTED, CapabilitySource.PROVIDER_METADATA
        ),
    }
    merged = caps.load(caps.merge_metadata(stored, reported))
    assert merged[Capability.VISION] == CapabilityValue(
        CapabilityStatus.SUPPORTED, CapabilitySource.PROBE
    )
    assert merged[Capability.TEXT].status == CapabilityStatus.SUPPORTED
    assert merged[Capability.TOOL_CALLING].status == CapabilityStatus.UNKNOWN
