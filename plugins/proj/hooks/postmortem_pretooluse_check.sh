#!/usr/bin/env bash
# PreToolUse trampoline: filter Bash + git-commit + fix-prefix, then forward
# to `run-cli.sh postmortem-pretooluse-git-commit`.
#
# Reads the PreToolUse JSON payload from stdin. Exits silently (0) for any
# non-matching invocation so Claude Code proceeds normally.
set -euo pipefail
payload=$(cat)
echo "$payload" | grep -q '"tool_name"\s*:\s*"Bash"' || exit 0
echo "$payload" | grep -qE 'git[[:space:]]+commit.*(fix|bug)\(' || exit 0
exec "${CLAUDE_PLUGIN_ROOT}/hooks/run-cli.sh" postmortem-pretooluse-git-commit <<< "$payload"
