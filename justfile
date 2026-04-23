# Root-level justfile — orchestrates cross-plugin developer workflows.
#
# Per-plugin justfiles (plugins/<name>/server/justfile) remain the authoritative
# single-plugin interface. This file sets up ALL plugin dirs so a fresh clone
# can reach CI parity with `just sync && just test`.
#
# Ordering:
#   1. plugins/_shared first (other plugins + installer depend on it as a uv
#      path dep; its wheel must be available before dependents resolve).
#   2. installer at repo root second (cpm-install pyproject lives here).
#   3. Remaining plugin servers in declaration order.

_PLUGIN_DIRS := "plugins/router/server plugins/proj/server plugins/worktree/server plugins/todoist/server plugins/trello/server plugins/jira/server plugins/confluence/server plugins/wiki/server"

default: help

help:
    @just --list

# Install dev deps in every plugin + installer. Runs `uv sync --all-groups`
# in each directory. Does NOT fail-fast: aggregates failures and exits
# non-zero at the end if any dir failed.
sync:
    #!/usr/bin/env bash
    set -u
    failed=0
    echo "=== uv sync --all-groups (plugins/_shared) ==="
    (cd plugins/_shared && uv sync --all-groups) || { echo ">>> FAILED: plugins/_shared"; failed=$((failed+1)); }
    echo ""
    echo "=== uv sync --all-groups (installer @ repo root) ==="
    uv sync --all-groups || { echo ">>> FAILED: installer"; failed=$((failed+1)); }
    for d in {{_PLUGIN_DIRS}}; do
      echo ""
      echo "=== uv sync --all-groups ($d) ==="
      (cd "$d" && uv sync --all-groups) || { echo ">>> FAILED: $d"; failed=$((failed+1)); }
    done
    if [[ $failed -gt 0 ]]; then
      echo ""
      echo "SYNC FAILED in $failed dir(s)"
      exit 1
    fi

# Run pytest in every plugin + installer. Does NOT fail-fast.
test:
    #!/usr/bin/env bash
    # Order here is presentation-only (no dep-resolve concern for tests).
    # Installer runs first so repo-root pytest output appears at the top.
    set -u
    failed=0
    echo "=== pytest (installer @ repo root) ==="
    uv run pytest installer/tests || { echo ">>> FAILED: installer"; failed=$((failed+1)); }
    echo ""
    echo "=== pytest (plugins/_shared) ==="
    (cd plugins/_shared && uv run pytest) || { echo ">>> FAILED: plugins/_shared"; failed=$((failed+1)); }
    for d in {{_PLUGIN_DIRS}}; do
      echo ""
      echo "=== pytest ($d) ==="
      (cd "$d" && uv run pytest) || { echo ">>> FAILED: $d"; failed=$((failed+1)); }
    done
    if [[ $failed -gt 0 ]]; then
      echo ""
      echo "TEST FAILED in $failed dir(s)"
      exit 1
    fi

# Full local CI mirror: sync then test.
ci: sync test
