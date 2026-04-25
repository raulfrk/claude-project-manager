#!/usr/bin/env bash
# 735-precommit-bisect.sh — Phase 2: per-hook bisection.
# Clones cpm to tmpdir, creates 3 worktrees with disjoint Python edits,
# runs pre-commit with each hook enabled in turn. Detects sibling-file artifact.
#
# Usage: scripts/repro/735-precommit-bisect.sh
# Pre-req: cpm repo has CWD = repo root when invoked.
#
# Exit: 0 = no artifact in any hook config; 1 = artifact reproduced; prints which hook.

set -euo pipefail

CPM_SOURCE="$(git rev-parse --show-toplevel)"
TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-precommit-bisect-$$"
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

# Disjoint files for 3 worktrees (each touches a different plugin)
declare -A BRANCH_FILE=(
  [feat-A]="plugins/proj/server/server/cli.py"
  [feat-B]="plugins/wiki/server/server/main.py"
  [feat-C]="plugins/router/server/server/main.py"
)

mkdir -p "$WORKTREES_DIR"
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Hook bisection: each iteration enables ONE hook (skip-others via SKIP env).
HOOKS=("ruff" "ruff-format" "basedpyright" "update-readme" "check-shared-version")
ALL_HOOKS=$(IFS=,; echo "${HOOKS[*]}")

fail_hook=""
for hook in "${HOOKS[@]}"; do
    # Reset: nuke + recreate the worktrees for clean state per hook
    for branch in feat-A feat-B feat-C; do
        git worktree remove -f "$WORKTREES_DIR/$branch" 2>/dev/null || true
        git branch -D "$branch" 2>/dev/null || true
        git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
    done

    # SKIP all hooks except the one being tested
    SKIP_LIST=$(echo "$ALL_HOOKS" | sed "s/$hook,//;s/,$hook//")

    echo "=== Testing hook: $hook (SKIP=$SKIP_LIST) ==="

    # Each worktree appends to its file + commits with this hook active
    for branch in feat-A feat-B feat-C; do
        f="${BRANCH_FILE[$branch]}"
        cd "$WORKTREES_DIR/$branch"
        # Trivial syntactic-no-op append (a comment)
        echo "# 735-repro-$branch" >> "$f"
        # Force update-readme to trigger by also touching marketplace.json once on feat-A
        if [ "$branch" = "feat-A" ] && [ "$hook" = "update-readme" ]; then
            touch ".claude-plugin/marketplace.json"
        fi
        SKIP="$SKIP_LIST" git commit -am "$branch: $hook test" -q || {
            # If pre-commit fails, that's not the artifact bug. Try again w/ --no-verify.
            git commit -am "$branch: $hook test (skip-on-fail)" -q --no-verify
        }
    done

    # Sequential rebase + FF-merge; detect artifact
    cd "$CLONE"
    artifact_found=0
    for branch in feat-A feat-B feat-C; do
        cd "$WORKTREES_DIR/$branch"
        own_files=$(git diff --name-only "dev..$branch" | sort -u)
        unstaged=$(git diff --name-only | sort -u)
        for u in $unstaged; do
            if ! echo "$own_files" | grep -qx "$u"; then
                echo "ARTIFACT (hook=$hook, worktree=$branch): unstaged sibling file $u"
                artifact_found=1
            fi
        done
        git rebase dev -q || { echo "REBASE FAILED for $branch (hook=$hook)"; }
        cd "$CLONE"
        git merge --ff-only "$branch" -q || true
    done

    if [ "$artifact_found" -eq 1 ]; then
        fail_hook="$hook"
        break
    fi

    # Reset CLONE's dev to start point for next hook test
    git reset --hard origin/dev -q 2>/dev/null || true
done

if [ -n "$fail_hook" ]; then
    echo "FAIL: hook '$fail_hook' produces sibling-file artifact"
    exit 1
else
    echo "PASS: no hook produces artifact (Phase 2 ruled out)"
    exit 0
fi
