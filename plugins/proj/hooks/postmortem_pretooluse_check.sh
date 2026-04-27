#!/usr/bin/env bash
# PreToolUse trampoline: filter Bash + git-commit + fix-prefix, then forward
# to `run-cli.sh postmortem-pretooluse-git-commit`.
#
# Reads the PreToolUse JSON payload from stdin. Exits silently (0) for any
# non-matching invocation so Claude Code proceeds normally.
#
# Subject-anchoring: the fix-prefix MUST appear immediately after `-m ` (w/
# optional quote) OR after a heredoc EOF + literal "\n" sequence. This avoids
# false-positives like `git commit -m "chore: revert fix(scope) earlier"`
# where `fix(` only appears in the body. Symmetric w/ the Python pre-commit
# hook in scripts/check_postmortem_for_fix.py which anchors on subject only.
#
# All regexes use POSIX character classes ([[:space:]]) — `\s` is non-POSIX
# and silently fails on BSD/macOS grep.
set -euo pipefail
payload=$(cat)
echo "$payload" | grep -q '"tool_name"[[:space:]]*:[[:space:]]*"Bash"' || exit 0
echo "$payload" | grep -qE 'git[[:space:]]+commit' || exit 0
# Anchored subject match. Three accepted forms (post JSON-escape on grep input):
#   1. -m "fix(...   appears as  -m \"fix(    (backslash-quote-fix)
#   2. -m 'fix(...   appears as  -m 'fix(     (quote-fix)
#   3. heredoc subject line: ...EOF\nfix(...  appears as  \nfix(  (literal `\n`)
# Optional prefix between `-m ` and `(fix|bug)\(` is `\\?["']?` — 0 or 1
# backslash, then 0 or 1 quote char.
echo "$payload" \
    | grep -qE -e '-m[[:space:]]+\\?["'"'"']?(fix|bug)\(' -e '\\n(fix|bug)\(' \
    || exit 0
exec "${CLAUDE_PLUGIN_ROOT}/hooks/run-cli.sh" postmortem-pretooluse-git-commit <<< "$payload"
