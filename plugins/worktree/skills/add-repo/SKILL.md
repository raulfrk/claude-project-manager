---
name: add-repo
description: Register a new base git repository for worktree creation. Use when the user says "add repo", "register repo", or "add <path> as a base repo".
allowed-tools: mcp__plugin_worktree_worktree__wt_add_repo, mcp__plugin_worktree_worktree__wt_list_repos
argument-hint: "<path> [label] [default_branch]"
---

Register a new base git repository.

**1.** Parse $ARGUMENTS for label and/or path. Ask for any missing values:
   - "Label for this repo? (short identifier, e.g. 'myapp')"
   - "Path to the git repository?"
   - "Default branch? [main]"
**2.** Call `mcp__plugin_worktree_worktree__wt_add_repo` with `path=<path>`, `label=<label>`, `default_branch=<default_branch or "main">`.
   - If the path is not a git repository, stop with: "Path `<path>` is not a git repository. Verify the path contains a `.git` directory."
   - If the label is already registered, stop with: "Label `<label>` already registered. Run `/worktree:list` to see existing repos."
   - On any other MCP error: display the error message and stop.
**3.** Confirm registration and show updated repo list with `mcp__plugin_worktree_worktree__wt_list_repos`.

## Prerequisites

- Worktree plugin MCP server must be running and reachable.

## Error Handling

- **Not a git repository**: displays "Path `<path>` is not a git repository. Verify the path contains a `.git` directory." and stops.
- **Label already registered**: displays "Label `<label>` already registered. Run `/worktree:list` to see existing repos." and stops.
- **Worktree MCP unavailable**: displays error from tool call and stops.
- **Missing arguments**: asks interactively for path, label, and default branch.

## Output

Registration confirmation followed by the updated repo list.

Suggested next: `1. /worktree:create` -- create a worktree from this repo
