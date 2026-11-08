from __future__ import annotations

import httpx

from tests.conftest import CSRF, STRONG_PASSWORD, ClientFactory, bearer, register


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------- register


async def test_register_returns_tokens_and_httponly_refresh_cookie(
    client: httpx.AsyncClient,
) -> None:
    response = await register(client, email="  Ada@Example.COM ")

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "ada@example.com"
    assert "password" not in str(body).lower()

    cookie = response.headers["set-cookie"]
    assert "tp_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie

    me = await client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["display_name"] == "Ada Lovelace"


async def test_register_rejects_duplicate_email(client: httpx.AsyncClient) -> None:
    assert (await register(client)).status_code == 201
    response = await register(client, email="ADA@example.com")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "auth.email_taken"


async def test_register_validation_never_echoes_password(client: httpx.AsyncClient) -> None:
    response = await register(client, password="short-pw")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "request.validation_failed"
    assert "short-pw" not in response.text


async def test_register_rejects_password_equal_to_email(client: httpx.AsyncClient) -> None:
    response = await register(
        client, email="longusername@example.com", password="longusername@example.com"
    )
    assert response.status_code == 422


async def test_registration_can_be_disabled(client_factory: ClientFactory) -> None:
    async with client_factory(allow_registration=False) as client:
        response = await register(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "feature.disabled"


# ------------------------------------------------------------------------------- login


async def test_login_success_and_generic_failure_messages(client: httpx.AsyncClient) -> None:
    await register(client)

    ok = await login(client, "ADA@example.com", STRONG_PASSWORD)
    assert ok.status_code == 200
    assert ok.json()["user"]["last_login_at"] is not None

    wrong_password = await login(client, "ada@example.com", "not-the-password")
    unknown_email = await login(client, "nobody@example.com", "not-the-password")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.json()["error"]["code"] == "auth.invalid_credentials"


async def test_login_is_rate_limited_per_email(client_factory: ClientFactory) -> None:
    async with client_factory(login_max_failures_per_email=3) as client:
        await register(client)
        for _ in range(3):
            assert (await login(client, "ada@example.com", "wrong-password-1")).status_code == 401

        blocked = await login(client, "ada@example.com", STRONG_PASSWORD)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert blocked.json()["error"]["code"] == "rate_limited"


async def test_successful_login_resets_email_failures(client_factory: ClientFactory) -> None:
    async with client_factory(login_max_failures_per_email=3) as client:
        await register(client)
        for _ in range(2):
            await login(client, "ada@example.com", "wrong-password-1")
        assert (await login(client, "ada@example.com", STRONG_PASSWORD)).status_code == 200
        for _ in range(2):
            await login(client, "ada@example.com", "wrong-password-1")
        assert (await login(client, "ada@example.com", STRONG_PASSWORD)).status_code == 200


# ----------------------------------------------------------------------- protected API


async def test_protected_endpoint_requires_valid_token(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "auth.unauthenticated"
    assert missing.json()["error"]["request_id"]

    garbage = await client.get("/api/v1/auth/me", headers=bearer("not-a-jwt"))
    assert garbage.status_code == 401
    assert garbage.json()["error"]["code"] == "auth.token_invalid"


# ----------------------------------------------------------------------------- refresh


async def test_refresh_rotates_token(client: httpx.AsyncClient) -> None:
    await register(client)
    first_cookie = client.cookies.get("tp_refresh", path="/api/v1/auth")

    response = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert response.status_code == 200
    second_cookie = client.cookies.get("tp_refresh", path="/api/v1/auth")
    assert second_cookie and second_cookie != first_cookie

    me = await client.get("/api/v1/auth/me", headers=bearer(response.json()["access_token"]))
    assert me.status_code == 200


async def test_refresh_requires_csrf_header(client: httpx.AsyncClient) -> None:
    await register(client)
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_header_missing"


async def test_refresh_without_cookie_fails(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", headers=CSRF)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.refresh_invalid"


async def test_reused_refresh_token_revokes_the_session(client_factory: ClientFactory) -> None:
    async with client_factory(refresh_reuse_grace_seconds=0) as client:
        registered = await register(client)
        stolen = client.cookies.get("tp_refresh", path="/api/v1/auth")
        access = registered.json()["access_token"]

        assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 200
        legit = client.cookies.get("tp_refresh", path="/api/v1/auth")

        # Attacker replays the old token.
        client.cookies.clear()
        client.cookies.set("tp_refresh", stolen, path="/api/v1/auth")
        replay = await client.post("/api/v1/auth/refresh", headers=CSRF)
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "auth.session_revoked"

        # The legitimate holder is logged out too, and existing access tokens die immediately.
        client.cookies.clear()
        client.cookies.set("tp_refresh", legit, path="/api/v1/auth")
        assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401
        assert (await client.get("/api/v1/auth/me", headers=bearer(access))).status_code == 401

        # The incident is in the audit log.
        relogin = await login(client, "ada@example.com", STRONG_PASSWORD)
        logs = await client.get(
            "/api/v1/audit-logs", headers=bearer(relogin.json()["access_token"])
        )
        reuse = [
            i for i in logs.json()["items"] if i["details"].get("reason") == "refresh_token_reuse"
        ]
        assert len(reuse) == 1
        assert reuse[0]["outcome"] == "denied"


async def test_concurrent_refresh_within_grace_is_tolerated(client: httpx.AsyncClient) -> None:
    await register(client)
    original = client.cookies.get("tp_refresh", path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 200

    # A second tab still holding the original token refreshes within the grace window.
    client.cookies.clear()
    client.cookies.set("tp_refresh", original, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 200


# ------------------------------------------------------------------------------ logout


async def test_logout_revokes_session_and_access_token(client: httpx.AsyncClient) -> None:
    access = (await register(client)).json()["access_token"]

    response = await client.post("/api/v1/auth/logout", headers=CSRF)
    assert response.status_code == 204
    assert (
        'tp_refresh=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )

    assert (await client.get("/api/v1/auth/me", headers=bearer(access))).status_code == 401
    assert (await client.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401


# ------------------------------------------------------------------------------- audit


async def test_audit_log_is_scoped_to_the_current_user(client: httpx.AsyncClient) -> None:
    ada = (await register(client)).json()["access_token"]
    client.cookies.clear()
    bob = (await register(client, email="bob@example.com", display_name="Bob")).json()[
        "access_token"
    ]
    await login(client, "ada@example.com", "definitely-wrong")

    ada_logs = (await client.get("/api/v1/audit-logs", headers=bearer(ada))).json()["items"]
    bob_logs = (await client.get("/api/v1/audit-logs", headers=bearer(bob))).json()["items"]

    assert {i["action"] for i in ada_logs} == {"auth.register", "auth.login"}
    assert any(i["outcome"] == "failure" for i in ada_logs)
    assert [i["action"] for i in bob_logs] == ["auth.register"]


async def test_audit_log_pagination(client: httpx.AsyncClient) -> None:
    access = (await register(client)).json()["access_token"]
    for _ in range(4):
        await login(client, "ada@example.com", STRONG_PASSWORD)

    first = (await client.get("/api/v1/audit-logs?limit=3", headers=bearer(access))).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    second = (
        await client.get(
            f"/api/v1/audit-logs?limit=3&cursor={first['next_cursor']}", headers=bearer(access)
        )
    ).json()
    assert len(second["items"]) == 2 and second["next_cursor"] is None
    ids = [i["id"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 5

    bad = await client.get("/api/v1/audit-logs?cursor=@@@", headers=bearer(access))
    assert bad.status_code == 400
