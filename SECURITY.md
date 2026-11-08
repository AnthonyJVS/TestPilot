# Security

## Reporting a vulnerability

Please do not open public issues for security problems. Contact the maintainer privately
with a description, reproduction steps and impact. You will get an acknowledgement and a
fix timeline.

## What is implemented (Milestone 1)

| Control | Implementation |
| --- | --- |
| Password storage | Argon2id (argon2-cffi defaults, RFC 9106 profile), automatic rehash on login when parameters change; 12–128 character passwords, not equal to the email |
| Timing safety | Unknown-email sign-ins still run an Argon2 verification; identical error for wrong email and wrong password |
| Access tokens | HS256 JWT, 15 minutes, `iss`/`aud`/`type` checked, `alg=none` rejected; held in memory by the SPA, never in `localStorage` |
| Sessions | Every request re-checks the session row, so sign-out and revocation take effect immediately |
| Refresh tokens | 256-bit random, stored as SHA-256 hashes, rotated on every use, `HttpOnly` + `SameSite=Strict` cookie scoped to `/api/v1/auth`; replaying a rotated token revokes the whole session (20-second grace for concurrent tabs) |
| CSRF | Cookie endpoints (`/auth/refresh`, `/auth/logout`) require `X-Requested-With: testpilot`; CORS is closed by default |
| Brute force | Failed sign-ins limited per email (5 / 15 min) and per IP (20 / 15 min); registrations per IP (10 / hour). Redis-backed in production |
| Audit log | Registration, sign-in success/failure/denial, sign-out and token-reuse incidents with IP, user agent and request ID; users see only their own entries |
| Logging | JSON logs, request IDs, no query strings in access logs, key- and pattern-based secret redaction (passwords, tokens, bearer headers, common provider key formats) |
| Validation errors | Never echo submitted values (prevents passwords appearing in responses) |
| Headers | API: `nosniff`, `DENY` framing, `no-referrer`, `default-src 'none'` CSP, `no-store`. SPA (Nginx): `script-src 'self'` CSP without inline scripts |
| Configuration | `APP_ENV=production` refuses to start without a strong `JWT_SECRET`, Redis and PostgreSQL |
| Containers | API runs as non-root; Nginx image is unprivileged; PostgreSQL/Redis on an internal network; only port 8080 published |

## Planned controls

Tracked in [docs/ARCHITECTURE.md §6](docs/ARCHITECTURE.md#6-security-risks-and-mitigations):
encrypted AI credentials (M2), secret references kept out of AI prompts (M2–M4), browser
worker sandbox with SSRF protection and egress limits (M4), prompt-injection controls
(M3–M7), payload redaction in the Execution Center (M6), usage limits (M2/M8).

## Operating notes

- Set `COOKIE_SECURE=true` whenever TestPilot is served over HTTPS. The compose default of
  `false` exists only so the plain-HTTP localhost demo works in every browser.
- `FORWARDED_ALLOW_IPS="*"` in compose is safe only because the API port is not published;
  restrict it to your proxy's address in other deployments.
- Rotate `JWT_SECRET` to invalidate all access tokens; delete rows from `auth_sessions` to
  force everyone to sign in again.
