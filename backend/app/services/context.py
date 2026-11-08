from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Client metadata passed from the API layer to services (no framework types)."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
