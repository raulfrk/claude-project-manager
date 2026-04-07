#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
DEP_HASH_FILE="$VENV/.dep-hash"

usage() {
    cat <<'USAGE'
Usage: install.sh [--update | --help]

  (no args)   Full install: create venv + sync dependencies
  --update    Sync-only: update deps in existing venv (falls through to full install if venv missing)
  --help      Show this help
USAGE
}

# Compute dep hash from pyproject.toml + uv.lock
compute_dep_hash() {
    cat "$DIR/pyproject.toml" "$DIR/uv.lock" | sha256sum | awk '{print $1}'
}

# Write dep-hash marker into .venv
write_dep_hash() {
    compute_dep_hash > "$DEP_HASH_FILE"
}

# Check uv
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install from https://astral.sh/uv/install.sh" >&2
    exit 1
fi

# Check uv.lock exists
if [ ! -f "$DIR/uv.lock" ]; then
    echo "ERROR: uv.lock not found. Run 'uv lock' first." >&2
    exit 1
fi

# Check uv.lock is not stale (pyproject.toml newer by mtime)
if [ "$DIR/pyproject.toml" -nt "$DIR/uv.lock" ]; then
    echo "ERROR: uv.lock is stale (pyproject.toml is newer). Run 'uv lock' to update." >&2
    exit 1
fi

case "${1:-install}" in
    --help|-h)
        usage
        exit 0
        ;;
    --update)
        if [ ! -f "$VENV/bin/python" ]; then
            echo "No venv found, falling through to full install..."
            uv venv --python 3.12 "$VENV"
        fi
        UV_PROJECT_ENVIRONMENT="$VENV" uv sync --extra plugins --frozen --directory "$DIR"
        write_dep_hash
        echo "Shared venv updated at $VENV"
        ;;
    install)
        # Create venv if needed
        if [ ! -f "$VENV/bin/python" ]; then
            uv venv --python 3.12 "$VENV"
        fi
        UV_PROJECT_ENVIRONMENT="$VENV" uv sync --extra plugins --frozen --directory "$DIR"
        write_dep_hash
        echo "Shared venv ready at $VENV"
        ;;
    *)
        echo "ERROR: Unknown option '$1'" >&2
        usage >&2
        exit 1
        ;;
esac
