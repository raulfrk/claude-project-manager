---
name: init-plugin
description: First-time setup wizard for the proj plugin. Run this before using any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
allowed-tools: mcp__proj__config_init, mcp__proj__config_load, mcp__proj__config_update, mcp__plugin_perms_perms__perms_batch_add_mcp_allow, mcp__plugin_perms_perms__perms_add_allow, mcp__plugin_perms_perms__perms_list, mcp__plugin_perms_perms__perms_set_sandbox_paths, mcp__plugin_perms_perms__perms_set_deny, Bash, mcp__proj__tracking_git_flush, mcp__plugin_hooks_hooks__hooks_list_tool
---

Set up the proj plugin. This is required before any other `/proj:*` command works.

**1.** Check if already configured with `mcp__proj__config_load`. If already configured, ask the user if they want to reconfigure. If the user declines, respond with "Existing configuration kept — no changes made." and stop.

**2.** Ask the following questions one at a time with defaults shown:

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
   h. **Team mode** — "Enable parallel agent execution for batch todos? [no]"
      - Explain: if enabled, batch operations can use multiple agents in parallel for faster execution
      - If yes: "Max agents? [4]"
        - Store as `team_mode_max_agents`; default to `4` if the user presses Enter
      - If yes: "Trust level? (0=supervised, 1=guided, 2=autonomous, 3=full-auto) [1]"
        - Explain: controls how much autonomy agents have — 0 requires approval for each action, 3 runs fully unattended
        - Store as `team_mode_trust_level`; default to `1` if the user presses Enter
   h2. **Default priority** — "Default priority for new todos? (low/medium/high) [medium]"
   h3. **Archive purge** — "How many days after archiving should purgeable projects be eligible for purge? Leave empty to never purge. [none]"
      - Store as `archive_purge_after_days` (None if left blank, integer if provided)
   i. **Plugins** — "Do you have the `perms` plugin installed? [no]"
   j. **Plugins** — "Do you have the `worktree` plugin installed? [no]"

**3.** Call `mcp__proj__config_init` with the collected values (including `auto_allow_mcps`, `projects_base_dir`, `zoxide_integration`, `archive_purge_after_days`, and `todoist_mcp_server` if Todoist is enabled). Omit `todoist_mcp_server` when `todoist_enabled: false`. If git tracking is enabled, also include `git_tracking_enabled`, `git_tracking_github_enabled`, and `git_tracking_github_repo_format`. If team mode is enabled, also include `team_mode_enabled`, `team_mode_max_agents`, and `team_mode_trust_level`.

**4.** If `perms` plugin is installed: build the server list and call `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` once:
   - Always include: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
   - If `auto_allow_mcps: true`, also include: `"plugin_proj_proj"`, `"plugin_perms_perms"`
   - If `auto_allow_mcps: true` and `worktree_integration: true`, also include: `"plugin_worktree_worktree"`
   - If `auto_allow_mcps: true` and `todoist.enabled: true`, also include: `todoist_mcp_server` (the value collected in step 2e, e.g. `"claude_ai_Todoist"`)
   - If `auto_allow_mcps: true` and `jira.enabled: true`, also include: `"jira"`
   - If `auto_allow_mcps: true` and `trello.enabled: true`, also include: `"trello"`
   - Call: `mcp__plugin_perms_perms__perms_batch_add_mcp_allow(servers=[<list>])`
   - If `zoxide_integration: true`, also call `mcp__plugin_perms_perms__perms_add_allow` with `entry="Bash(zoxide *)"` to allow zoxide commands without prompts.
   If `perms` plugin is not installed, skip silently and note: "Perms MCP server not available. Check your MCP server configuration and restart Claude Code."

