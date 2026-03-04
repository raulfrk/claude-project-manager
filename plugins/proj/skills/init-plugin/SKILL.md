---
name: init-plugin
description: First-time setup wizard for the proj plugin. Run this before using any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
disable-model-invocation: "true"
allowed-tools: mcp__proj__config_init, mcp__proj__config_load, Bash
---

Set up the proj plugin. This is required before any other `/proj:*` command works.

1. Check if already configured with `mcp__proj__config_load`. If already configured, ask the user if they want to reconfigure.

2. Ask the following questions one at a time with defaults shown:

   a. **Tracking directory** — "Where should project tracking data be stored? [~/projects/tracking]"
   a2. **Projects base directory** — "Default directory where project content lives (e.g. ~/projects)? Leave blank to skip."
      - Explain: if set, /proj:init will use `<base>/<project-name>` as the content path when no explicit path is given
      - Store as `projects_base_dir` (null if left blank)
   b. **Permissions** — "Allow Claude to freely act in project directories without permission prompts? [yes]"
      - Explain: if enabled, Claude will auto-add Read/Edit permissions for each project directory when you run /proj:init
      - Note: Requires the `perms` plugin to be installed; skipped silently if not available
   b2. **MCP auto-allow** — "Auto-allow plugin MCP tools so Claude never prompts for permission when calling them? [yes]"
      - Explain: adds `mcp__plugin_proj_proj__*`, `mcp__plugin_perms_perms__*`, `mcp__plugin_worktree_worktree__*` (and `mcp__claude_ai_Todoist__*` if Todoist enabled) to settings.json allow list immediately
      - Note: Requires the `perms` plugin; skipped silently if not available
   c. **Todoist sync** — "Enable Todoist sync? [no]"
      - If yes: "Auto-sync on every project command? [yes]"
      - If yes to Todoist: "What is the name of your Todoist MCP server? [claude_ai_Todoist]"
        - Explain: this must match the server key registered in your MCP config (e.g. `claude_ai_Todoist`); used to grant tool permissions and call Todoist APIs
        - Store as `todoist_mcp_server`; default to `"claude_ai_Todoist"` if the user presses Enter without typing
   d. **Git integration** — "Enable git integration? [yes]"
      - Explain: if enabled, /proj:update will detect recent commits and suggest todo updates
   e. **Default priority** — "Default priority for new todos? (low/medium/high) [medium]"
   f. **Plugins** — "Do you have the `perms` plugin installed? [no]"
   g. **Plugins** — "Do you have the `worktree` plugin installed? [no]"

3. Call `mcp__proj__config_init` with the collected values (including `auto_allow_mcps`, `projects_base_dir`, and `todoist_mcp_server` if Todoist is enabled). Omit `todoist_mcp_server` when `todoist_enabled: false`.

4. **If `perms` plugin is installed**: build the server list and call `mcp__perms__perms_batch_add_mcp_allow` once:
   - Always include: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
   - If `auto_allow_mcps: true`, also include: `"plugin_proj_proj"`, `"plugin_perms_perms"`
   - If `auto_allow_mcps: true` and `worktree_integration: true`, also include: `"plugin_worktree_worktree"`
   - If `auto_allow_mcps: true` and `todoist.enabled: true`, also include: `todoist_mcp_server` (the value collected in step 2c, e.g. `"claude_ai_Todoist"`)
   - Call: `mcp__perms__perms_batch_add_mcp_allow(servers=[<list>])`
   If `perms` plugin is not installed, skip silently and note: "perms plugin not found — add MCP allow rules manually if needed."

5. Confirm: "proj plugin configured! Configuration saved to ~/.claude/proj.yaml"

5. Show the user their next step: "Run /proj:init to start tracking your first project."

💡 Suggested next: (1) /proj:init — create your first project
