#!/usr/bin/env bash
# Drift guard: forbid hardcoded TMPDIR/tempfile.gettempdir() and
# claude-cpm-{plugin}-*.sock literals in production code outside the
# plugins/_shared/hook_transport/socket_path.py helper.
#
# Production paths scanned:
#   plugins/*/server/server/
#   plugins/_shared/hook_transport/  (excluding socket_path.py)
#   plugins/_shared/hook_dispatch/
#
# Test paths and helper itself are allowlisted.
#
# Pre-commit hook runs this with pass_filenames=false; it scans the entire
# repo every time so newly-introduced drift is caught regardless of which
# files were staged.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Globs to scan (production source only).
production_paths=(
  "plugins/_shared/hook_transport"
  "plugins/_shared/hook_dispatch"
  "plugins/proj/server/server"
  "plugins/router/server/server"
  "plugins/worktree/server/server"
  "plugins/todoist/server/server"
  "plugins/trello/server/server"
  "plugins/jira/server/server"
  "plugins/confluence/server/server"
  "plugins/wiki/server/server"
)

# Files inside production scan paths that are explicitly exempt.
allowlisted=(
  "plugins/_shared/hook_transport/socket_path.py"
)

violations=0
report() {
  echo "DRIFT: $1"
  violations=$((violations + 1))
}

# Walk each production path and look for forbidden patterns. We use grep -r
# with --include and --exclude tuned to skip __pycache__, generated dirs,
# and the allowlisted helper.
for root in "${production_paths[@]}"; do
  [[ -d "$root" ]] || continue

  # Pattern 1: bare os.environ.get("TMPDIR", ...) calls.
  if matches=$(grep -rn --include='*.py' \
      --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=tests \
      'os\.environ\.get("TMPDIR"' "$root" 2>/dev/null); then
    while IFS= read -r line; do
      file="${line%%:*}"
      skip=0
      for allow in "${allowlisted[@]}"; do
        [[ "$file" == "$allow" ]] && skip=1 && break
      done
      [[ $skip -eq 1 ]] && continue
      report "$line  (use hook_transport.socket_path.{tmp_dir,socket_dir} instead)"
    done <<< "$matches"
  fi

  # Pattern 2: tempfile.gettempdir() calls outside the helper.
  if matches=$(grep -rn --include='*.py' \
      --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=tests \
      'tempfile\.gettempdir(' "$root" 2>/dev/null); then
    while IFS= read -r line; do
      file="${line%%:*}"
      skip=0
      for allow in "${allowlisted[@]}"; do
        [[ "$file" == "$allow" ]] && skip=1 && break
      done
      [[ $skip -eq 1 ]] && continue
      report "$line  (use hook_transport.socket_path.{tmp_dir,socket_dir} instead)"
    done <<< "$matches"
  fi

  # Pattern 3: claude-cpm-{plugin}-*.sock glob literals (PID-tagged form).
  # Catches both '...*.sock' and "...*.sock" forms.
  if matches=$(grep -rnE --include='*.py' \
      --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=tests \
      'claude-cpm-[a-z][a-z0-9_]*-\*\.sock' "$root" 2>/dev/null); then
    while IFS= read -r line; do
      file="${line%%:*}"
      skip=0
      for allow in "${allowlisted[@]}"; do
        [[ "$file" == "$allow" ]] && skip=1 && break
      done
      [[ $skip -eq 1 ]] && continue
      report "$line  (use hook_transport.socket_path.socket_glob(plugin) instead)"
    done <<< "$matches"
  fi
done

if [[ $violations -gt 0 ]]; then
  echo
  echo "Found $violations TMPDIR/socket-glob drift site(s) outside the"
  echo "plugins/_shared/hook_transport/socket_path.py helper."
  echo "Migrate to:"
  echo "  from hook_transport.socket_path import tmp_dir, socket_dir, socket_glob, socket_path"
  echo "Tests are exempt; only production code under plugins/*/server/server/"
  echo "and plugins/_shared/hook_{transport,dispatch}/ is enforced."
  exit 1
fi

exit 0
