---
name: list
description: List all git worktrees across configured base repositories. Use when the user says "list worktrees", "show worktrees", or "what worktrees do I have".
allowed-tools: mcp__plugin_worktree_worktree__wt_list
argument-hint: "[repo-label]"
context: fork
agent: general-purpose
---

List git worktrees.

**1.** Call `mcp__plugin_worktree_worktree__wt_list` with the optional repo label from $ARGUMENTS (or no filter to list all). Display the results clearly. For each worktree show: path, branch, HEAD SHA (short), and any status flags (locked, prunable).

If `wt_list` returns an error that the repo label was not found, stop with:
  "Repo label `<label>` not found. Run `/worktree:add-repo` to register one."

If the result is an empty list, print:
  "No worktrees found for <repo-label>." — if a label was given
  "No worktrees found." — if no label was given
  Stop.

## Prerequisites

- Worktree plugin must be configured (at least one base repo registered).

## Error Handling

- **Invalid repo label**: displays "Repo label `<label>` not found. Run `/worktree:add-repo` to register one." and stops.
- **Empty list**: displays `No worktrees found.` and stops.
- **Worktree MCP unavailable**: displays error from tool call and stops.

## Output

For each worktree: path, branch, HEAD SHA (short), and status flags (locked, prunable).

Suggested next: `1. /worktree:create` -- create a new worktree | `2. /worktree:prune` -- clean up stale worktrees
