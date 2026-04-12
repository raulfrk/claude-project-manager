---
name: setup
description: Set up the worktree plugin. Run this once to configure the default worktree directory and register base repositories. Use when the user says "set up worktrees", "configure worktree plugin", or "worktree setup".
allowed-tools: Read, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_add_repo, Bash
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Set up worktree plugin config.

Wizard uses **load-once pattern**: Step 0 reads `~/.claude/worktree.yaml` once, threads cur vals into each prompt as bracketed default. Enter keeps loaded val; typing overrides. First-run (no config) → hardcoded defaults.

**0.** Load existing config — `Read` `~/.claude/worktree.yaml`, parse w/ `yaml.safe_load`. Store as `worktree_config`. Any err (missing, read fail, parse fail) → `worktree_config = None`. Warn once on parse fail (not missing):
`"Warning: ~/.claude/worktree.yaml exists but could not be parsed (<error>). Using hardcoded defaults."`

**1.** Check existing config via `mcp__plugin_worktree_worktree__wt_list_repos`. Repos configured → ask reconfigure or add more. Reconfiguring: re-ask default dir (2a) w/ cur val as default; skip repo registration unless user requests.

**2.** Ask these questions (one at a time, defaults shown). Defaults: `(worktree_config or {}).get("<field>", <hardcoded>)`:

   a. `"Where should worktrees be created by default? [<worktree_config.default_worktree_dir or '~/worktrees'>]"`
      Confirmed → persist as `default_worktree_dir` in `~/.claude/worktree.yaml`.
   b. `"Would you like to register any base repositories now? (You can always add more later with /worktree:add-repo)"`

**3.** Each base repo:
   - Ask local path to git repo
   - Ask short label (e.g. "myapp", "backend", "docs")
   - Ask default branch (default: `main`)
   - `mcp__plugin_worktree_worktree__wt_add_repo` w/ provided vals

**4.** Confirm setup complete; show registered repos.

## Prerequisites

Worktree plugin MCP server must be running/reachable.

## Err Handling

- Already configured: ask reconfigure or add. Declined → keep existing.
- Worktree MCP unavailable: show err, stop.
- Invalid repo path: show err from `wt_add_repo`, ask diff path.

## Output

Setup confirmation + registered repos list.

Suggested next: `1. /worktree:create` -- create first worktree | `2. /worktree:add-repo` -- register another base repo
