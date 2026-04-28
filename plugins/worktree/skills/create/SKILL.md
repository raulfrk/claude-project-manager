---
name: create
description: Create a git worktree from a registered base repository. Use when the user says "create a worktree", "new worktree", or "worktree for branch X".
allowed-tools: mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_create, mcp__plugin_proj_proj__sandbox_sandbox_add_write_path
argument-hint: "[repo-label] [branch-name]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Create git worktree. Args: $ARGUMENTS (opt — repo label and/or branch name)

**1.** `mcp__plugin_worktree_worktree__wt_list_repos` → show available base repos.
 Empty list → stop: "No repos configured. Run `/worktree:add-repo` to register one."
**2.** $ARGUMENTS has repo label + branch → use those. Otherwise ask:
 - "Which repo? (label from list)"
 - "Branch name?"
 - "Create as new branch? [yes/no, default: yes]"
 - "Custom path? [blank for default ~/worktrees/<repo>/<branch>]"
**3.** `mcp__plugin_worktree_worktree__wt_create` w/ provided vals.
 Error → display msg, stop.
**4.** `mcp__plugin_proj_proj__sandbox_sandbox_add_write_path` w/ new worktree path for read/edit perms.
 Sandbox server unavailable → skip, continue.
**5.** Show created worktree path; confirm success.

## Prerequisites

- Worktree plugin configured (≥1 base repo registered)
- Worktree MCP server running + reachable

## Error Handling

- No repos → "No repos configured. Run `/worktree:add-repo` to register one." Stop.
- Create error → display `wt_create` error. Stop.
- Sandbox unavailable → skip perm grant, continue.
- Missing args → ask interactively for repo, branch, new branch flag, path.

## Output

Created worktree path + success confirmation. Perm grant status if needed.
Plugin venv-sync warnings surface in result msg when `sync_venvs_on_create` is enabled (worktree.yaml).

Suggested next: `1. /worktree:list` -- see all worktrees | `2. /worktree:remove` -- remove worktree when done
