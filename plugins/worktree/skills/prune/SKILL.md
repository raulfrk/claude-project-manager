---
name: prune
description: Prune stale git worktree admin files. Use when the user says "prune worktrees", "clean up stale worktrees".
allowed-tools: mcp__plugin_worktree_worktree__wt_prune
argument-hint: "[repo-label]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Prune stale worktree metadata.

**1.** `$ARGUMENTS` has repo label → pass to `mcp__plugin_worktree_worktree__wt_prune`. No label → call w/ no label (prune all).
**2.** Success → list pruned worktrees: branch name + path each.
**3.** Nothing pruned → print: "No stale worktrees found."

## Prerequisites

- Worktree plugin configured (≥1 base repo registered).

## Err Handling

- Invalid repo label → "Repo label `<label>` not found. Run `/worktree:add-repo` to register one." Stop.
- Empty prune result → `No stale worktrees found.` Stop.
- MCP tool err → show err msg, suggest `git worktree prune` manually.

## Output

```
Pruned worktrees:
- <branch-name> — <path>
- <branch-name> — <path>
```

Suggested next: `1. /worktree:list` -- verify remaining worktrees
