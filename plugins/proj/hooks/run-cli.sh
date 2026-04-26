#!/bin/bash
# Hook-time wrapper for `python -m server.cli`. Mirrors plugins/proj/start.sh
# 3-stage probe to locate the shared marketplace venv, then execs the CLI.
#
# Why a wrapper instead of `${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python` direct:
# the runtime architecture is shared-venv-only (no per-plugin .venv guaranteed
# on production cache-only installs). Probe must match start.sh so hooks and
# MCP servers resolve to the same interpreter.
#
# Args ($@) are forwarded to `server.cli` verbatim.
set -euo pipefail

DIR="${CLAUDE_PLUGIN_ROOT:-}/server"
if [ ! -d "$DIR" ]; then
  echo "ERROR: CLAUDE_PLUGIN_ROOT/server not found: $DIR" >&2
  exit 1
fi
DIR="$(cd "$DIR" && pwd)"

MARKETPLACE_CACHE="$(cd "$DIR/../../.." && pwd)"
MARKETPLACE_NAME="$(basename "$MARKETPLACE_CACHE")"

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

SHARED_VENV=""
WALK_UP_FOUND=""

# Stage 1: walk up from $DIR for marketplace metadata.
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

# Stage 2a: installLocation-derived (directory-source installs).
if [ -z "$SHARED_VENV" ] && [ -n "$INSTALL_LOC" ] && [ -f "$INSTALL_LOC/.venv/bin/python" ]; then
  SHARED_VENV="$INSTALL_LOC/.venv"
fi

# Stage 2b: basename-derived (standard cache install).
if [ -z "$SHARED_VENV" ]; then
  BASENAME_CANDIDATE="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv"
  if [ -f "$BASENAME_CANDIDATE/bin/python" ]; then
    SHARED_VENV="$BASENAME_CANDIDATE"
  fi
fi

if [ -z "$SHARED_VENV" ]; then
  echo "ERROR: shared marketplace venv not found." >&2
  echo "Probed:" >&2
  echo "  walk-up from $DIR for .claude-plugin/marketplace.json: ${WALK_UP_FOUND:-<not found>}" >&2
  echo "  installLocation lookup: ${INSTALL_LOC:-<not resolved>}/.venv" >&2
  echo "  basename lookup: $HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME/.venv" >&2
  echo "Fix: cpm-install --reinstall" >&2
  exit 1
fi

exec env PYTHONPATH="$DIR" "$SHARED_VENV/bin/python" -m server.cli "$@"
