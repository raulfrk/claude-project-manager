---
name: init-plugin
description: First-time setup wizard for the proj plugin. Run this before using any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
allowed-tools: mcp__proj__config_init, mcp__proj__config_load, mcp__proj__config_update, mcp__plugin_perms_perms__perms_batch_add_mcp_allow, mcp__plugin_perms_perms__perms_add_allow, mcp__plugin_perms_perms__perms_list, mcp__plugin_perms_perms__perms_set_sandbox_paths, mcp__plugin_perms_perms__perms_set_deny, mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_perms_perms__perms_sandbox_init, Bash, mcp__proj__tracking_git_flush, mcp__plugin_hooks_hooks__hooks_list_tool, mcp__plugin_hooks_hooks__hooks_register_tool
---

Set up the proj plugin. This is required before any other `/proj:*` command works.

## Step 1: Check existing configuration

Call `mcp__proj__config_load`. If already configured:
- Show all current values in a formatted summary
- Ask: "Reconfigure? [no]"
- If declined: respond with "Existing configuration kept — no changes made." and stop.

## Step 2: Detect installed plugins

Auto-detect which plugins are available by attempting to call their MCP tools. Do NOT ask the user whether plugins are installed — detect programmatically.

Check each plugin by calling a lightweight tool from its server:
- **perms**: call `mcp__plugin_perms_perms__perms_list` with `scope="user"` and `format="json"` — if it returns a result, perms is installed
- **worktree**: call `mcp__plugin_worktree_worktree__wt_list_repos` — if it returns a result, worktree is installed
- **hooks**: call `mcp__plugin_hooks_hooks__hooks_list_tool` — if it returns a result, hooks is installed
- **todoist**: call `mcp__plugin_todoist_todoist__todoist_find_projects` with `name=""` — if it returns a result (even empty), todoist plugin is installed
- **trello**: call `mcp__plugin_trello_trello__list_boards` — if it returns a result, trello is installed
- **jira**: call `mcp__plugin_jira_jira__jira_list_projects` — if it returns a result, jira is installed
- **zoxide**: call `mcp__plugin_zoxide_zoxide__zoxide_query` with `query=""` — if it returns a result, zoxide is installed

If a tool call fails (tool not found, connection error), that plugin is not installed. Continue silently.

Report the detection results:
```
Detected plugins: perms, worktree, hooks, todoist, zoxide
Not found: trello, jira
```

## Step 3: Collect configuration (grouped)

Present questions in logical groups. Within each group, show all questions together and collect answers as a batch. When reconfiguring, show the current value in brackets.

### Group A: Core paths
- **Tracking directory** — "Where should project tracking data be stored? [~/projects/tracking]"
  - Note: all projects share a single tracking repo at this path. Each project gets a subdirectory under it.
- **Projects base directory** — "Default directory where project content lives (e.g. ~/projects)? Leave blank to skip."
  - If set, `/proj:init` uses `<base>/<project-name>` as the content path when no explicit path is given.
  - Store as `projects_base_dir` (null if left blank)

### Group B: Permissions & sandbox (only if perms plugin detected)
- **Permissions** — "Auto-grant Claude read/edit permissions for project directories? [yes]"
  - If enabled, Claude auto-adds Read/Edit permissions for each project directory on `/proj:init`
- **MCP auto-allow** — "Auto-allow plugin MCP tools so Claude never prompts for permission? [yes]"
  - Adds wildcard MCP rules for all detected plugins to settings.json
- **Sandbox setup** — "Initialize sandbox mode for project directories? [yes]"
  - Sets up sandbox paths for projects root, tracking root, and archive destination
  - Adds default deny rules for security

### Group C: Sync integrations (only show for detected plugins)

For each detected sync plugin, ask its configuration questions as a sub-group:

**Todoist** (only if todoist plugin detected):
- "Enable Todoist sync? [no]"
- If yes: "Auto-sync on every project command? [yes]"
- If yes: "Todoist MCP server name (must match your MCP config)? [claude_ai_Todoist]"
  - Store as `todoist_mcp_server`

**Trello** (only if trello plugin detected):
- "Enable Trello sync? [no]"
- If yes: "Auto-sync on every project command? [yes]"
- If yes: "Default Trello board ID? (leave blank to set later)"
- If yes: "On delete action — archive or delete Trello cards? [archive]"

**Jira** (only if jira plugin detected):
- "Enable Jira sync? [no]"
- If yes: "Default Jira user (email or account ID)? (leave blank to set later)"

