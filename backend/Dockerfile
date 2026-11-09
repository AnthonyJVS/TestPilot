# TestPilot API image. Used by the `migrate` (one-shot), `backend` and `worker` (Celery) services.
# Browsers are not installed here: they run in the separate browser-worker image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Fixed UID shared with the browser-worker image (artifacts volume).
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /artifacts && chown app:app /artifacts

# Dependencies first (cached layer): read the pinned list straight from pyproject.toml.
COPY pyproject.toml README.md ./
RUN python -c "import subprocess, sys, tomllib; \
deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; \
subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])"
# Fail the build, not the first test run, if the job queue's Redis transport cannot load.
RUN python -c "import kombu.transport.redis, celery, redis; print('celery queue transport ok')"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
# Only the typed protocol is used by the API; the engine module needs Playwright and is not imported.
COPY browser_worker ./browser_worker

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

# Proxy headers are trusted from FORWARDED_ALLOW_IPS (set by docker-compose; the API port is not published).
CMD ["uvicorn", "--factory", "app.main:app_factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-access-log"]
