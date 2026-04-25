#!/usr/bin/env bash
# audit-685-687-rule.sh — flag worktrees that may have skipped the post-wt_create remote sync.
#
# Background: managed CLAUDE.md rule 13 (formerly rule 685, refined by 687) instructs Claude
# to run `git fetch origin` then conditionally `git reset --hard origin/<base>` (or `<base>`
# if local has unpushed commits) after wt_create. If Claude misparsed the conditional, the
# worktree's HEAD may sit behind origin/<base-branch> by commits that existed at creation time
# — i.e. the worktree never picked up remote work that was already there.
#
# Detection heuristic: for each worktree directory found under WORKTREES_ROOT:
#   1. Resolve the worktree's current branch and its upstream (tracking branch).
#   2. Fetch origin (read-only — no local state change).
#   3. Count commits reachable from origin/<base> but not from HEAD.
#   4. If that count > 0, flag the worktree and explain how many commits it is behind.
#
# This is a heuristic: a worktree may be intentionally behind its base (e.g. if the user
# only wants a slice of origin). The output is informational, not authoritative.
#
# Exit codes:
#   0 — no anomalies detected
#   1 — one or more worktrees flagged
#
# Usage:
#   ./scripts/audit-685-687-rule.sh [WORKTREES_ROOT]
#
# WORKTREES_ROOT defaults to $HOME/worktrees if not supplied as $1 or via env var.
# Override: WORKTREES_ROOT=/path/to/worktrees ./scripts/audit-685-687-rule.sh

set -euo pipefail

WORKTREES_ROOT="${1:-${WORKTREES_ROOT:-$HOME/worktrees}}"

# Suppress zoxide config noise when sourced indirectly.
export _ZO_DOCTOR=0
ANOMALIES=0

if [ ! -d "$WORKTREES_ROOT" ]; then
  echo "No worktrees root at $WORKTREES_ROOT — nothing to audit."
  exit 0
fi

# find_worktrees: emit all second-level dirs (WORKTREES_ROOT/<repo>/<branch>)
# that are git worktrees (contain a .git file or .git dir).
find_worktrees() {
  local root="$1"
  # two-level glob: repo/branch
  for repo_dir in "$root"/*/; do
    [ -d "$repo_dir" ] || continue
    for wt_dir in "$repo_dir"*/; do
      [ -d "$wt_dir" ] || continue
      # A git worktree has a .git file (not a dir) pointing back to the main repo.
      if [ -f "$wt_dir/.git" ] || [ -d "$wt_dir/.git" ]; then
        printf '%s\n' "${wt_dir%/}"
      fi
    done
  done
}

audit_worktree() {
  local wt="$1"

  # Resolve current branch name (HEAD may be detached — skip those).
  local branch
  branch=$(git -C "$wt" symbolic-ref --short HEAD 2>/dev/null) || {
    echo "  SKIP $wt — detached HEAD"
    return 0
  }

  # Find remote tracking ref. Common patterns:
  #   branch.foo.remote + branch.foo.merge  →  remote/branch
  local remote merge_ref upstream
  remote=$(git -C "$wt" config --get "branch.${branch}.remote" 2>/dev/null) || remote=""
  merge_ref=$(git -C "$wt" config --get "branch.${branch}.merge" 2>/dev/null) || merge_ref=""

  if [ -z "$remote" ] || [ -z "$merge_ref" ]; then
    # No upstream configured — try origin/<branch> as fallback.
    remote="origin"
    merge_ref="refs/heads/${branch}"
  fi

  # Convert refs/heads/foo → foo.
  local base_branch="${merge_ref#refs/heads/}"
  upstream="${remote}/${base_branch}"

  # Fetch to update remote refs (read-only — does NOT touch working tree or local branches).
  git -C "$wt" fetch "$remote" --quiet 2>/dev/null || {
    echo "  WARN $wt — fetch ${remote} failed (offline?); skipping"
    return 0
  }

  # Check if upstream ref exists after fetch.
  if ! git -C "$wt" rev-parse --verify "$upstream" >/dev/null 2>&1; then
    echo "  SKIP $wt — ${upstream} not found (branch not pushed yet?)"
    return 0
  fi

  # Count commits on upstream that are NOT reachable from our HEAD.
  local behind_count
  behind_count=$(git -C "$wt" rev-list --count "HEAD..${upstream}" 2>/dev/null) || behind_count=0

  if [ "$behind_count" -gt 0 ]; then
    echo "  FLAG $wt"
    echo "       branch:   $branch"
    echo "       upstream: $upstream"
    echo "       behind:   ${behind_count} commit(s) on ${upstream} not in HEAD"
    echo "       → possible rule-685/687 misparse (reset --hard may have been skipped)"
    ANOMALIES=$((ANOMALIES + 1))
  else
    echo "  OK   $wt  ($branch ← ${upstream})"
  fi
}

echo "Auditing worktrees under: $WORKTREES_ROOT"
echo "---"

wt_list=$(find_worktrees "$WORKTREES_ROOT")

if [ -z "$wt_list" ]; then
  echo "No git worktrees found under $WORKTREES_ROOT — nothing to audit."
  exit 0
fi

while IFS= read -r wt; do
  audit_worktree "$wt"
done <<< "$wt_list"

echo "---"
if [ "$ANOMALIES" -gt 0 ]; then
  echo "Found ${ANOMALIES} potential rule-685/687 misparse(s). Review flagged worktrees above."
  exit 1
fi
echo "No anomalies. All audited worktrees are current with their upstream."
exit 0
