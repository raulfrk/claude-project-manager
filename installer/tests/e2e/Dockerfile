# E2E test environment for the cpm-install TUI installer.
# Provides Python 3.12, Node.js (for Claude CLI), git, and uv.

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

WORKDIR /app

# Copy dependency manifests first to leverage Docker layer caching
COPY pyproject.toml uv.lock* ./

# Install test dependencies (frozen lockfile when available)
RUN uv sync --frozen --group test || uv sync --group test

# Copy the full project
COPY . .

# Re-sync to pick up the local editable install
RUN uv sync --frozen --group test || uv sync --group test

CMD ["uv", "run", "pytest", "installer/tests/e2e/", "-v"]
