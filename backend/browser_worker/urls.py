"""Joining a `goto` path with the environment's base URL (shared by the engine and code renderer).

A path is relative to the base URL, so ``/login`` on ``https://shop.test/app`` opens
``https://shop.test/app/login``. When the path already repeats the base URL's own path (common in
AI-written plans: base ``https://site.test/quiz/42``, path ``/quiz/42``), the repeated prefix is
not added twice. Percent-encoded and decoded spellings of the same path count as equal.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit


def path_after_base(base_url: str, path: str) -> str:
    """The part of ``path`` to append to ``base_url`` ("" when it names the base URL itself)."""
    base_path = urlsplit(base_url).path.rstrip("/")
    if not base_path or not path.startswith("/"):
        return path
    for base, candidate in ((base_path, path), (unquote(base_path), unquote(path))):
        if candidate == base or candidate.startswith((base + "/", base + "?", base + "#")):
            return candidate[len(base) :]
    return path


def resolve_url(base_url: str, value: str) -> str:
    """The address a `goto` step opens: full URLs as given, paths joined with the base URL."""
    if not value.startswith("/"):
        return value
    return base_url.rstrip("/") + path_after_base(base_url, value)
