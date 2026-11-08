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
from app.main import create_app  # noqa: E402


def main() -> None:
    settings = Settings(_env_file=None, app_env="development", enable_api_docs=True)  # type: ignore[call-arg]
    schema = create_app(settings).openapi()
    target = BACKEND_DIR / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {target.relative_to(BACKEND_DIR.parent)}")


if __name__ == "__main__":
    main()
