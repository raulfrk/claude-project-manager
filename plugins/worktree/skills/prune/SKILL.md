---
name: prune
description: Prune stale git worktree admin files. Use when the user says "prune worktrees", "clean up stale worktrees".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_prune
argument-hint: "[repo-label]"
---

Prune stale worktree metadata.

## Steps

1. If `$ARGUMENTS` contains a repo label, pass it to `mcp__worktree__wt_prune`. Otherwise call with no label to prune all repos.
2. On success, display the pruned worktrees as a list: branch name and path for each entry.
3. If no worktrees were pruned, print: "No stale worktrees found."

## Failure Paths

- **Invalid repo label**: print `"Repo label '<label>' not found. Use /worktree:list to see available repos."` and stop.
- **Empty prune result**: print `"No stale worktrees found."` and stop.
- **MCP tool error**: display the error message and suggest: `"Run \`git worktree prune\` manually to clean up stale entries."`

## Output Format

```
Pruned worktrees:
- <branch-name> — <path>
- <branch-name> — <path>
```

## Suggested next

`/worktree:list — verify remaining worktrees`
