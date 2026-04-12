---
name: add-repo
description: Register a new base git repository for worktree creation. Use when the user says "add repo", "register repo", or "add <path> as a base repo".
allowed-tools: mcp__plugin_worktree_worktree__wt_add_repo, mcp__plugin_worktree_worktree__wt_list_repos
argument-hint: "<path> [label] [default_branch]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Register new base git repo.

**1.** Parse $ARGUMENTS for label/path. Ask missing vals:
 - "Label for this repo? (short identifier, e.g. 'myapp')"
 - "Path to git repo?"
 - "Default branch? [main]"
**2.** `mcp__plugin_worktree_worktree__wt_add_repo` w/ `path=<path>`, `label=<label>`, `default_branch=<default_branch or "main">`.
 - Not git repo → stop: "Path `<path>` is not git repo. Verify path contains a `.git` dir."
 - Label exists → stop: "Label `<label>` already registered. Run `/worktree:list` to see existing repos."
 - Other MCP err → show err, stop.
**3.** Confirm registration; show updated repo list via `mcp__plugin_worktree_worktree__wt_list_repos`.

## Prerequisites

Worktree plugin MCP server running/reachable.

## Err Handling

- Not git repo → "Path `<path>` is not git repo. Verify path contains a `.git` dir." Stop.
- Label exists → "Label `<label>` already registered. Run `/worktree:list` to see existing repos." Stop.
- MCP unavailable → show tool err, stop.
- Missing args → ask interactively for path, label, default branch.

## Output

Registration confirmation + updated repo list.

Suggested next: `1. /worktree:create` -- create worktree from this repo
