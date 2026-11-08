"""Helpers shared by provider adapters."""

from __future__ import annotations

import json
from typing import Any

from app.services.ai.base import JSON_ONLY_INSTRUCTION
from app.services.ai.types import GenerateRequest


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds form only)."""
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def prompt_with_schema(request: GenerateRequest) -> str:
    """Prompt text, with the JSON-only instruction when native structured output is not used."""
    if request.json_schema is not None and not request.native_structured_output:
        schema = json.dumps(request.json_schema, separators=(",", ":"))
        return f"{request.prompt}\n\n{JSON_ONLY_INSTRUCTION}{schema}"
    return request.prompt


def short(text: Any, limit: int = 300) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"