Skip sync sections entirely for plugins that are not detected.

### Group D: Git
- **Git integration** — "Enable git integration (detect commits, suggest todo updates)? [yes]"
- **Git tracking** — "Auto-commit tracking data (todos, notes, sessions) to the shared tracking repo? [no]"
  - All projects share a single git-tracked repo at the tracking directory path.
  - If yes: "Also push the tracking repo to GitHub as a private repo? [no]"
    - If yes: "GitHub repo name? [tracking]"
      - Store as `git_tracking_github_repo_format`

### Group E: Extras
- **Zoxide** (only if zoxide plugin detected) — "Enable zoxide integration (boost project dirs in frecency)? [no]"
- **Worktree** (only if worktree plugin detected) — shown as detected, no question needed (auto-enabled)
- **Team mode** — "Enable parallel agent execution for batch todos? [no]"
  - If yes: "Max agents? [4]" (store as `team_mode_max_agents`)
  - If yes: "Trust level? (0=supervised, 1=guided, 2=autonomous, 3=full-auto) [1]" (store as `team_mode_trust_level`)
- **Default priority** — "Default priority for new todos? (low/medium/high) [medium]"
- **Archive purge** — "Days after archiving before purgeable projects are eligible for purge? Leave empty for never. [none]"
  - Store as `archive_purge_after_days` (None if blank, integer if provided)

## Step 4: Show summary before applying

Before calling config_init, display a summary of all settings that will be applied:

```
Configuration summary:
  Core:
    tracking_dir: ~/projects/tracking
    projects_base_dir: ~/projects
  Detected plugins: perms, worktree, hooks, todoist, zoxide
  Permissions:
    auto_grant: yes
    auto_allow_mcps: yes
    sandbox: yes
  Sync:
    todoist: enabled (auto-sync, server: claude_ai_Todoist)
    trello: disabled (not installed)
    jira: disabled (not installed)
  Git:
    integration: yes
    tracking: no
  Extras:
    zoxide: yes
    worktree: yes
    team_mode: no
    default_priority: medium
    archive_purge: never

Apply this configuration? [yes]
```

If the user declines, return to step 3.

## Step 5: Apply configuration

Call `mcp__proj__config_init` with all collected values including:
- Core paths: `tracking_dir`, `projects_base_dir`
- Permissions: `auto_grant_permissions`, `auto_allow_mcps`
- Plugin flags: `perms_integration` (auto-set from detection), `worktree_integration` (auto-set from detection), `zoxide_integration`
- Sync: `todoist_enabled`, `todoist_auto_sync`, `todoist_mcp_server`, `trello_enabled`, `trello_auto_sync`, `trello_default_board_id`, `trello_on_delete`, `jira_enabled`, `jira_default_user`
- Git: `git_integration`, `git_tracking_enabled`, `git_tracking_github_enabled`, `git_tracking_github_repo_format`
- Extras: `team_mode_enabled`, `team_mode_max_agents`, `team_mode_trust_level`, `default_priority`, `archive_purge_after_days`

Omit `todoist_mcp_server` when `todoist_enabled: false`.

## Step 6: Permission setup (if perms plugin detected)

### 6a. MCP auto-allow
Build the server list and call `mcp__plugin_perms_perms__perms_batch_add_mcp_allow` once:
- Always include: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
- If `auto_allow_mcps: true`, also include: `"plugin_proj_proj"`, `"plugin_perms_perms"`
- If `auto_allow_mcps: true` and worktree detected: `"plugin_worktree_worktree"`
- If `auto_allow_mcps: true` and hooks detected: `"plugin_hooks_hooks"`
- If `auto_allow_mcps: true` and todoist enabled: the `todoist_mcp_server` value (e.g. `"claude_ai_Todoist"`) AND `"plugin_todoist_todoist"`
- If `auto_allow_mcps: true` and trello enabled: `"plugin_trello_trello"`
- If `auto_allow_mcps: true` and jira enabled: `"plugin_jira_jira"`
- If `auto_allow_mcps: true` and zoxide detected: `"plugin_zoxide_zoxide"`
- Call: `mcp__plugin_perms_perms__perms_batch_add_mcp_allow(servers=[<list>])`
- If `zoxide_integration: true`, also call `mcp__plugin_perms_perms__perms_add_allow` with `entry="Bash(zoxide *)"`.

