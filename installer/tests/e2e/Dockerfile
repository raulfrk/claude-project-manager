# E2E test environment for the cpm-install TUI installer.
# Provides Python 3.12, Node.js (for Claude CLI), git, and uv.
#
# Source code is NOT copied into the image — it is bind-mounted at runtime
# into /app. This keeps the image cache stable across source changes; only
# pyproject.toml / uv.lock changes invalidate the dep-install layer.

# --- Stage 1: fetch uv binary ---
FROM ghcr.io/astral-sh/uv:latest AS uv

# --- Stage 2: test runner ---
FROM docker.io/python:3.12-slim

# System packages: git for plugin detection, curl for Node.js setup
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        ca-certificates \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js LTS (required by Claude CLI npm package)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally via npm
RUN npm install -g @anthropic-ai/claude-code

# Copy uv from the first stage
COPY --from=uv /uv /usr/local/bin/uv

# Install the venv to /opt/venv (outside /app) so the runtime bind-mount
# on /app does not shadow it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Build dependencies in an isolated directory so /app stays clean for the
# runtime bind-mount.
WORKDIR /build

# Copy dependency manifests first to leverage Docker layer caching.
COPY pyproject.toml uv.lock* ./

# Copy the _shared workspace package — the root project declares
# claude-hook-transport (path = plugins/_shared) as a runtime dependency,
# so uv must be able to resolve and build its metadata at install time
# even with --no-install-project (which only skips the *root* project).
COPY plugins/_shared ./plugins/_shared

# Install test dependencies without installing the root installer project.
# --no-install-project skips the root hatchling build (which would need
# the installer/ source). claude-hook-transport (above) is built normally.
# Runtime bind-mount provides the installer source on /app.
RUN uv sync --frozen --no-install-project --group test \
    || uv sync --no-install-project --group test

# Runtime working directory — source is bind-mounted here at `docker run`.
WORKDIR /app

# Point Python / pytest at the pre-built venv.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Prevent host tree pollution from the bind-mount:
#   - no __pycache__/*.pyc written next to source files
#   - .pytest_cache/ redirected out of /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTEST_CACHE_DIR=/tmp/pytest-cache

CMD ["pytest", "installer/tests/e2e/", "-v"]
