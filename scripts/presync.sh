#\!/usr/bin/env bash
# Pre-sync all plugin venvs so uv doesn't timeout during MCP server startup.
# Useful when the plugin cache lives on a different filesystem than /tmp.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

plugins=(proj perms worktree trello jira)

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
