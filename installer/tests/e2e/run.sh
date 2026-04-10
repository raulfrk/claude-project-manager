#!/usr/bin/env bash
#
# run.sh — Local runner for e2e tests that mirrors CI behavior.
#
# Builds the cpm-e2e:latest image and runs pytest inside a container with
# narrow bind-mounts matching the CI workflow. Use this to reproduce CI
# results locally without installing the test dependencies on the host.
#
# Usage:
#   ./installer/tests/e2e/run.sh                      # run all e2e tests
#   ./installer/tests/e2e/run.sh installer/tests/e2e/test_snapshots.py
#   SNAPSHOT_CREATE_MISSING=1 ./installer/tests/e2e/run.sh   # seed missing goldens
#   SNAPSHOT_UPDATE=1 ./installer/tests/e2e/run.sh           # regenerate all goldens
#
# Environment variables:
#   SNAPSHOT_CREATE_MISSING  If set to 1, create missing snapshot goldens.
#   SNAPSHOT_UPDATE          If set to 1, regenerate all snapshot goldens.
#
# Any additional arguments are forwarded to pytest inside the container.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Build the e2e image (or cache-hit if unchanged).
docker build -f installer/tests/e2e/Dockerfile -t cpm-e2e:latest .

# Run pytest with narrow bind-mount mirroring CI.
# --user avoids root-owned file writes on the host.
# SNAPSHOT_CREATE_MISSING=1 seeds missing goldens; SNAPSHOT_UPDATE=1 regenerates all.
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$REPO_ROOT/installer":/app/installer \
  -v "$REPO_ROOT/plugins":/app/plugins \
  -v "$REPO_ROOT/pyproject.toml":/app/pyproject.toml:ro \
  -v "$REPO_ROOT/uv.lock":/app/uv.lock:ro \
  -v "$REPO_ROOT/installer/tests/e2e/snapshots":/app/installer/tests/e2e/snapshots \
  -e SNAPSHOT_CREATE_MISSING="${SNAPSHOT_CREATE_MISSING:-}" \
  -e SNAPSHOT_UPDATE="${SNAPSHOT_UPDATE:-}" \
  cpm-e2e:latest "$@"
