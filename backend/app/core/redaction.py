"""Secret redaction for logs, audit metadata, events and AI payload previews.

Two layers:
* key-based: values under sensitive-looking keys are replaced entirely;
* pattern-based: well-known secret formats inside free text are masked.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|apikey|authorization|cookie|"
    r"session[_-]?id|credential|private[_-]?key|access[_-]?key|client[_-]?secret|signature)",
    re.IGNORECASE,
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Authorization headers / bearer tokens
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    # JSON Web Tokens
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    # Common provider key formats (Anthropic, OpenAI, OpenRouter, xAI, Google, GitHub, AWS)
    re.compile(r"\bsk-(ant-|proj-|or-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
)

_MAX_DEPTH = 12


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return a redacted deep copy of ``value`` (dicts, lists, tuples, strings)."""
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if is_sensitive_key(key_str) and item not in (None, ""):
                result[key_str] = REDACTED
            else:
                result[key_str] = redact(item, _depth=_depth + 1)
        return result
    if isinstance(value, list | tuple):
        return [redact(item, _depth=_depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
