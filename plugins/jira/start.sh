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

# Resolve marketplace install location via known_marketplaces.json — authoritative
# source-of-truth maintained by Claude Code. Works for github- and directory-source
# installs (the latter live outside ~/.claude/plugins/marketplaces/).
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"
INSTALL_LOC=""
if [ -f "$KNOWN_MARKETPLACES" ] && command -v python3 >/dev/null 2>&1; then
  INSTALL_LOC=$(MARKETPLACE_NAME="$MARKETPLACE_NAME" KM_FILE="$KNOWN_MARKETPLACES" python3 -c '
import json, os
try:
    with open(os.environ["KM_FILE"]) as f:
        data = json.load(f)
    print(data.get(os.environ["MARKETPLACE_NAME"], {}).get("installLocation", ""))
except Exception:
    pass
' 2>/dev/null)
fi

FOUND=""
# Prefer installLocation — covers github + directory-source installs
if [ -n "$INSTALL_LOC" ] && [ -f "$INSTALL_LOC/plugins/_shared/pyproject.toml" ]; then
  FOUND="$INSTALL_LOC/plugins/_shared"
elif [ -f "$MARKETPLACE_SRC/pyproject.toml" ]; then
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

# Locate shared venv via two-stage lookup
SHARED_VENV=""
WALK_UP_FOUND=""

# Stage 1: walk up from $DIR looking for marketplace metadata
walk_dir="$DIR"
while [ "$walk_dir" != "/" ] && [ -n "$walk_dir" ]; do
  if [ -f "$walk_dir/.claude-plugin/marketplace.json" ]; then
    WALK_UP_FOUND="$walk_dir"
    break
  fi
  walk_dir="$(dirname "$walk_dir")"
done

if [ -n "$WALK_UP_FOUND" ] && [ -f "$WALK_UP_FOUND/.venv/bin/python" ]; then
  SHARED_VENV="$WALK_UP_FOUND/.venv"
fi

# Stage 2a: installLocation-derived lookup (directory-source installs)
if [ -z "$SHARED_VENV" ] && [ -n "$INSTALL_LOC" ] && [ -f "$INSTALL_LOC/.venv/bin/python" ]; then
  SHARED_VENV="$INSTALL_LOC/.venv"
fi

# Stage 2b: basename-derived lookup (covers standard cache install)
if [ -z "$SHARED_VENV" ]; then
  BASENAME_CANDIDATE="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
  if [ -f "$BASENAME_CANDIDATE/bin/python" ]; then
    SHARED_VENV="$BASENAME_CANDIDATE"
  fi
fi

if [ -n "$SHARED_VENV" ]; then
  export UV_PROJECT_ENVIRONMENT="$SHARED_VENV"
else
  echo "[start.sh] shared venv not found, falling back to per-plugin venv:" >&2
  echo "  walk-up from $DIR for .claude-plugin/marketplace.json: ${WALK_UP_FOUND:-<not found>}" >&2
  echo "  installLocation lookup tried: ${INSTALL_LOC:-<not resolved>}/.venv" >&2
  echo "  basename lookup tried: $HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv" >&2
  echo "  per-plugin venv: $DIR/.venv (will run 'uv sync --frozen --no-dev')" >&2
  export UV_PROJECT_ENVIRONMENT="$DIR/.venv"
  uv sync --frozen --no-dev --directory "$DIR"
fi

exec uv --directory "$DIR" run --frozen --no-sync "$SERVER"
