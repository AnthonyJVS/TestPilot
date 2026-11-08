"""Write the OpenAPI schema to backend/openapi.json (used to generate frontend types).

Usage: python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.core.crypto import generate_key_entry  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="development",
        enable_api_docs=True,
        jwt_secret="schema-export-only-" + "x" * 32,
        encryption_keys=generate_key_entry("export"),  # throwaway; nothing is encrypted
    )
    schema = create_app(settings).openapi()
    target = BACKEND_DIR / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {target.relative_to(BACKEND_DIR.parent)}")


if __name__ == "__main__":
    main()
