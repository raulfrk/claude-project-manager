---
name: add-repo
description: Register a new base git repository for worktree creation. Use when the user says "add repo", "register repo", or "add <path> as a base repo".
disable-model-invocation: "true"
allowed-tools: mcp__plugin_worktree_worktree__wt_add_repo, mcp__plugin_worktree_worktree__wt_list_repos
argument-hint: "<path> [label] [default_branch]"
---

Register a new base git repository.

1. Parse $ARGUMENTS for label and/or path. Ask for any missing values:
   - "Label for this repo? (short identifier, e.g. 'myapp')"
   - "Path to the git repository?"
   - "Default branch? [main]"
2. Call `mcp__plugin_worktree_worktree__wt_add_repo` with `path=<path>`, `label=<label>`, `default_branch=<default_branch or "main">`.
   - If the path is not a git repository: output "Path '<path>' is not a git repository." and stop.
   - If the label is already registered: output "Label '<label>' already registered. Choose a different label." and stop.
   - On any other MCP error: display the error message and stop.
3. Confirm registration and show updated repo list with `mcp__plugin_worktree_worktree__wt_list_repos`.

💡 Suggested next:
(1) /worktree:create — create a worktree from this repo