### 6b. Verify MCP rules
Call `mcp__plugin_perms_perms__perms_list` with `scope="user"` and `format="json"`.
Parse `permissions_allow` from the result.
- If `perms_integration: true`: check for `mcp__plugin_perms_perms__*` — warn if missing
- If `worktree_integration: true`: check for `mcp__plugin_worktree_worktree__*` — warn if missing

### 6c. Sandbox setup
- Compute `projects_root` from `projects_base_dir`
- Compute `tracking_root` from `tracking_dir`
- Compute `archive_destination` from archive config
- Call `perms_set_sandbox_paths` with `paths=[projects_root, tracking_root, archive_destination]` and `preserve_extra=true`

### 6d. Default deny rules
- Call `perms_set_deny` with the default deny rules list (from `DEFAULT_DENY_RULES` constant)

### 6e. Persist root paths
- Call `config_update` with `permissions_projects_root=<projects_root>` and `permissions_tracking_root=<tracking_root>`

If perms plugin is not detected, skip all of step 6 with: "Perms plugin not detected — skipping permission and sandbox setup."

## Step 7: Hook setup (if hooks plugin detected)

### 7a. Verify hooks server connectivity
Call `mcp__plugin_hooks_hooks__hooks_list_tool` to check reachability.
- If unreachable: warn "Hooks server not reachable. You can check manually with `GET http://127.0.0.1:19100/health`."
  Offer: (1) Continue without hooks (2) Stop and fix.
  If user continues, skip to step 8.
- If reachable: proceed.

### 7b. Check and register default hooks
Inspect the hooks list result.
- If no hooks registered: warn "No hooks registered. Will attempt to register default hooks for detected plugins."

For each detected and enabled plugin, register its default hooks by calling `mcp__plugin_hooks_hooks__hooks_register_tool` for each hook entry from the plugin's `default-hooks.yaml`. Only register hooks whose conditions match enabled integrations:
- **proj** hooks: register if `git_tracking.enabled` (tracking flush hooks) or `perms_integration` (perms sync hook)
- **todoist** hooks: register if `todoist_enabled`
- **trello** hooks: register if `trello_enabled`
- **zoxide** hooks: register if `zoxide_integration`
- **worktree** hooks: register if `worktree_integration` (perms hooks) or `zoxide_integration` (zoxide hooks)
- **perms** hooks: register if `perms_integration`

Report how many hooks were registered: "Registered N default hooks for: proj, todoist, zoxide"

### 7c. Validate hook condition paths
Inspect the `condition` field of each registered hook. Known fixes:
- `todoist.enabled` should be `sync.todoist.enabled`
- `todoist.auto_sync` should be `sync.todoist.auto_sync`
- `trello.enabled` should be `sync.trello.enabled`
- `trello.auto_sync` should be `sync.trello.auto_sync`
- `zoxide.enabled` should be `zoxide_integration`

If mismatches found, list them and offer to fix by editing `~/.claude/hooks.yaml`.

If hooks plugin is not detected, skip all of step 7 with: "Hooks plugin not detected — skipping hook registration. Hooks enable automatic sync between plugins."

## Step 8: Confirmation

Display: "proj plugin configured! Configuration saved to `~/.claude/proj.yaml`"

Show a summary of what was set up:
```
Setup complete:
  Config: ~/.claude/proj.yaml
  Plugins: perms, worktree, hooks, todoist, zoxide
  MCP rules: 7 servers auto-allowed
  Sandbox: initialized (3 paths)
  Hooks: 12 registered
```

## Step 9: Next steps

"Run `/proj:init` to start tracking your first project."

Suggested next: `1. /proj:init` -- create your first project | `2. /proj:load` -- load an existing project

## Prerequisites

- None (this is the first-time setup wizard).

## Error Handling

- **Already configured**: shows current values, asks to reconfigure. If declined, stops.
- **Config init failure**: displays error from `config_init` and stops.
- **Plugin detection failure**: treats plugin as not installed, continues with others.
- **Perms plugin not detected**: skips all permission/sandbox setup with a note.
- **Hooks plugin not detected**: skips hook registration with a note.
- **Hooks server unreachable**: warns user with options to continue or stop.
- **No hooks registered**: attempts to register default hooks for detected plugins.
- **Mismatched hook conditions**: lists affected hooks and offers to fix.
- **MCP rule verification failure**: displays warning about missing rules.

## Output

Confirmation: `proj plugin configured! Configuration saved to ~/.claude/proj.yaml`. Summary of what was configured. Next step guidance to run `/proj:init`.
