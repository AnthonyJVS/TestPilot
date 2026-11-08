# TestPilot backend

FastAPI service for TestPilot. See the [project README](../README.md) for setup and
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for the design.

```
app/
  api/            routes, dependencies, middleware, central error handling
  core/           settings, security (Argon2id, JWT), logging, redaction
  domain/         domain exceptions
  schemas/        Pydantic request/response models (public API contract)
  services/       use cases (auth, audit, system status)
  infrastructure/ database models/session, repositories, Redis/rate limiting
alembic/          migrations
scripts/          export_openapi.py
tests/            unit + integration (SQLite by default, TEST_DATABASE_URL for PostgreSQL)
```