**4a.** Integration verification (if `perms` plugin is installed):
   Call `mcp__plugin_perms_perms__perms_list` with `scope="user"` and `format="json"` to get the current rules.
   Parse the JSON result and extract `permissions_allow` from the user scope entry.

   - If `perms_integration: true`: check if any entry matching `mcp__plugin_perms_perms__*` exists in `permissions_allow`. If not, display:
     "Warning: `perms` plugin MCP rules not found in settings. The `perms_batch_add_mcp_allow` call may have failed. Re-run `/proj:init-plugin` to fix."
   - If `worktree_integration: true`: check if any entry matching `mcp__plugin_worktree_worktree__*` exists in `permissions_allow`. If not, display:
     "Warning: `worktree` plugin MCP rules not found in settings. Install the `worktree` plugin and re-run `/proj:init-plugin`."

   If the `perms_list` call fails (tool not available), skip with: "Perms MCP server not available. Check your MCP server configuration and restart Claude Code."

**4b.** **Sandbox root paths** (if `perms` plugin installed):
   - Compute `projects_root` from `projects_base_dir` value
   - Compute `tracking_root` from `tracking_dir` value
   - Compute `archive_destination` from `archive.destination` config value
   - Call `perms_set_sandbox_paths` with `paths=[projects_root, tracking_root, archive_destination]` and `preserve_extra=true`

**4c.** **Default deny rules** (if `perms` plugin installed):
   - Call `perms_set_deny` with the default deny rules list (from `DEFAULT_DENY_RULES` constant)

**4d.** **Persist root paths:**
   - Call `config_update` with `permissions_projects_root=<projects_root>` and `permissions_tracking_root=<tracking_root>`

**4e.** **Verify hooks server connectivity:**
   - Call `mcp__plugin_hooks_hooks__hooks_list_tool` to check if the hooks server is reachable.
   - If the call fails (tool not available or connection error), warn the user:
     "Warning: Hooks server is not reachable. You can check manually with `GET http://127.0.0.1:19100/health`."
     Offer two options: (1) Continue without hooks (2) Stop and fix.
     Do NOT hard-fail — if the user chooses to continue, proceed to step 5.
   - If reachable, proceed to step 4f.

**4f.** **Check default hooks exist** (only if hooks server is reachable):
   - Inspect the result from `mcp__plugin_hooks_hooks__hooks_list_tool`.
   - If no hooks are registered (empty list), warn:
     "Warning: No hooks registered. Restart Claude Code to trigger auto-discovery of hook definitions."
   - If hooks are registered, proceed to step 4g.

**4g.** **Validate hook condition paths** (only if hooks are registered):
   - Inspect the `condition` field of each returned hook for known mismatched config paths. Known fixes:
     - `todoist.enabled` should be `sync.todoist.enabled`
     - `todoist.auto_sync` should be `sync.todoist.auto_sync`
     - `trello.enabled` should be `sync.trello.enabled`
     - `trello.auto_sync` should be `sync.trello.auto_sync`
     - `zoxide.enabled` should be `zoxide_integration`
   - If any mismatched conditions are found, list them and offer to fix by editing `~/.claude/hooks.yaml` (update the condition paths to the correct values).
   - If no mismatches found, skip silently.

**5.** Confirm: "proj plugin configured! Configuration saved to `~/.claude/proj.yaml`"

**6.** Show the user their next step: "Run `/proj:init` to start tracking your first project."

## Prerequisites

- None (this is the first-time setup wizard).

## Error Handling

- **Already configured**: asks the user if they want to reconfigure. If declined, stops with `Existing configuration kept — no changes made.`
- **Config init failure**: displays error from `config_init` and stops.
- **Perms plugin not available**: skips permission setup silently with a note.
- **MCP rule verification failure**: displays warning about missing rules and suggests re-running.
- **Hooks server unreachable**: warns user with options to continue without hooks or stop and fix. Does not hard-fail.
- **No hooks registered**: warns user to restart Claude Code for auto-discovery.
- **Mismatched hook conditions**: lists affected hooks and offers to fix `~/.claude/hooks.yaml`.

## Output

Confirmation: `proj plugin configured! Configuration saved to ~/.claude/proj.yaml`. Next step guidance to run `/proj:init`.

Suggested next: `1. /proj:init` -- create your first project | `2. /proj:load` -- load an existing project
