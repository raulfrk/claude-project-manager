---
name: init-plugin
description: First-time setup wizard for the proj plugin. Run this before using any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
disable-model-invocation: "true"
allowed-tools: mcp__proj__config_init, mcp__proj__config_load, mcp__plugin_perms_perms__perms_batch_add_mcp_allow, mcp__plugin_perms_perms__perms_add_allow, Bash, mcp__proj__tracking_git_flush
---

Set up the proj plugin. This is required before any other `/proj:*` command works.

1. Check if already configured with `mcp__proj__config_load`. If already configured, ask the user if they want to reconfigure. If the user declines, respond with "Existing configuration kept — no changes made." and stop.

2. Ask the following questions one at a time with defaults shown:

   a. **Tracking directory** — "Where should project tracking data be stored? [~/projects/tracking]"
   b. **Projects base directory** — "Default directory where project content lives (e.g. ~/projects)? Leave blank to skip."
      - Explain: if set, /proj:init will use `<base>/<project-name>` as the content path when no explicit path is given
      - Store as `projects_base_dir` (null if left blank)
   c. **Permissions** — "Allow Claude to freely act in project directories without permission prompts? [yes]"
      - Explain: if enabled, Claude will auto-add Read/Edit permissions for each project directory when you run /proj:init
      - Note: Requires the `perms` plugin to be installed; skipped silently if not available
   d. **MCP auto-allow** — "Auto-allow plugin MCP tools so Claude never prompts for permission when calling them? [yes]"
      - Explain: adds `mcp__plugin_proj_proj__*`, `mcp__plugin_perms_perms__*`, `mcp__plugin_worktree_worktree__*` (and `mcp__claude_ai_Todoist__*` if Todoist enabled) to settings.json allow list immediately
      - Note: Requires the `perms` plugin; skipped silently if not available
   e. **Todoist sync** — "Enable Todoist sync? [no]"
      - If yes: "Auto-sync on every project command? [yes]"
      - If yes to Todoist: "What is the name of your Todoist MCP server? [claude_ai_Todoist]"
        - Explain: this must match the server key registered in your MCP config (e.g. `claude_ai_Todoist`); used to grant tool permissions and call Todoist APIs
        - Store as `todoist_mcp_server`; default to `"claude_ai_Todoist"` if the user presses Enter without typing
   f. **Git integration** — "Enable git integration? [yes]"
      - Explain: if enabled, /proj:save will detect recent commits and suggest todo updates
   f2. **Git tracking** — "Auto-commit project tracking data (todos, notes, sessions) with git? [no]"
      - Explain: if enabled, a git repo is created in each project's tracking directory and changes are auto-committed after each skill invocation
      - If yes: "Also push tracking repos to GitHub as private repos? [no]"
        - If yes: "GitHub repo name format? [tracking-{project-name}]"
          - Explain: `{project-name}` is replaced with the project name (e.g. project "my-app" → repo "tracking-my-app")
          - Store as `git_tracking_github_repo_format`; default to `"tracking-{project-name}"` if the user presses Enter
   g. **Zoxide integration** — "Enable zoxide integration? [no]"
      - Explain: if enabled, project directories are boosted in zoxide's frecency database on init/load for faster `cd` navigation
   h. **Default priority** — "Default priority for new todos? (low/medium/high) [medium]"
   i. **Plugins** — "Do you have the `perms` plugin installed? [no]"
   j. **Plugins** — "Do you have the `worktree` plugin installed? [no]"

3. Call `mcp__proj__config_init` with the collected values (including `auto_allow_mcps`, `projects_base_dir`, `zoxide_integration`, and `todoist_mcp_server` if Todoist is enabled). Omit `todoist_mcp_server` when `todoist_enabled: false`. If git tracking is enabled, also include `git_tracking_enabled`, `git_tracking_github_enabled`, and `git_tracking_github_repo_format`.

4. **If `perms` plugin is installed**: build the server list and call `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` once:
   - Always include: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
   - If `auto_allow_mcps: true`, also include: `"plugin_proj_proj"`, `"plugin_perms_perms"`
   - If `auto_allow_mcps: true` and `worktree_integration: true`, also include: `"plugin_worktree_worktree"`
   - If `auto_allow_mcps: true` and `todoist.enabled: true`, also include: `todoist_mcp_server` (the value collected in step 2e, e.g. `"claude_ai_Todoist"`)
   - Call: `mcp__plugin_perms_perms__perms_batch_add_mcp_allow(servers=[<list>])`
   - If `zoxide_integration: true`, also call `mcp__plugin_perms_perms__perms_add_allow` with `entry="Bash(zoxide *)"` to allow zoxide commands without prompts.
   If `perms` plugin is not installed, skip silently and note: "perms plugin not found — add MCP allow rules manually if needed."

5. Confirm: "proj plugin configured! Configuration saved to ~/.claude/proj.yaml"

6. Show the user their next step: "Run /proj:init to start tracking your first project."

💡 Suggested next: (1) /proj:init — create your first project | (2) /proj:load — load an existing project
