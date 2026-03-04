---
name: setup
description: Set up the worktree plugin. Run this once to configure the default worktree directory and register base repositories. Use when the user says "set up worktrees", "configure worktree plugin", or "worktree setup".
disable-model-invocation: "true"
allowed-tools: mcp__worktree__wt_list_repos, Bash
---

Set up the worktree plugin configuration.

1. Check if config already exists by calling `mcp__worktree__wt_list_repos`. If repos are already configured, ask the user if they want to reconfigure or just add more repos.

2. Ask the following questions (one at a time, with defaults shown):

   a. "Where should worktrees be created by default? [~/worktrees]"
   b. "Would you like to register any base repositories now? (You can always add more later with /worktree:add-repo)"

3. For each base repo the user wants to add:
   - Ask for the local path to the git repository
   - Ask for a short label (e.g. "myapp", "backend", "docs")
   - Ask for the default branch (default: main)
   - Call `mcp__worktree__wt_add_repo` with the provided values

4. Confirm setup is complete and show the registered repos.

💡 Suggested next:
(1) /worktree:create — create your first worktree
(2) /worktree:add-repo — register another base repository
