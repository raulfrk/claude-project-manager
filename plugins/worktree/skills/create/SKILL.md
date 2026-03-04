---
name: create
description: Create a git worktree from a registered base repository. Use when the user says "create a worktree", "new worktree", or "worktree for branch X".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_list_repos, mcp__worktree__wt_create, mcp__perms__perms_add_allow
argument-hint: "[repo-label] [branch-name]"
---

Create a git worktree. Arguments: $ARGUMENTS (optional — repo label and/or branch name)

1. Call `mcp__worktree__wt_list_repos` to show available base repos.
   If the repo list is empty, stop: "No repos configured. Run /worktree:add-repo first."
2. If $ARGUMENTS provides repo label and branch, use those. Otherwise ask:
   - "Which repo? (label from the list above)"
   - "Branch name for the new worktree?"
   - "Create as a new branch? [yes/no, default: yes]"
   - "Custom path? [leave blank for default ~/worktrees/<repo>/<branch>]"
3. Call `mcp__worktree__wt_create` with the provided values.
   If it returns an error, display the error message and stop.
4. Call `mcp__perms__perms_add_allow` with the new worktree path to grant read/edit permissions.
   (If the perms server is unavailable, skip and continue.)
5. Show the created worktree path and confirm success.

💡 Suggested next:
(1) /worktree:list — see all worktrees
(2) /worktree:remove — remove a worktree when done
