"""End-to-end smoke test of a real run through a deployed stack (used by CI against Docker).

    python backend/scripts/smoke_run.py http://localhost:8080

Registers a throwaway account, creates a project for https://demo.playwright.dev, approves a
four-step TodoMVC plan, runs it and waits for the isolated browser worker to finish. Exits
non-zero unless the run passed and produced screenshots and a trace. Standard library only.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/") + "/api/v1"
TOKEN = ""


def call(method: str, path: str, body: Any = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)  # noqa: S310
    request.add_header("Content-Type", "application/json")
    if TOKEN:
        request.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        # The API's error envelope (code, message, request_id) says what went wrong.
        detail = exc.read().decode("utf-8", "replace")[:2000]
        sys.exit(f"{method} {path} -> HTTP {exc.code}: {detail}")


def main() -> None:
    global TOKEN
    email = f"smoke-{secrets.token_hex(4)}@example.com"
    TOKEN = call(
        "POST",
        "/auth/register",
        {"email": email, "display_name": "Smoke", "password": secrets.token_urlsafe(18)},
    )["access_token"]
    project = call(
        "POST", "/projects", {"name": "Smoke", "base_url": "https://demo.playwright.dev"}
    )
    suite = call("GET", f"/projects/{project['id']}/suites")[0]
    case = call(
        "POST",
        f"/projects/{project['id']}/cases",
        {"suite_id": suite["id"], "name": "Add a todo"},
    )
    todo = {"strategy": "placeholder", "value": "What needs to be done?"}
    plan = {
        "name": "Add a todo",
        "steps": [
            {"action": "goto", "description": "Open TodoMVC", "value": "/todomvc/"},
            {"action": "fill", "description": "Type", "locator": todo, "value": "Buy milk"},
            {"action": "press", "description": "Submit", "value": "Enter"},
            {
                "action": "expect_text",
                "description": "Listed",
                "locator": {"strategy": "test_id", "value": "todo-title"},
                "value": "Buy milk",
            },
        ],
    }
    draft = call("POST", f"/cases/{case['id']}/plans", {"plan": plan})
    version = call("POST", f"/plans/{draft['latest_plan']['id']}/approve")
    runtime = call("GET", "/execution-runtime")
    print("runtime:", json.dumps(runtime))
    run = call("POST", f"/versions/{version['id']}/run", {"trace": True})
    deadline = time.monotonic() + 180
    while run["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(2)
        run = call("GET", f"/executions/{run['id']}")
    events = call("GET", f"/executions/{run['id']}/events")
    for event in events:
        print(f"{event['seq']:>3} {event['type']:<28} {event['message']}")
    kinds = sorted({a["kind"] for a in run["artifacts"]})
    print("status:", run["status"], "isolated:", run["isolated"], "artifacts:", kinds)
    ok = (
        run["status"] == "passed"
        and run["isolated"] is True
        and "screenshot" in kinds
        and "trace" in kinds
    )
    if not ok:
        print("error:", run.get("error_message"))
        sys.exit(1)
    shot = next(a for a in run["artifacts"] if a["kind"] == "screenshot")
    request = urllib.request.Request(f"{BASE}/artifacts/{shot['id']}/content")  # noqa: S310
    request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        assert response.read(3) == b"\xff\xd8\xff", "screenshot is not a JPEG"
    print("smoke run passed")


if __name__ == "__main__":
    main()
