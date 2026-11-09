"""Network policy enforced on every request the browser makes.

* Only ``http``/``https`` requests leave the browser (``data:``/``blob:``/``about:`` stay local).
* Top-level navigations must target the project's allowed domains (``example.com`` or
  ``*.example.com``).
* Unless the deployment explicitly allows private targets, no request may reach loopback,
  private, multicast or reserved addresses — checked against every address the host resolves
  to. This blocks SSRF from a test page into the worker's network.
* Link-local addresses and metadata hostnames (cloud instance metadata) are blocked even when
  private targets are allowed.

DNS answers can change between this check and the browser's own lookup (rebinding), so the
container network policy remains the outer boundary; see SECURITY.md.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

_INTERNAL_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")
_INTERNAL_NAMES = {"localhost"}
_METADATA_NAMES = {"metadata", "metadata.google.internal", "instance-data"}
_AWS_IPV6_METADATA = ipaddress.ip_network("fd00:ec2::/32")

AddressClass = Literal["public", "private", "link_local"]


def normalize_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def host_allowed(host: str, allowed_domains: list[str]) -> bool:
    host = normalize_domain(host)
    for pattern in (normalize_domain(d) for d in allowed_domains):
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True
        elif host == pattern:
            return True
    return False


def classify_address(address: str) -> AddressClass:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip in _AWS_IPV6_METADATA:
        return "link_local"
    if ip.is_global and not ip.is_multicast:
        return "public"
    return "private"


def strip_query(url: str) -> str:
    """URL without query string, fragment or credentials (they may carry tokens)."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return url.split("?", 1)[0].split("#", 1)[0].split("@")[-1][:200]
    if parts.scheme in ("http", "https"):
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        return f"{parts.scheme}://{host}{port}{parts.path}"[:500]
    return f"{parts.scheme}:"[:500]


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""


class NetworkPolicy:
    def __init__(self, allowed_domains: list[str], *, allow_private_network: bool) -> None:
        self.allowed_domains = [normalize_domain(d) for d in allowed_domains if d.strip()]
        self.allow_private_network = allow_private_network
        self._resolved: dict[tuple[str, int], AddressClass] = {}

    async def check(self, url: str, *, top_level_navigation: bool) -> Decision:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return Decision(False, "Malformed URL.")
        if parts.scheme in ("data", "blob", "about"):
            return Decision(True)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return Decision(False, f"Scheme '{parts.scheme}' is not allowed.")
        host = normalize_domain(parts.hostname)
        if top_level_navigation and not host_allowed(host, self.allowed_domains):
            return Decision(False, f"'{host}' is not in the project's allowed domains.")
        if host in _METADATA_NAMES:
            return Decision(False, f"Metadata host '{host}' is always blocked.")
        if not self.allow_private_network and (
            host in _INTERNAL_NAMES or host.endswith(_INTERNAL_SUFFIXES)
        ):
            return Decision(False, f"Internal host '{host}' is blocked.")
        port = port or (443 if parts.scheme == "https" else 80)
        kind = await self._classify(host, port)
        if kind == "link_local":
            return Decision(False, f"'{host}' resolves to a link-local (metadata) address.")
        if kind == "private" and not self.allow_private_network:
            return Decision(False, f"'{host}' resolves to a private or reserved address.")
        return Decision(True)

    async def _classify(self, host: str, port: int) -> AddressClass:
        key = (host, port)
        cached = self._resolved.get(key)
        if cached is not None:
            return cached
        try:
            ipaddress.ip_address(host.strip("[]"))
            addresses = {host.strip("[]")}
        except ValueError:
            try:
                infos = await asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
            except (socket.gaierror, UnicodeError):
                # Unresolvable hosts fail in the browser anyway; let it report the real error.
                self._resolved[key] = "public"
                return "public"
            addresses = {str(info[4][0]) for info in infos}
        kinds = {classify_address(a) for a in addresses} or {"private"}
        kind: AddressClass = (
            "link_local" if "link_local" in kinds else "private" if "private" in kinds else "public"
        )
        self._resolved[key] = kind
        return kind
