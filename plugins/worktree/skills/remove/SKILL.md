---
name: remove
description: Remove a git worktree. Use when the user says "remove worktree", "delete worktree", or "clean up worktree at <path>".
allowed-tools: mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove
argument-hint: "[path]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Remove git worktree.

**1.** $ARGUMENTS has path → use it. Else `mcp__plugin_worktree_worktree__wt_list`, ask which.
**2.** Confirm: "Remove worktree at <path>? Cannot be undone."
**3.** `mcp__plugin_worktree_worktree__wt_remove` w/ path. Fails unclean → ask force-remove.

## Prerequisites

- Worktree plugin configured (≥1 worktree exists).
- Worktree MCP server running/reachable.

## Err Handling

- No path → list worktrees, ask user to select.
- Unclean state → ask force-remove or cancel.
- MCP unavailable → show err, stop.
- User declines → stop.

## Output

Confirm worktree removed.

Suggested next: `1. /worktree:list` -- verify removal | `2. /worktree:prune` -- clean stale metadata
