#!/bin/bash
set -euo pipefail
DIR="$(cd "$1" && pwd)"
SERVER="$2"
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="$DIR/.venv"
test -f "$DIR/.venv/bin/python" || uv sync --frozen --directory "$DIR"
exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"
