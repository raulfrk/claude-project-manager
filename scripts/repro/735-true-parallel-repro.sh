#!/usr/bin/env bash
# 735-true-parallel-repro.sh — true parallel commit + rebase race repro.
# Phase 4 of todo 735. No pre-commit, no tests; same fixture as bare-git but
# launches per-worktree commit/rebase concurrently via bash backgrounding.
# Idempotent: nukes its tmpdir each iteration.
#
# Usage: scripts/repro/735-true-parallel-repro.sh [iterations]
# Exit: 0 = no artifact across all iterations; 1 = artifact reproduced at least once.

set -uo pipefail

ITERATIONS="${1:-10}"
TMPDIR_BASE="${TMPDIR:-/tmp}"
ANY_FAIL=0
HITS=0

cleanup_iter() { rm -rf "$WORK" 2>/dev/null || true; }

for iter in $(seq 1 "$ITERATIONS"); do
    WORK="$TMPDIR_BASE/735-true-par-repro-$$-$iter"
    SCRATCH="$WORK/scratch"
    WORKTREES_DIR="$WORK/wt"
    mkdir -p "$SCRATCH" "$WORKTREES_DIR"
    cd "$SCRATCH"

    # Init scratch repo on dev branch
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

    declare -A BRANCH_FILE=( [feat-A]=a [feat-B]=b [feat-C]=c )

    # PARALLEL commit phase — 3 worktrees commit concurrently.
    pids=()
    for branch in feat-A feat-B feat-C; do
        f="${BRANCH_FILE[$branch]}"
        (
            cd "$WORKTREES_DIR/$branch"
            echo "modified by $branch" >> "$f.txt"
            git commit -am "$branch: modify $f" -q --no-verify
        ) &
        pids+=($!)
    done
    for pid in "${pids[@]}"; do wait "$pid" || true; done

    # PARALLEL rebase phase — 3 worktrees rebase onto dev concurrently.
    # Capture per-branch artifact reports into temp files (can't share state across subshells).
    REPORTS_DIR="$WORK/reports"
    mkdir -p "$REPORTS_DIR"

    pids=()
    for branch in feat-A feat-B feat-C; do
        (
            cd "$WORKTREES_DIR/$branch"
            own_files=$(git diff --name-only "dev..$branch" | sort -u)
            unstaged=$(git diff --name-only | sort -u)
            untracked=$(git ls-files --others --exclude-standard | sort -u)
            artifacts=""
            for u in $unstaged; do
                if ! echo "$own_files" | grep -qx "$u"; then
                    artifacts="${artifacts}UNSTAGED-SIBLING:$u "
                fi
            done
            for u in $untracked; do
                artifacts="${artifacts}UNTRACKED:$u "
            done
            echo "$branch|own=$own_files|unstaged=$unstaged|untracked=$untracked|artifacts=$artifacts" \
                > "$REPORTS_DIR/$branch.pre"

            git rebase dev -q 2>"$REPORTS_DIR/$branch.rebase.err" \
                && echo "REBASE_OK" > "$REPORTS_DIR/$branch.rebase.status" \
                || echo "REBASE_FAIL" > "$REPORTS_DIR/$branch.rebase.status"

            # Post-rebase artifact check
            unstaged_post=$(git diff --name-only | sort -u)
            untracked_post=$(git ls-files --others --exclude-standard | sort -u)
            echo "$branch|unstaged_post=$unstaged_post|untracked_post=$untracked_post" \
                > "$REPORTS_DIR/$branch.post"
        ) &
        pids+=($!)
    done
    for pid in "${pids[@]}"; do wait "$pid" || true; done

    # Sequentially FF-merge into base repo (this part can't be parallel — same branch ref).
    cd "$SCRATCH"
    for branch in feat-A feat-B feat-C; do
        git merge --ff-only "$branch" -q 2>/dev/null || true
    done

    # Aggregate iteration verdict
    iter_fail=0
    for branch in feat-A feat-B feat-C; do
        if grep -q 'artifacts=.*[A-Z]' "$REPORTS_DIR/$branch.pre" 2>/dev/null; then
            echo "[iter $iter] ARTIFACT in pre-phase for $branch:"
            cat "$REPORTS_DIR/$branch.pre"
            iter_fail=1
        fi
        if grep -q 'REBASE_FAIL' "$REPORTS_DIR/$branch.rebase.status" 2>/dev/null; then
            echo "[iter $iter] REBASE FAILED for $branch:"
            cat "$REPORTS_DIR/$branch.rebase.err"
            iter_fail=1
        fi
        post_unstaged=$(grep -oE 'unstaged_post=[^|]*' "$REPORTS_DIR/$branch.post" \
            | sed 's/unstaged_post=//' | tr -d ' ')
        post_untracked=$(grep -oE 'untracked_post=[^|]*' "$REPORTS_DIR/$branch.post" \
            | sed 's/untracked_post=//' | tr -d ' ')
        if [ -n "$post_unstaged" ] || [ -n "$post_untracked" ]; then
            echo "[iter $iter] POST-REBASE leftovers in $branch: unstaged='$post_unstaged' untracked='$post_untracked'"
            iter_fail=1
        fi
    done

    if [ "$iter_fail" -eq 1 ]; then
        echo "[iter $iter] FAIL — artifact detected"
        HITS=$((HITS + 1))
        ANY_FAIL=1
    else
        echo "[iter $iter] pass"
    fi
    cleanup_iter
done

echo "=================================================="
echo "Summary: $HITS / $ITERATIONS iterations reproduced artifact"
exit "$ANY_FAIL"
