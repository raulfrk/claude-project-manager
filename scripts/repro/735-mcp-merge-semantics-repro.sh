#!/usr/bin/env bash
# 735-mcp-merge-semantics-repro.sh — mimic wt_merge MCP tool semantics under
# true parallelism: rebase in worktree, then FF-merge in base repo (cwd=base).
#
# Phase 4b of todo 735. Tests whether concurrent merge_ff_only calls in the
# SAME base repo working tree (where dev is checked out) race + leak files
# into sibling worktrees.
#
# Usage: scripts/repro/735-mcp-merge-semantics-repro.sh [iterations]

set -uo pipefail

ITERATIONS="${1:-10}"
TMPDIR_BASE="${TMPDIR:-/tmp}"
ANY_FAIL=0
HITS=0

cleanup_iter() { rm -rf "$WORK" 2>/dev/null || true; }

for iter in $(seq 1 "$ITERATIONS"); do
    WORK="$TMPDIR_BASE/735-mcp-merge-$$-$iter"
    SCRATCH="$WORK/scratch"
    WORKTREES_DIR="$WORK/wt"
    mkdir -p "$SCRATCH" "$WORKTREES_DIR"
    cd "$SCRATCH"

    git -c init.defaultBranch=dev init -q
    git config user.email "test@example.com"
    git config user.name "735 repro"

    for f in a b c; do echo "$f base content" > "$f.txt"; done
    git add a.txt b.txt c.txt
    git commit -m "init" -q

    for branch in feat-A feat-B feat-C; do
        git worktree add -b "$branch" "$WORKTREES_DIR/$branch" dev -q
    done

    declare -A BRANCH_FILE=( [feat-A]=a [feat-B]=b [feat-C]=c )

    # Sequential commit (not the bug surface)
    for branch in feat-A feat-B feat-C; do
        f="${BRANCH_FILE[$branch]}"
        cd "$WORKTREES_DIR/$branch"
        echo "modified by $branch" >> "$f.txt"
        git commit -am "$branch: modify $f" -q --no-verify
    done

    # PARALLEL wt_merge-style execution — each runs:
    #   rebase in worktree  AND THEN  FF-merge in base repo (shared cwd!)
    REPORTS_DIR="$WORK/reports"
    mkdir -p "$REPORTS_DIR"

    pids=()
    for branch in feat-A feat-B feat-C; do
        (
            wt="$WORKTREES_DIR/$branch"
            cd "$wt"
            git rebase --no-fork-point dev -q 2>"$REPORTS_DIR/$branch.rebase.err" \
                && echo "REBASE_OK" > "$REPORTS_DIR/$branch.rebase.status" \
                || { echo "REBASE_FAIL" > "$REPORTS_DIR/$branch.rebase.status"; exit 0; }

            # Imitate wt_merge: merge_ff_only with cwd=base_repo
            (cd "$SCRATCH" && git merge --ff-only "$branch" -q) \
                2>"$REPORTS_DIR/$branch.ffmerge.err" \
                && echo "FFMERGE_OK" > "$REPORTS_DIR/$branch.ffmerge.status" \
                || echo "FFMERGE_FAIL" > "$REPORTS_DIR/$branch.ffmerge.status"
        ) &
        pids+=($!)
    done
    for pid in "${pids[@]}"; do wait "$pid" || true; done

    # Aggregate iteration verdict
    iter_fail=0
    cd "$SCRATCH"
    base_unstaged=$(git diff --name-only | sort -u)
    base_untracked=$(git ls-files --others --exclude-standard | sort -u)
    if [ -n "$base_unstaged" ] || [ -n "$base_untracked" ]; then
        echo "[iter $iter] BASE-REPO leftovers: unstaged='$base_unstaged' untracked='$base_untracked'"
        iter_fail=1
    fi

    for branch in feat-A feat-B feat-C; do
        wt="$WORKTREES_DIR/$branch"
        if [ ! -d "$wt" ]; then continue; fi
        cd "$wt"
        wt_unstaged=$(git diff --name-only | sort -u)
        wt_untracked=$(git ls-files --others --exclude-standard | sort -u)
        if [ -n "$wt_unstaged" ] || [ -n "$wt_untracked" ]; then
            echo "[iter $iter] WORKTREE leftovers in $branch: unstaged='$wt_unstaged' untracked='$wt_untracked'"
            iter_fail=1
        fi
        # Check ffmerge status per branch
        ff_status=$(cat "$REPORTS_DIR/$branch.ffmerge.status" 2>/dev/null || echo "MISSING")
        if [ "$ff_status" = "FFMERGE_FAIL" ]; then
            echo "[iter $iter] FF-merge failed for $branch (expected if non-FF after sibling merge): $(cat "$REPORTS_DIR/$branch.ffmerge.err")"
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
