#\!/usr/bin/env bash
# Pre-sync all plugin venvs so uv doesn't timeout during MCP server startup.
# Useful when the plugin cache lives on a different filesystem than /tmp.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Sync _shared first — all plugins depend on it via [tool.uv.sources]
shared_dir="$REPO_ROOT/plugins/_shared"
if [ -d "$shared_dir" ]; then
  echo "syncing _shared ..."
  uv sync --directory "$shared_dir"
else
  echo "ERROR: plugins/_shared not found" >&2
  exit 1
fi

plugins=(proj perms worktree trello jira hooks todoist zoxide)

for plugin in "${plugins[@]}"; do
  dir="$REPO_ROOT/plugins/$plugin/server"
  if [ -d "$dir" ]; then
    echo "syncing $plugin ..."
    uv sync --directory "$dir"
  else
    echo "skip $plugin (no server dir)"
  fi
done

echo "done"
