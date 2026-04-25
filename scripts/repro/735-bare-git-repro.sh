#!/usr/bin/env bash
# 735-bare-git-repro.sh — deterministic 3-worktree repro for sibling-file leak.
# Phase 0+1 of todo 735 investigation. No pre-commit, no tests.
# Idempotent: nukes its tmpdir each run.
#
# Usage: scripts/repro/735-bare-git-repro.sh
# Exit: 0 = no artifact detected (Phase 1 PASS); 1 = artifact reproduced.

set -euo pipefail

TMPDIR_BASE="${TMPDIR:-/tmp}"
WORK="$TMPDIR_BASE/735-bare-git-repro-$$"
SCRATCH="$WORK/scratch"
WORKTREES_DIR="$WORK/wt"

cleanup() { rm -rf "$WORK" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$SCRATCH" "$WORKTREES_DIR"
cd "$SCRATCH"

# Init scratch repo on `dev` branch
git -c init.defaultBranch=dev init -q
git config user.email "test@example.com"
git config user.name "735 repro"

for f in a b c; do
    echo "$f base content" > "$f.txt"
done
git add a.txt b.txt c.txt
git commit -m "init" -q

# Create 3 worktrees off dev
for branch in feat-A feat-B feat-C; do
    git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
done

# Each worktree appends to its OWN file (disjoint changes)
declare -A BRANCH_FILE=( [feat-A]=a [feat-B]=b [feat-C]=c )
for branch in feat-A feat-B feat-C; do
    f="${BRANCH_FILE[$branch]}"
    cd "$WORKTREES_DIR/$branch"
    echo "modified by $branch" >> "$f.txt"
    git commit -am "$branch: modify $f" -q --no-verify
done

# Sequential rebase + FF-merge; check for sibling-file artifact between rebases
fail=0
for branch in feat-A feat-B feat-C; do
    cd "$WORKTREES_DIR/$branch"

    # Files this branch is supposed to own (vs current dev tip)
    own_files=$(git diff --name-only "dev..$branch" | sort -u)
    # Files showing as unstaged in working tree
    unstaged=$(git diff --name-only | sort -u)

    echo "=== Pre-rebase: $branch ==="
    echo "own_files: $own_files"
    echo "unstaged:  $unstaged"

    # Sibling-leak detection: any unstaged file NOT in own_files
    for u in $unstaged; do
        if ! echo "$own_files" | grep -qx "$u"; then
            echo "ARTIFACT: $branch has unstaged sibling file: $u"
            fail=1
        fi
    done

    git rebase dev -q || { echo "REBASE FAILED for $branch"; fail=1; break; }
    cd "$SCRATCH"
    git merge --ff-only "$branch" -q
done

cd "$SCRATCH"
echo "=== Final dev log ==="
git log --oneline | head -5

if [ "$fail" -eq 0 ]; then
    echo "PASS: no sibling-file artifact in Phase 1 (bare git)"
    exit 0
else
    echo "FAIL: sibling-file artifact detected in Phase 1"
    exit 1
fi
