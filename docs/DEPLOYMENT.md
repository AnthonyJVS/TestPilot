# Deployment Guide

TestPilot ships as one Docker Compose stack. This guide covers a single-host deployment
(a VM or a workstation); every service is stateless except PostgreSQL, Redis and the artifacts
volume.

## 1. Services

| Service | Image | Role | Networks |
| --- | --- | --- | --- |
| `frontend` | `frontend/Dockerfile` (unprivileged Nginx) | SPA, reverse proxy to the API, the only published port | `edge` |
| `backend` | `backend/Dockerfile` | FastAPI API, SSE streams, serves artifacts read-only | `internal`, `edge` |
| `worker` | `backend/Dockerfile` (Celery) | Orchestrates test runs and workflows, AI calls, artifact retention | `internal`, `edge` |
| `browser-worker` | `backend/browser_worker.Dockerfile` (Playwright) | Runs browsers; no database, no credentials, read-only root FS | `browser`, `browser-egress` |
| `migrate` | `backend/Dockerfile` | One-shot `alembic upgrade head` before the API starts | `internal` |
| `postgres`, `redis` | official images | System of record; queues, pub/sub, rate limits | `internal` (+ `browser` for Redis) |

`internal` and `browser` have no internet access. Only the browser worker reaches the sites
under test (`browser-egress`); only the API and worker reach AI providers (`edge`).

## 2. First start

```bash
cp .env.example .env
```

Set at least `POSTGRES_PASSWORD`, `JWT_SECRET` (≥ 32 characters) and `ENCRYPTION_KEYS`
(`v1:<base64url of 32 random bytes>`):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
```bash
python -c "import base64, os; print('v1:' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

```bash
docker compose up --build -d
```

Open `http://<host>:8080`, create the first account, then connect an AI provider on the
**AI Providers** page. Set `ALLOW_REGISTRATION=false` once your team has accounts.

Verify the whole path, including a real browser run in the isolated worker:

```bash
python backend/scripts/smoke_run.py http://localhost:8080
```

## 3. HTTPS and cookies

Put TestPilot behind a TLS-terminating proxy (Caddy, Traefik, a cloud load balancer) that
forwards to port 8080, then set `COOKIE_SECURE=true`. Restrict `FORWARDED_ALLOW_IPS` to the
proxy's address if the API port is ever published. The SSE route is already configured
without buffering in `frontend/nginx.conf`; an outer proxy must not buffer
`/api/v1/executions/*/events/stream` either.

## 4. Configuration reference (production-relevant)

| Variable | Notes |
| --- | --- |
| `APP_ENV=production` | Enforces PostgreSQL, Redis, a strong `JWT_SECRET`, `ENCRYPTION_KEYS`, and `EXECUTION_MODE=celery` + `BROWSER_TRANSPORT=redis` |
| `ENCRYPTION_KEYS` | Comma-separated `id:key`; the first encrypts, all decrypt. Rotate by prepending a new key, then re-save provider keys and secrets |
| `BROWSER_MAX_SESSIONS` | Parallel browsers per browser-worker container (default 2); scale with `docker compose up --scale browser-worker=N` |
| `RUN_MAX_SECONDS`, `MAX_ACTIVE_RUNS_PER_USER` | Run limits |
| `BROWSER_ALLOW_PRIVATE_NETWORK` | Only if you test internal sites; metadata addresses stay blocked |
| `AI_ALLOW_LOCAL_PROVIDERS` | Off in production by default; enable to use Ollama / LM Studio (use `http://host.docker.internal:11434/v1` from containers) |
| `ARTIFACT_RETENTION_DAYS` | Default 30; `0` keeps artifacts forever |

## 5. Operations

**Backups.** Back up the `pgdata` volume (or `pg_dump`) and keep `ENCRYPTION_KEYS` in your
secret store: without them stored AI keys and test secrets cannot be decrypted. Artifacts are
regenerable evidence; back them up only if you need old screenshots and traces.

**Artifact retention.** Run daily, for example from cron:

```bash
docker compose exec -T worker python -m app.maintenance cleanup-artifacts
```

**Upgrades.** `git pull`, then `docker compose up --build -d`; the `migrate` service applies
Alembic migrations before the API starts.

**Monitoring.** `GET /health/live` and `/health/ready` (API), the Dashboard's system status,
JSON logs with request IDs from every service, and the AI usage section on the AI Providers
page.

## 6. Hardening checklist

- [ ] TLS in front, `COOKIE_SECURE=true`, `ALLOW_REGISTRATION=false` after onboarding.
- [ ] Strong, unique `POSTGRES_PASSWORD`, `JWT_SECRET`, `ENCRYPTION_KEYS` stored outside git.
- [ ] Optional: a Redis ACL user for the browser worker limited to `bw:*` keys.
- [ ] Optional: an egress firewall for `browser-egress` limited to the sites you test.
- [ ] Daily `cleanup-artifacts` and PostgreSQL backups.
