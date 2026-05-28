# Vixen — production container image.
#
# Standalone build:
#   docker build -t vixen:local .
#
# Run alembic migrations against the production DB (one-time / on
# schema changes):
#   docker run --rm --env-file .env vixen:local alembic upgrade head
#
# Normal production path is via Kaizen/deploy/docker-compose.box-a.yml,
# which references this Dockerfile by relative `build: context`.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies in a cache-friendly layer.
COPY pyproject.toml ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --upgrade pip wheel \
    && pip install .

# Non-root.
RUN useradd -u 1000 -m vixen \
    && chown -R vixen:vixen /app
USER vixen

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import vixen" || exit 1

ENTRYPOINT ["python", "-m", "vixen"]
