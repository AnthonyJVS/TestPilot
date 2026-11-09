# Security

## Reporting a vulnerability

Please do not open public issues for security problems. Contact the maintainer privately
with a description, reproduction steps and impact. You will get an acknowledgement and a
fix timeline.

## What is implemented (Milestones 1–4)

| AI control (M2) | Implementation |
| --- | --- |
| Provider keys at rest | AES-256-GCM, versioned keys (`ENCRYPTION_KEYS`), ciphertext bound to its row via associated data; only a 4-character hint is ever returned |
| Key lifecycle | Write-only API; rotate and delete endpoints; audit events for create, rotate, delete, test |
| Custom endpoints | HTTPS only, no embedded credentials, must resolve to public addresses (blocks loopback, private ranges, link-local/metadata) |
| Prompts | Page/user content wrapped as untrusted data with a standing instruction to ignore embedded instructions; outputs validated against schemas |
| Payload storage | Sanitized (redacted, truncated) previews, optional per user ("Keep sanitized prompt and response copies") |
| Provider switching | Never silent: fallback is opt-in, limited to transient/quota errors and recorded |
| Cost control | Optional daily AI request limit pauses AI work; bounded retries; long rate-limit waits are surfaced, not slept on |

| Testing control (M3) | Implementation |
| --- | --- |
| Test secrets | Environment secrets AES-GCM encrypted (bound to environment + name), write-only, audited; never returned, never in plans or generated code |
| AI exposure | Only variable **names** reach AI prompts; scenario text is wrapped as untrusted data |
| No generated code execution | AI output is a schema-validated plan in a closed action set; code is rendered deterministically from the approved plan |
| Navigation scope | `goto` targets outside the project's allowed domains are errors that block approval (network-level enforcement follows in M4) |
| Secret placement | Secrets may only be typed into fields (`fill`/`select_option`), never asserted on or placed in URLs/screenshot names |
| Immutability | Approved versions cannot be edited; changes create new drafts and new versions |

| Execution control (M4) | Implementation |
| --- | --- |
| Browser isolation | Separate `browser-worker` container: no database access, no credentials, no `app` code (test-enforced); non-root, read-only root FS, `cap_drop: ALL`, `no-new-privileges`, memory/CPU/pids limits; reaches Redis over a dedicated network without PostgreSQL and the internet over its own network. Production refuses to start in the unisolated development mode |
| Network policy | Every browser request is intercepted: http(s) only; top-level navigation limited to allowed domains; loopback/private/reserved targets blocked (opt-in for local apps); link-local and cloud metadata always blocked; DNS answers checked |
| Test data | Decrypted only by the orchestrator at run time; secret-typed fields masked in screenshots; traces and video disabled for runs that type secrets; all worker output scrubbed of secret values before storage or streaming |
| Evidence minimisation | Network logs keep method, URL without query string, status and timing (no headers or bodies); console text truncated; event counts capped |
| Artifacts | Stored outside the web root, served only through owner-checked endpoints with fixed content types (`attachment` for non-images); the SPA loads them with the bearer token |
| No generated code execution | The worker interprets the validated step DSL; rendered Playwright code is never executed |
| Abuse limits | Per-run time limit, active runs per user, browser sessions per worker, idle session reaping; cancellation aborts the in-flight browser action |
| Live events | SSE requires the bearer token in a header (fetch-based), is ownership-checked, ends after 10 minutes and resumes with `Last-Event-ID` |

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
prompt-injection controls (M3–M7), payload redaction in the Execution Center (M6), usage
limits (M2/M8), artifact retention (M8), a Redis ACL user restricted to the `bw:*` keys for
the browser worker, and DNS pinning to close the rebinding window of the network policy.

## Operating notes

- Set `COOKIE_SECURE=true` whenever TestPilot is served over HTTPS. The compose default of
  `false` exists only so the plain-HTTP localhost demo works in every browser.
- `FORWARDED_ALLOW_IPS="*"` in compose is safe only because the API port is not published;
  restrict it to your proxy's address in other deployments.
- Rotate `JWT_SECRET` to invalidate all access tokens; delete rows from `auth_sessions` to
  force everyone to sign in again.
