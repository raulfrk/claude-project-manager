#!/usr/bin/env bash
# Caveman guard pre-commit hook.
#
# Rejects commits on main or dev that add caveman-experiment marker strings.
# On dev-caveman (or any other branch), the hook is a no-op so the experiment
# can evolve freely in isolation.
#
# Install via .pre-commit-config.yaml local repo.

set -euo pipefail

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"

case "$branch" in
  main|dev)
    ;;
  *)
    exit 0
    ;;
esac

markers=(
  "Caveman-Aware Output"
  "CPM-CAVEMAN-BACKUP"
  "Caveman Mode Precedence"
  "_CAVEMAN_APPEND"
  "# cpm:caveman"
)

staged_files="$(git diff --cached --name-only --diff-filter=ACMR)"
if [ -z "$staged_files" ]; then
  exit 0
fi

failed=0
for m in "${markers[@]}"; do
  while IFS= read -r file; do
    [ -z "$file" ] && continue
    case "$file" in
      .github/workflows/caveman-guard.yml|.pre-commit-hooks/caveman-guard.sh)
        continue
        ;;
    esac
    if git diff --cached -- "$file" | grep -F -q "+$m"; then
      echo "caveman-guard: marker '$m' added in $file" >&2
      failed=1
    fi
  done <<< "$staged_files"
done

if [ "$failed" -ne 0 ]; then
  echo >&2
  echo "caveman-guard: caveman content must stay on the dev-caveman branch." >&2
  echo "caveman-guard: use 'git checkout dev-caveman' and retry if this is caveman work." >&2
  exit 1
fi

exit 0
