---
name: list
description: List all git worktrees across configured base repositories. Use when the user says "list worktrees", "show worktrees", or "what worktrees do I have".
allowed-tools: mcp__plugin_worktree_worktree__wt_list
argument-hint: "[repo-label]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List git worktrees.

**1.** `mcp__plugin_worktree_worktree__wt_list` w/ opt repo label from $ARGUMENTS (or no filter). Each worktree: path, branch, HEAD SHA (short), status flags (locked, prunable).

`wt_list` err repo not found → "Repo label `<label>` not found. Run `/worktree:add-repo` to register one."

Empty list → "No worktrees found for <repo-label>." (label given) or "No worktrees found." (no label). Stop.

## Prerequisites

Worktree plugin configured (≥1 base repo registered).

## Err Handling

- Invalid repo label → "Repo label `<label>` not found. Run `/worktree:add-repo` to register one." Stop.
- Empty list → "No worktrees found." Stop.
- Worktree MCP unavailable → show err, stop.

## Output

Each worktree: path, branch, HEAD SHA (short), status flags (locked, prunable).

Suggested next: `1. /worktree:create` -- create new worktree | `2. /worktree:prune` -- clean up stale worktrees
