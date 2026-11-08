"""Reading and merging capability metadata stored on ``ai_model_configurations``."""

from __future__ import annotations

from typing import Any

from app.services.ai.types import (
    Capability,
    CapabilitySource,
    CapabilityStatus,
    CapabilityValue,
)


def load(raw: dict[str, Any] | None) -> dict[Capability, CapabilityValue]:
    result: dict[Capability, CapabilityValue] = {}
    for cap in Capability:
        entry = (raw or {}).get(cap.value) or {}
        try:
            status = CapabilityStatus(entry.get("status", "unknown"))
            source = CapabilitySource(entry.get("source", "none"))
        except ValueError:
            status, source = CapabilityStatus.UNKNOWN, CapabilitySource.NONE
        result[cap] = CapabilityValue(status, source)
    return result


def dump(values: dict[Capability, CapabilityValue]) -> dict[str, Any]:
    return {cap.value: values[cap].to_json() for cap in Capability if cap in values}


def merge_metadata(
    stored: dict[str, Any] | None, reported: dict[Capability, CapabilityValue]
) -> dict[str, Any]:
    """Provider metadata fills unknowns and refreshes metadata values; probe results are kept."""
    current = load(stored)
    for cap, value in reported.items():
        if current[cap].source == CapabilitySource.PROBE:
            continue
        if (
            value.status != CapabilityStatus.UNKNOWN
            or current[cap].status == CapabilityStatus.UNKNOWN
        ):
            current[cap] = value
    return dump(current)


def with_probe(
    stored: dict[str, Any] | None, cap: Capability, status: CapabilityStatus
) -> dict[str, Any]:
    current = load(stored)
    current[cap] = CapabilityValue(status, CapabilitySource.PROBE)
    return dump(current)
