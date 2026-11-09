"""Validation for user-supplied provider endpoints (custom base URLs are an SSRF vector)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.services.ai.exceptions import UnsafeBaseUrlError

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata"}


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def validate_local_url(url: str) -> str:
    """Endpoints of local model servers (Ollama, LM Studio): http(s) on loopback or the LAN.

    Cloud metadata (link-local addresses and metadata hostnames) stays blocked.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeBaseUrlError("The endpoint URL must start with http:// or https://.")
    if parts.username or parts.password:
        raise UnsafeBaseUrlError("Do not put credentials in the endpoint URL.")
    host = parts.hostname.lower()
    if host in ("metadata", "metadata.google.internal"):
        raise UnsafeBaseUrlError("Metadata hosts are not allowed.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, parts.port or (443 if parts.scheme == "https" else 80)
        )
    except socket.gaierror as exc:
        raise UnsafeBaseUrlError(f"The host '{host}' could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        if ip.is_link_local or ip in ipaddress.ip_network("fd00:ec2::/32"):
            raise UnsafeBaseUrlError("Link-local (cloud metadata) addresses are not allowed.")
    return url.strip().rstrip("/")


async def validate_public_https_url(url: str) -> str:
    """Require https, a hostname that resolves only to public addresses, and no credentials."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafeBaseUrlError("The endpoint URL must start with https://.")
    if parts.username or parts.password:
        raise UnsafeBaseUrlError("Do not put credentials in the endpoint URL.")
    host = parts.hostname.lower()
    if host in _BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeBaseUrlError("Internal hostnames are not allowed.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or 443)
    except socket.gaierror as exc:
        raise UnsafeBaseUrlError(f"The host '{host}' could not be resolved.") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses or not all(_is_public(address) for address in addresses):
        raise UnsafeBaseUrlError("The endpoint resolves to a private or reserved address.")
    return url.strip().rstrip("/")
