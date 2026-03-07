---
name: list
description: List all git worktrees across configured base repositories. Use when the user says "list worktrees", "show worktrees", or "what worktrees do I have".
allowed-tools: mcp__plugin_worktree_worktree__wt_list
argument-hint: "[repo-label]"
---

List git worktrees.

Call `mcp__plugin_worktree_worktree__wt_list` with the optional repo label from $ARGUMENTS (or no filter to list all).

Display the results clearly. For each worktree show: path, branch, HEAD SHA (short), and any status flags (locked, prunable).

If `wt_list` returns an error that the repo label was not found, print:
  "Repo label '<label>' not found. Available labels: <list from config>"
  Stop.

If the result is an empty list, print:
  "No worktrees found for <repo-label>." — if a label was given
  "No worktrees found." — if no label was given
  Stop.

💡 Suggested next:
(1) /worktree:create — create a new worktree
(2) /worktree:prune — clean up stale worktrees
