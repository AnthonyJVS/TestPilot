# Isolated browser worker (ADR-005). Contains Playwright, its browsers and the `browser_worker`
# package only: no application code, no database driver, no AI SDKs and no credentials.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    ARTIFACTS_DIR=/artifacts

# Same versions as pyproject.toml.
RUN python -m pip install "playwright==1.62.0" "pydantic==2.14.3" "redis==8.1.0"

# Fixed UID shared with the API image so both can use the artifacts volume.
RUN groupadd --gid 10001 worker && useradd --uid 10001 --gid worker --no-create-home worker \
    && mkdir -p /artifacts /app && chown worker:worker /artifacts

WORKDIR /app
COPY browser_worker ./browser_worker

USER worker
CMD ["python", "-m", "browser_worker"]
