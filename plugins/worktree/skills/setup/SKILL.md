---
name: setup
description: Set up the worktree plugin. Run this once to configure the default worktree directory and register base repositories. Use when the user says "set up worktrees", "configure worktree plugin", or "worktree setup".
allowed-tools: Read, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__wt_add_repo, Bash
---

Set up the worktree plugin configuration.

This wizard uses a **load-once pattern**: at Step 0 it reads `~/.claude/worktree.yaml` once and threads the current values into each prompt as the bracketed default. Pressing Enter keeps the loaded value; typing a new value overrides it. On first-run (no config file), prompts fall back to hardcoded defaults.

**0.** **Load existing config** — Read `~/.claude/worktree.yaml` with the `Read` tool and parse with `yaml.safe_load`. Store the result as `worktree_config`. On any error (file missing, read failure, YAML parse failure), set `worktree_config = None`. Warn once per wizard run on parse failure (not on missing file):
`"Warning: ~/.claude/worktree.yaml exists but could not be parsed (<error>). Using hardcoded defaults."`

**1.** Check if config already exists by calling `mcp__plugin_worktree_worktree__wt_list_repos`. If repos are already configured, ask the user if they want to reconfigure or just add more repos. If reconfiguring: re-ask the default directory question (2a) with the current value shown as default; skip repo registration unless the user explicitly requests to add new repos.

**2.** Ask the following questions (one at a time, with defaults shown). Defaults are computed via `(worktree_config or {}).get("<field>", <hardcoded>)`:

   a. `"Where should worktrees be created by default? [<worktree_config.default_worktree_dir or '~/worktrees'>]"`
      After the user confirms the directory, persist it to worktree config as `default_worktree_dir` in `~/.claude/worktree.yaml`.
   b. `"Would you like to register any base repositories now? (You can always add more later with /worktree:add-repo)"`

**3.** For each base repo the user wants to add:
   - Ask for the local path to the git repository
   - Ask for a short label (e.g. "myapp", "backend", "docs")
   - Ask for the default branch (default: `main`)
   - Call `mcp__plugin_worktree_worktree__wt_add_repo` with the provided values

**4.** Confirm setup is complete and show the registered repos.

## Prerequisites

- Worktree plugin MCP server must be running and reachable.

## Error Handling

- **Already configured**: asks user to reconfigure or add repos. If declined, keeps existing config.
- **Worktree MCP unavailable**: displays error from tool call and stops.
- **Invalid repo path**: displays error from `wt_add_repo` and asks for a different path.

## Output

Setup confirmation and list of registered repos.

Suggested next: `1. /worktree:create` -- create your first worktree | `2. /worktree:add-repo` -- register another base repository
