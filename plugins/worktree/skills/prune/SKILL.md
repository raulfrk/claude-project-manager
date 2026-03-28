---
name: prune
description: Prune stale git worktree admin files. Use when the user says "prune worktrees", "clean up stale worktrees".
allowed-tools: mcp__plugin_worktree_worktree__wt_prune
argument-hint: "[repo-label]"
context: fork
agent: general-purpose
---

Prune stale worktree metadata.

**1.** If `$ARGUMENTS` contains a repo label, pass it to `mcp__plugin_worktree_worktree__wt_prune`. Otherwise call with no label to prune all repos.
**2.** On success, display the pruned worktrees as a list: branch name and path for each entry.
**3.** If no worktrees were pruned, print: "No stale worktrees found."

## Prerequisites

- Worktree plugin must be configured (at least one base repo registered).

## Error Handling

- **Invalid repo label**: displays "Repo label `<label>` not found. Run `/worktree:add-repo` to register one." and stops.
- **Empty prune result**: displays `No stale worktrees found.` and stops.
- **MCP tool error**: displays the error message and suggests running `git worktree prune` manually.

## Output

```
Pruned worktrees:
- <branch-name> — <path>
- <branch-name> — <path>
```

Suggested next: `1. /worktree:list` -- verify remaining worktrees
