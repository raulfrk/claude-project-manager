---
name: remove
description: Remove a git worktree. Use when the user says "remove worktree", "delete worktree", or "clean up worktree at <path>".
allowed-tools: mcp__plugin_worktree_worktree__wt_list, mcp__plugin_worktree_worktree__wt_remove
argument-hint: "[path]"
---

Remove a git worktree.

**1.** If $ARGUMENTS provides a path, use it. Otherwise call `mcp__plugin_worktree_worktree__wt_list` and ask which worktree to remove.
**2.** Confirm with the user before removing: "Remove worktree at <path>? This cannot be undone."
**3.** Call `mcp__plugin_worktree_worktree__wt_remove` with the path. If it fails due to unclean state, ask the user if they want to force-remove.

## Prerequisites

- Worktree plugin must be configured (at least one worktree must exist).
- Worktree MCP server must be running and reachable.

## Error Handling

- **No path provided**: lists worktrees and asks the user to select one.
- **Unclean state**: asks user to force-remove or cancel.
- **Worktree MCP unavailable**: displays error from tool call and stops.
- **User declines**: stops without removing.

## Output

Confirmation that the worktree was removed.

Suggested next: `1. /worktree:list` -- verify the worktree was removed | `2. /worktree:prune` -- clean up any stale metadata
