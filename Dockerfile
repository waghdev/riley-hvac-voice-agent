# syntax=docker/dockerfile:1

# Based on LiveKit's uv template (docs.livekit.io/deploy/agents/builds), adapted for this project:
# Python 3.13 to match pyproject.toml, the agent package installed from src/, no dev tools in the
# image, and the venv's python as the entrypoint so a cold start never re-syncs dependencies.
ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

# Unbuffered output, so logs reach LiveKit Cloud even if the process crashes.
ENV PYTHONUNBUFFERED=1
# Compile bytecode at build time; shortens cold starts.
ENV UV_COMPILE_BYTECODE=1

# --- Build stage --------------------------------------------------------------------------
FROM base AS build

# Compilers for any package without a prebuilt wheel; they stay out of the final image.
RUN apt-get update && apt-get install -y gcc g++ python3-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so this layer is cached until uv.lock changes. --no-install-project:
# the project itself needs src/ and README.md, which aren't copied yet.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the code, and the project (editable, so agent/config.py finds /app/config/business.yaml).
COPY . .
RUN uv sync --locked --no-dev

# --- Production stage ---------------------------------------------------------------------
FROM base

# Don't run as root.
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/app" --shell "/sbin/nologin" \
  --uid "${UID}" appuser

WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
USER appuser

# "start" is production mode: JSON logs and a shutdown drain. LIVEKIT_URL, LIVEKIT_API_KEY and
# LIVEKIT_API_SECRET are injected by LiveKit Cloud; other settings come from agent secrets.
CMD [".venv/bin/python", "-m", "agent.main", "start"]
