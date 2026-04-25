#!/usr/bin/env bash
# 735-mcp-merge-semantics-repro.sh — mimic wt_merge MCP tool semantics under
# true parallelism: rebase in worktree, then FF-merge via atomic update-ref CAS.
#
# Phase 5 fix verification for todo 735. Tests that the atomic `git update-ref`
# CAS approach (replacing `git merge --ff-only`) eliminates the race that leaked
# files into the base repo's working tree.
#
# The fix: instead of `git merge --ff-only <branch>` from the base repo (racy
# on .git/HEAD + .git/index.lock), we use `git update-ref` CAS from the
# worktree, then sync the base repo's index + working tree.
#
# Usage: scripts/repro/735-mcp-merge-semantics-repro.sh [iterations]

set -uo pipefail

ITERATIONS="${1:-10}"
TMPDIR_BASE="${TMPDIR:-/tmp}"
ANY_FAIL=0
HITS=0

cleanup_iter() { rm -rf "$WORK" 2>/dev/null || true; }

# Atomic CAS ff-merge: mirrors the Python merge_ff_only(repo_path, branch, worktree_path, base_branch).
# Args: $1=worktree_path $2=branch $3=base_branch $4=base_repo_path
# Returns 0 on success, 1 on non-FF, 2 on max retries exhausted.
cas_merge_ff() {
    local wt_path="$1" branch="$2" base_branch="$3" repo_path="$4"
    local max_retries=5
    local attempt new_sha old_sha
    # Backoff in seconds (mirrors Python 10ms, 20ms, 40ms, 80ms, 160ms)
    local backoff=(0.01 0.02 0.04 0.08 0.16)

    for attempt in $(seq 0 $((max_retries - 1))); do
        # Read current base_branch ref.
        old_sha=$(git -C "$wt_path" rev-parse "refs/heads/${base_branch}" 2>/dev/null) || return 1

        # Verify FF-mergeable.
        git -C "$wt_path" merge-base --is-ancestor "$old_sha" "$branch" 2>/dev/null || return 1

        # Read branch tip.
        new_sha=$(git -C "$wt_path" rev-parse "$branch" 2>/dev/null) || return 1

        # Atomic CAS.
        if git -C "$wt_path" update-ref "refs/heads/${base_branch}" "$new_sha" "$old_sha" 2>/dev/null; then
            # Sync base repo index + working tree.
            # Check for unstaged changes (working tree vs index) before deciding strategy.
            if git -C "$repo_path" diff --quiet 2>/dev/null; then
                # Clean working tree: hard reset updates both index and working tree.
                git -C "$repo_path" reset --hard HEAD 2>/dev/null || true
            else
                # Dirty working tree: keep preserves unstaged work; aborts on conflict.
                git -C "$repo_path" reset --keep HEAD 2>/dev/null || true
            fi
            return 0
        fi

        # CAS failed — another caller updated ref; retry after backoff.
        sleep "${backoff[$attempt]}" 2>/dev/null || sleep 0.1
    done
    return 2
}

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
    #   rebase in worktree  AND THEN  atomic CAS ff-merge (fix for todo 735)
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

            # Imitate fixed wt_merge: atomic CAS update-ref from worktree (not racy git merge --ff-only)
            cas_merge_ff "$wt" "$branch" "dev" "$SCRATCH" \
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
