"""JSON-schema preparation and parsing/validation of structured model output."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema with ``$ref``s inlined (providers differ in ``$defs`` support)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.removeprefix("#/$defs/")])
                return resolve(target)
            return {key: resolve(value) for key, value in node.items() if key != "title"}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


class StructuredOutputError(ValueError):
    pass


def parse_structured[T: BaseModel](text: str, model: type[T]) -> T:
    """Parse model output as JSON (tolerating markdown fences) and validate it."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise StructuredOutputError("The response is not JSON.") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"The response is not valid JSON: {exc.msg}.") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'root'}: {err['msg']}"
            for err in exc.errors()
        )
        raise StructuredOutputError(f"The JSON does not match the schema ({problems}).") from exc
