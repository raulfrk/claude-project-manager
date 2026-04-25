#!/usr/bin/env bash
# 735-tests-bisect.sh — Phase 3: tests bisection on top of full pre-commit.
# Same fixture as precommit-bisect; adds pytest run per worktree.
# Detects sibling-file artifact post-pytest.

set -euo pipefail

CPM_SOURCE="$(git rev-parse --show-toplevel)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-tests-bisect-$$"
CLONE="$WORK/cpm"
WORKTREES_DIR="$WORK/wt"

cleanup() { rm -rf "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$WORK"
git clone --no-hardlinks --shared "$CPM_SOURCE" "$CLONE" -q
cd "$CLONE"
git checkout dev -q 2>/dev/null || git checkout -b dev origin/dev -q
git config user.email "test@example.com"
git config user.name "735 repro"

declare -A BRANCH_FILE=(
  [feat-A]="plugins/proj/server/server/cli.py"
  [feat-B]="plugins/wiki/server/server/main.py"
  [feat-C]="plugins/router/server/server/main.py"
)
declare -A BRANCH_TESTDIR=(
  [feat-A]="plugins/proj/server"
  [feat-B]="plugins/wiki/server"
  [feat-C]="plugins/router/server"
)

mkdir -p "$WORKTREES_DIR"
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Each worktree: edit + commit + run pytest + rebase + FF-merge; check artifact
fail=0
for branch in feat-A feat-B feat-C; do
    f="${BRANCH_FILE[$branch]}"
    testdir="${BRANCH_TESTDIR[$branch]}"

    cd "$WORKTREES_DIR/$branch"
    echo "# 735-test-$branch" >> "$f"
    git commit -am "$branch: test bisect" -q

    # Run pytest in this worktree's plugin
    cd "$WORKTREES_DIR/$branch/$testdir"
    uv sync --all-groups -q 2>&1 | tail -2 || true
    uv run pytest --no-cov -x 2>&1 | tail -5 || true

    # Check for cross-worktree leakage NOW (before rebase, after pytest)
    cd "$WORKTREES_DIR/$branch"
    own_files=$(git diff --name-only "dev..$branch" | sort -u)
    unstaged=$(git diff --name-only | sort -u)
    for u in $unstaged; do
        if ! echo "$own_files" | grep -qx "$u"; then
            echo "ARTIFACT (post-pytest, worktree=$branch): unstaged sibling file $u"
            fail=1
        fi
    done

    git rebase dev -q || { echo "REBASE FAILED for $branch"; fail=1; }
    cd "$CLONE"
    git merge --ff-only "$branch" -q || true
done

if [ "$fail" -eq 1 ]; then
    echo "FAIL: pytest run produced sibling-file artifact"
    exit 1
else
    echo "PASS: pytest run did not produce artifact (Phase 3 ruled out)"
    exit 0
fi
