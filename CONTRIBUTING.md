# Contributing

## Workflow

1. Work on a branch; keep changes scoped to one milestone task.
2. Keep the app working after every change: tests, lint and type checks must pass.
3. Schema changes go through an Alembic migration; never edit an applied migration.
4. API changes: re-export the OpenAPI schema and regenerate frontend types in the same change.
5. Record significant architectural choices in `docs/ENGINEERING_DECISIONS.md`.
6. Never commit secrets. `.env` files are git-ignored; use `.env.example` for documentation.

## Checks

Backend (from `backend/`):

```bash
ruff check . && ruff format --check . && mypy app && pytest -q
```

Frontend (from `frontend/`):

```bash
npm run lint && npm run typecheck && npm test && npm run build
```

API contract (after backend schema changes):

```bash
cd backend && python scripts/export_openapi.py && cd ../frontend && npm run gen:api
```

## Conventions

- **Backend layers:** `api/routes` (HTTP only) → `services` (use cases, no FastAPI imports)
  → `infrastructure` (database, Redis). Domain errors live in `app/domain/exceptions.py`
  and map to the shared error envelope.
- **Ownership:** every query on user data filters by the owner; add an IDOR test for each
  new resource.
- **Frontend:** feature folders under `src/features`, shared primitives in
  `src/components`, server state in TanStack Query, client state in Zustand.
- **Honest UI:** unbuilt features are labelled *Planned*. No mock data presented as real
  output.
- **Copy:** sentence case, plain verbs, errors say what happened and what to do.
- **Dependencies:** pin exact versions; justify new dependencies in the PR description.

## Commit messages

Imperative mood, short subject (≤ 72 chars), body explaining why when it is not obvious.
