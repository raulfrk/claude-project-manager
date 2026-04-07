#!/bin/bash
set -euo pipefail
DIR="$(cd "$1" && pwd)"
SERVER="$2"
export UV_LINK_MODE=copy
export UV_CACHE_DIR="${UV_CACHE_DIR:-$DIR/.uv-cache}"

# Ensure _shared (claude-hook-transport) is available and up-to-date.
# In the plugin cache the layout is <marketplace>/<plugin>/<version>/server/
# so ../../_shared from server/ resolves to <plugin>/_shared (shared across versions).
SHARED_TARGET="$(cd "$DIR/../.." && pwd)/_shared"
MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"
MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"
MARKETPLACE_SRC="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/plugins/_shared"

FOUND=""
# Prefer marketplace source — it's what "update marketplace" refreshes
if [ -f "$MARKETPLACE_SRC/pyproject.toml" ]; then
  FOUND="$MARKETPLACE_SRC"
else
  # Fall back to sibling plugin cache dirs
  for candidate in "$MARKETPLACE_CACHE"/*/_shared/pyproject.toml; do
    if [ -f "$candidate" ]; then
      FOUND="$(dirname "$candidate")"
      break
    fi
  done
fi

if [ -n "$FOUND" ]; then
  # Refresh _shared if missing or if its version changed (bump _shared/pyproject.toml to signal changes)
  SRC_VERSION=$(grep '^version' "$FOUND/pyproject.toml" 2>/dev/null | head -1 | cut -d'"' -f2)
  CACHED_VERSION=$(grep '^version' "$SHARED_TARGET/pyproject.toml" 2>/dev/null | head -1 | cut -d'"' -f2 || echo "")
  if [ ! -f "$SHARED_TARGET/pyproject.toml" ] || [ "$SRC_VERSION" != "$CACHED_VERSION" ]; then
    rm -rf "$SHARED_TARGET"
    cp -a "$FOUND" "$SHARED_TARGET"
    # Force venv rebuild so the updated _shared package is installed
    rm -rf "$DIR/.venv"
  fi
else
  if [ ! -f "$SHARED_TARGET/pyproject.toml" ]; then
    echo "ERROR: _shared (claude-hook-transport) not found in plugin cache or marketplace source." >&2
    echo "Run 'uv sync' in the marketplace repo plugins/_shared/ first." >&2
    exit 1
  fi
fi

# Use shared marketplace venv if available, otherwise fall back to per-plugin venv
SHARED_VENV="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
if [ -f "$SHARED_VENV/bin/python" ]; then
  export UV_PROJECT_ENVIRONMENT="$SHARED_VENV"
else
  echo "Shared venv not found, falling back to per-plugin venv" >&2
  export UV_PROJECT_ENVIRONMENT="$DIR/.venv"
  test -f "$DIR/.venv/bin/python" || uv sync --frozen --directory "$DIR"
fi

exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"
