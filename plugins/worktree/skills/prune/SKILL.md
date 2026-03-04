---
name: prune
description: Prune stale git worktree admin files. Use when the user says "prune worktrees", "clean up stale worktrees".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_prune
argument-hint: "[repo-label]"
---

Prune stale worktree metadata.

Call `mcp__worktree__wt_prune` with the optional repo label from $ARGUMENTS (or prune all repos).
Show the results including what was cleaned up.
