---
name: add-repo
description: Register a new base git repository for worktree creation. Use when the user says "add repo", "register repo", or "add <path> as a base repo".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_add_repo, mcp__worktree__wt_list_repos
argument-hint: "[label] [path]"
---

Register a new base git repository.

1. Parse $ARGUMENTS for label and/or path. Ask for any missing values:
   - "Label for this repo? (short identifier, e.g. 'myapp')"
   - "Path to the git repository?"
   - "Default branch? [main]"
2. Call `mcp__worktree__wt_add_repo` with the values.
3. Confirm registration and show updated repo list with `mcp__worktree__wt_list_repos`.

💡 Suggested next:
(1) /worktree:create — create a worktree from this repo
