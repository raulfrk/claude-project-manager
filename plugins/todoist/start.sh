#!/bin/bash
set -euo pipefail
DIR="$(cd "$1" && pwd)"
SERVER="$2"
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="$DIR/.venv"

# Ensure _shared (claude-hook-transport) is available at the path
# referenced by pyproject.toml [tool.uv.sources]: ../../_shared
# In the plugin cache the layout is <marketplace>/<plugin>/<version>/server/
# so ../../_shared from server/ resolves to <plugin>/_shared.
SHARED_TARGET="$(cd "$DIR/../.." && pwd)/_shared"
if [ ! -f "$SHARED_TARGET/pyproject.toml" ]; then
  # Search sibling plugin cache dirs for an existing _shared copy
  MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"
  FOUND=""
  for candidate in "$MARKETPLACE_CACHE"/*/_shared/pyproject.toml; do
    if [ -f "$candidate" ]; then
      FOUND="$(dirname "$candidate")"
      break
    fi
  done
  # Fallback: copy from the marketplace source repo
  if [ -z "$FOUND" ]; then
    MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"
    MARKETPLACE_SRC="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/plugins/_shared"
    if [ -f "$MARKETPLACE_SRC/pyproject.toml" ]; then
      FOUND="$MARKETPLACE_SRC"
    fi
  fi
  if [ -n "$FOUND" ]; then
    rm -rf "$SHARED_TARGET"
    cp -a "$FOUND" "$SHARED_TARGET"
  else
    echo "ERROR: _shared (claude-hook-transport) not found in plugin cache or marketplace source." >&2
    echo "Run 'uv sync' in the marketplace repo plugins/_shared/ first." >&2
    exit 1
  fi
fi

test -f "$DIR/.venv/bin/python" || uv sync --frozen --directory "$DIR"
exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"
