---
name: remove
description: Remove a git worktree. Use when the user says "remove worktree", "delete worktree", or "clean up worktree at <path>".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_list, mcp__worktree__wt_remove
argument-hint: "[path]"
---

Remove a git worktree.

1. If $ARGUMENTS provides a path, use it. Otherwise call `mcp__worktree__wt_list` and ask which worktree to remove.
2. Confirm with the user before removing: "Remove worktree at <path>? This cannot be undone."
3. Call `mcp__worktree__wt_remove` with the path. If it fails due to unclean state, ask the user if they want to force-remove.

💡 Suggested next:
(1) /worktree:list — verify the worktree was removed
(2) /worktree:prune — clean up any stale metadata
