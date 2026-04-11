---
name: init-plugin
description: First-time setup wizard for the proj plugin. Run this before using any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
allowed-tools: Read, mcp__proj__config_init, mcp__proj__config_load, mcp__proj__config_update, mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow, mcp__plugin_sandbox_sandbox__sandbox_add_write_path, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_set_deny, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, Bash, mcp__proj__tracking_git_flush, mcp__plugin_router_router__router_list_tool, mcp__plugin_router_router__router_register_tool, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_todoist_todoist__todoist_find_projects, mcp__plugin_trello_trello__list_boards, mcp__plugin_jira_jira__jira_list_projects, mcp__plugin_zoxide_zoxide__zoxide_query, mcp__plugin_trello_trello__trello_init, mcp__plugin_jira_jira__jira_init, mcp__plugin_todoist_todoist__todoist_init
---

Set up the proj plugin. This is required before any other `/proj:*` command works.

This wizard uses a **load-once pattern**: at Step 0 it reads every relevant config file into named variables, and each subsequent prompt shows the current value from that variable as its bracketed default. Press Enter to keep the existing value; type to override. On first-run (no config files), prompts fall back to hardcoded defaults.

## Step 0: Load existing config files

Before any prompting, load every config file the wizard will reference. Each file is loaded once into a named variable; later steps reference these variables for their default values.

Initialize a top-of-skill tracking set:

```
warnings_emitted = set()    # tracks which files have already warned — prevents duplicate warnings
```

Load each config file with the following pattern (use the `Read` tool on the absolute path, then parse with `yaml.safe_load`). On any error (file missing, read failure, YAML parse failure), set the variable to `None`. Only warn once per file — check `warnings_emitted` before printing, then add the filename to the set.

1. **proj_config** — Read `~/.claude/proj.yaml`:
   - If the file does not exist → `proj_config = None` (silent; first-run is expected)
   - If the file exists but fails to parse → `proj_config = None` and warn once:
     `"Warning: ~/.claude/proj.yaml exists but could not be parsed (<error>). Using hardcoded defaults for proj fields."`
2. **todoist_config** — Read `~/.claude/todoist.yaml`:
   - Missing → `todoist_config = None` (silent)
   - Parse failure → `todoist_config = None` and warn once with the same pattern
3. **trello_config** — Read `~/.claude/trello.yaml`: same pattern, store as `trello_config`
4. **jira_config** — Read `~/.claude/jira.yaml`: same pattern, store as `jira_config`
5. **sandbox_state** — Call `mcp__plugin_sandbox_sandbox__sandbox_list` with `scope="user"` and `format="json"`:
   - On success → parse JSON, store as `sandbox_state`
   - On failure (tool unavailable, sandbox plugin not installed) → `sandbox_state = None` (silent; plugin detection in Step 2 handles the "not installed" case)

After this step, every prompt in Steps 3, 4, and 7 reads its default from the matching loaded variable via safe nested access (`(proj_config or {}).get("tracking_dir", "~/projects/tracking")` style). If the variable is `None` or the field is missing, fall back to the hardcoded default specified in the prompt.

**Masking helper** (used in Step 3 for credential fields):

```
def mask_secret(value):
    if not value:
        return "[not set]"
    if len(value) < 8:
        return "****"
    return f"****{value[-4:]}"
```

Non-sensitive fields (trello.api_key, jira.base_url, jira.default_user, jira.default_project) are shown raw, not masked.

## Step 1: Check existing configuration

Call `mcp__proj__config_load`. If already configured:
- Show all current values in a formatted summary
- Ask: "Reconfigure? [no]"
- If declined: respond with "Existing configuration kept — no changes made." and stop.

## Step 2: Detect installed plugins

Auto-detect which plugins are available by attempting to call their MCP tools. Do NOT ask the user whether plugins are installed — detect programmatically.

Check each plugin by calling a lightweight tool from its server:
- **sandbox**: call `mcp__plugin_sandbox_sandbox__sandbox_list` with `scope="user"` and `format="json"` — if it returns a result, sandbox is installed
- **worktree**: call `mcp__plugin_worktree_worktree__wt_list_repos` — if it returns a result, worktree is installed
- **router**: call `mcp__plugin_router_router__router_list_tool` — if it returns a result, router is installed
- **todoist**: call `mcp__plugin_todoist_todoist__todoist_find_projects` with `name=""` — if it returns a result (even empty), todoist plugin is installed
- **trello**: call `mcp__plugin_trello_trello__list_boards` — if it returns a result, trello is installed
- **jira**: call `mcp__plugin_jira_jira__jira_list_projects` — if it returns a result, jira is installed
- **zoxide**: call `mcp__plugin_zoxide_zoxide__zoxide_query` with `query=""` — if it returns a result, zoxide is installed

If a tool call fails (tool not found, connection error), that plugin is not installed. Continue silently.

Report the detection results:
```
Detected plugins: sandbox, worktree, hooks, todoist, zoxide
Not found: trello, jira
```

## Step 3: Plugin Credential Setup

For each detected plugin that requires credentials, prompt using the values loaded in Step 0 as defaults. Each credential field is shown per its **per-field masking policy**: sensitive fields (any `*_token`, `api_token`, `personal_access_token`) are displayed as `****<last4>` if ≥ 8 chars, `****` if shorter, and `[not set]` when absent. Non-sensitive fields (trello.api_key, jira.base_url, jira.default_user, jira.default_project) are shown raw.

Masking is applied inline using the `mask_secret()` helper defined in Step 0. Pressing Enter at a prompt keeps the existing value unchanged (no re-init call needed); typing a new value overrides it and triggers the init call.

This phase is non-blocking — if a plugin is not detected or the user skips it, continue to the next.

### Trello (only if trello detected in Step 2)

Use `trello_config` loaded in Step 0.

1. Compute displays:
   - `key_display = trello_config.get("api_key", "") if trello_config else ""` → shown **raw** (non-sensitive; Trello API keys are board-level identifiers)
   - `token_display = mask_secret(trello_config.get("token", "")) if trello_config else "[not set]"`
2. If both fields are present and non-empty, optionally short-circuit: show `"Trello: ✓ credentials configured (key: <key_display>, token: <token_display>)"` and ask `"Reconfigure Trello credentials? [no]"`. If no → skip.
3. Otherwise prompt:
   - `"Trello API key? [<key_display or 'required'>]"` — Enter keeps current, typing overrides
   - `"Trello API token? [<token_display>]"` — Enter keeps current masked value, typing overrides (validate the new value is ≥ 8 chars before calling init)
4. If either value changed, call `mcp__plugin_trello_trello__trello_init` with the final `api_key` and `token`
5. If the init call returns an error → show the error and continue (do not block setup)
6. If successful → show `"Trello: ✓ credentials saved to ~/.claude/trello.yaml"`

### Jira (only if jira detected in Step 2)

Use `jira_config` loaded in Step 0.

1. Compute displays:
   - `base_url_display = jira_config.get("base_url", "") if jira_config else ""` → shown **raw**
   - `token_display = mask_secret(jira_config.get("personal_access_token", "")) if jira_config else "[not set]"`
   - `user_display = jira_config.get("default_user", "") if jira_config else ""` → shown **raw**
   - `project_display = jira_config.get("default_project", "") if jira_config else ""` → shown **raw**
2. If `base_url` and `personal_access_token` are both present and non-empty, optionally short-circuit: show `"Jira: ✓ credentials configured (base_url: <base_url_display>, token: <token_display>)"` and ask `"Reconfigure Jira credentials? [no]"`. If no → skip.
3. Otherwise prompt:
   - `"Jira base URL? (e.g. https://yourcompany.atlassian.net) [<base_url_display or 'required'>]"`
   - `"Jira personal access token? [<token_display>]"` — Enter keeps current, typing overrides
   - `"Jira default user (email or account ID)? [<user_display or 'optional'>]"`
   - `"Jira default project? [<project_display or 'optional'>]"`
4. If `base_url` or `personal_access_token` changed, call `mcp__plugin_jira_jira__jira_init` with the final `base_url` and `personal_access_token`
5. If the init call returns an error → show the error and continue (do not block setup)
6. If successful → show `"Jira: ✓ credentials saved to ~/.claude/jira.yaml"`

### Todoist (only if todoist detected in Step 2)

Use `todoist_config` loaded in Step 0.

1. Compute display:
   - `token_display = mask_secret(todoist_config.get("api_token", "")) if todoist_config else "[not set]"`
2. If `api_token` is present and non-empty, optionally short-circuit: show `"Todoist: ✓ credentials configured (token: <token_display>)"` and ask `"Reconfigure Todoist credentials? [no]"`. If no → skip.
3. Otherwise prompt:
   - `"Todoist API token? [<token_display>]"` — Enter keeps current masked value, typing overrides
4. If the value changed, call `mcp__plugin_todoist_todoist__todoist_init` with the final `api_token`
5. If the init call returns an error → show the error and continue (do not block setup)
6. If successful → show `"Todoist: ✓ credentials saved to ~/.claude/todoist.yaml"`

If no sync plugins were detected, skip this step entirely.

## Step 4: Collect configuration (grouped)

Present questions in logical groups. Within each group, show all questions together and collect answers as a batch. Every prompt's bracketed default is computed from the `proj_config` variable loaded in Step 0 — if the field is present, show the loaded value; otherwise show the hardcoded default shown in parentheses below. Use safe nested access: `(proj_config or {}).get("field", <hardcoded_default>)`. Boolean fields render as `[yes]`/`[no]`. Missing files or missing fields fall through to the hardcoded default.

If a field's current value is a path that does not exist on disk, append ` (not found)` to the bracketed default as a subtle warning (e.g., `[~/custom/tracking (not found)]`).

### Group A: Core paths
- **Tracking directory** — `"Where should project tracking data be stored? [<proj_config.tracking_dir or '~/projects/tracking'>]"`
  - Note: all projects share a single tracking repo at this path. Each project gets a subdirectory under it.
- **Projects base directory** — `"Default directory where project content lives (e.g. ~/projects)? [<proj_config.projects_base_dir or 'blank to skip'>]"`
  - If set, `/proj:init` uses `<base>/<project-name>` as the content path when no explicit path is given.
  - Store as `projects_base_dir` (null if left blank)

### Group B: Permissions & sandbox (only if sandbox plugin detected)
- **Permissions** — `"Auto-grant Claude read/edit permissions for project directories? [<yes/no from proj_config.auto_grant_permissions, default yes>]"`
  - If enabled, Claude auto-adds Read/Edit permissions for each project directory on `/proj:init`
- **MCP auto-allow** — `"Auto-allow plugin MCP tools so Claude never prompts for permission? [<yes/no from proj_config.auto_allow_mcps, default yes>]"`
  - Adds wildcard MCP rules for all detected plugins to settings.json
- **Sandbox setup** — `"Initialize sandbox mode for project directories? [<yes/no from proj_config.sandbox_integration, default yes>]"`
  - Sets up sandbox paths for projects root, tracking root, and archive destination
  - Adds default deny rules for security

### Group C: Sync integrations (only show for detected plugins)

For each detected sync plugin, ask its configuration questions as a sub-group. Sync enabled/auto-sync flags and nested fields are read from `proj_config.sync.<plugin>.*` via safe nested traversal (`(proj_config or {}).get("sync", {}).get("todoist", {}).get("enabled", False)`).

**Todoist** (only if todoist plugin detected):
- `"Enable Todoist sync? [<yes/no from proj_config.sync.todoist.enabled, default no>]"`
- If yes: `"Auto-sync on every project command? [<yes/no from proj_config.sync.todoist.auto_sync, default yes>]"`
- If yes: `"Todoist MCP server name (must match your MCP config)? [<proj_config.sync.todoist.mcp_server or 'claude_ai_Todoist'>]"`
  - Store as `todoist_mcp_server`

**Trello** (only if trello plugin detected):
- `"Enable Trello sync? [<yes/no from proj_config.sync.trello.enabled, default no>]"`
- If yes: `"Auto-sync on every project command? [<yes/no from proj_config.sync.trello.auto_sync, default yes>]"`
- If yes: `"Default Trello board ID? [<proj_config.sync.trello.default_board_id or 'blank to set later'>]"`
- If yes: `"On delete action — archive or delete Trello cards? [<proj_config.sync.trello.on_delete or 'archive'>]"`
- If yes: `"Trello projects list name? [<proj_config.sync.trello.list_projects or 'Projects'>]"` — the Trello list where project cards are created. Empty input uses the shown default.
- If yes: `"Trello tasks list name? [<proj_config.sync.trello.list_tasks or 'proj-tasks'>]"` — the Trello list where standalone task cards are created. Empty input uses the shown default.

**Jira** (only if jira plugin detected):
- `"Enable Jira sync? [<yes/no from proj_config.sync.jira.enabled, default no>]"`
- If yes: `"Default Jira user (email or account ID)? [<proj_config.sync.jira.default_user or 'blank to set later'>]"`

Skip sync sections entirely for plugins that are not detected.

### Group D: Git
- **Git integration** — `"Enable git integration (detect commits, suggest todo updates)? [<yes/no from proj_config.git_integration, default yes>]"`
- **Git tracking** — `"Auto-commit tracking data (todos, notes, sessions) to the shared tracking repo? [<yes/no from proj_config.git_tracking.enabled, default no>]"`
  - All projects share a single git-tracked repo at the tracking directory path.
  - If yes: `"Also push the tracking repo to GitHub as a private repo? [<yes/no from proj_config.git_tracking.github_enabled, default no>]"`
    - If yes: `"GitHub repo name? [<proj_config.git_tracking.github_repo_format or 'tracking'>]"`
      - Store as `git_tracking_github_repo_format`

### Group E: Extras
- **Zoxide** (only if zoxide plugin detected) — `"Enable zoxide integration (boost project dirs in frecency)? [<yes/no from proj_config.zoxide_integration, default no>]"`
- **Worktree** (only if worktree plugin detected) — shown as detected, no question needed (auto-enabled)
- **Team mode** — `"Enable parallel agent execution for batch todos? [<yes/no from proj_config.team_mode.enabled, default no>]"`
  - If yes: `"Max agents? [<proj_config.team_mode.max_agents or 30>]"` (store as `team_mode_max_agents`). Recommended cap: 10 for CPU-bound or API-rate-limited workloads; the hard default is 30.
  - If yes: `"Trust level? (0=supervised, 1=guided, 2=autonomous, 3=full-auto) [<proj_config.team_mode.trust_level or 1>]"` (store as `team_mode_trust_level`)
- **Default priority** — `"Default priority for new todos? (low/medium/high) [<proj_config.default_priority or 'medium'>]"`
  - If the loaded value is not one of low/medium/high, warn and use 'medium' as the default.
- **Archive purge** — `"Days after archiving before purgeable projects are eligible for purge? Leave empty for never. [<proj_config.archive.purge_after_days or 'none'>]"`
  - Store as `archive_purge_after_days` (None if blank, integer if provided)

## Step 5: Show summary before applying

Before calling config_init, display a summary of all settings that will be applied:

```
Configuration summary:
  Core:
    tracking_dir: ~/projects/tracking
    projects_base_dir: ~/projects
  Detected plugins: sandbox, worktree, hooks, todoist, zoxide
  Permissions:
    auto_grant: yes
    auto_allow_mcps: yes
    sandbox: yes
  Sync:
    todoist: enabled (auto-sync, server: claude_ai_Todoist)
    trello: disabled (not installed)  [or: enabled (auto-sync, board: <id>, on_delete: archive, projects_list: Projects, tasks_list: proj-tasks)]
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

If the user declines, return to step 4.

## Step 6: Apply configuration

Call `mcp__proj__config_init` with all collected values including:
- Core paths: `tracking_dir`, `projects_base_dir`
- Permissions: `auto_grant_permissions`, `auto_allow_mcps`
- Plugin flags: `sandbox_integration` (auto-set from detection), `worktree_integration` (auto-set from detection), `zoxide_integration`
- Sync: `todoist_enabled`, `todoist_auto_sync`, `todoist_mcp_server`, `trello_enabled`, `trello_auto_sync`, `trello_default_board_id`, `trello_on_delete`, `trello_list_projects`, `trello_list_tasks`, `jira_enabled`, `jira_default_user`
- Git: `git_integration`, `git_tracking_enabled`, `git_tracking_github_enabled`, `git_tracking_github_repo_format`
- Extras: `team_mode_enabled`, `team_mode_max_agents`, `team_mode_trust_level`, `default_priority`, `archive_purge_after_days`

Omit `todoist_mcp_server` when `todoist_enabled: false`.

## Step 7: Permission setup (if sandbox plugin detected)

This step uses `sandbox_state` loaded in Step 0 to detect which MCP rules, write paths, and batch-setup paths already exist, so the wizard can report idempotent no-ops instead of silently re-applying. If `sandbox_state` is `None` (load failed or stale), re-fetch via `sandbox_list` before proceeding.

Compute the existing-rules view once:
```
existing_allow = set(sandbox_state.get("permissions_allow", [])) if sandbox_state else set()
existing_write = set(sandbox_state.get("write_paths", [])) if sandbox_state else set()
```

### 7a. MCP auto-allow
Build the server list and call `mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow` once:
- Always include: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
- If `auto_allow_mcps: true`, also include: `"plugin_proj_proj"`, `"plugin_sandbox_sandbox"`
- If `auto_allow_mcps: true` and worktree detected: `"plugin_worktree_worktree"`
- If `auto_allow_mcps: true` and router detected: `"plugin_router_router"`
- If `auto_allow_mcps: true` and todoist enabled: the `todoist_mcp_server` value (e.g. `"claude_ai_Todoist"`) AND `"plugin_todoist_todoist"`
- If `auto_allow_mcps: true` and trello enabled: `"plugin_trello_trello"`
- If `auto_allow_mcps: true` and jira enabled: `"plugin_jira_jira"`
- If `auto_allow_mcps: true` and zoxide detected: `"plugin_zoxide_zoxide"`
- Before calling, filter out servers whose wildcard rule `f"mcp__{server}__*"` is already in `existing_allow` — report each skipped rule as `"<rule> already present, skipping"`. Call `mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow(servers=[<filtered list>])` only if the filtered list is non-empty.
- If `zoxide_integration: true` and `"Bash(zoxide *)"` is not in `existing_allow`, call `mcp__plugin_sandbox_sandbox__sandbox_add_write_path` with `entry="Bash(zoxide *)"`.

### 7b. Verify MCP rules
Re-read sandbox state via `mcp__plugin_sandbox_sandbox__sandbox_list` with `scope="user"` and `format="json"` (fresh read, since 7a may have mutated it).
Parse `permissions_allow` from the result.
- If `sandbox_integration: true`: check for `mcp__plugin_sandbox_sandbox__*` — warn if missing
- If `worktree_integration: true`: check for `mcp__plugin_worktree_worktree__*` — warn if missing

### 7c. Sandbox setup
- Compute `projects_root` from `projects_base_dir` (default from `sandbox_state` if present, else from newly-entered value)
- Compute `tracking_root` from `tracking_dir`
- Compute `archive_destination` from archive config
- Call `sandbox_batch_setup` with `paths=[projects_root, tracking_root, archive_destination]` and `preserve_extra=true`. The tool is idempotent — paths already configured are no-ops.

### 7d. Default deny rules
- Call `sandbox_set_deny` with the default deny rules list (from `DEFAULT_DENY_RULES` constant)

### 7e. Persist root paths
- Call `config_update` with `permissions_projects_root=<projects_root>` and `permissions_tracking_root=<tracking_root>`

If sandbox plugin is not detected, skip all of step 7 with: "Sandbox plugin not detected — skipping permission and sandbox setup."

## Step 8: Hook setup (if router plugin detected)

### 8a. Verify router server connectivity
Call `mcp__plugin_router_router__router_list_tool` to check reachability.
- If unreachable: warn "Router server not reachable. You can check manually with `GET http://127.0.0.1:19100/health`."
  Offer: (1) Continue without hooks (2) Stop and fix.
  If user continues, skip to step 9.
- If reachable: proceed.

### 8b. Check and register default hooks
Inspect the hooks list result.
- If no hooks registered: warn "No hooks registered. Will attempt to register default hooks for detected plugins."

For each detected and enabled plugin, register its default hooks by calling `mcp__plugin_router_router__router_register_tool` for each hook entry from the plugin's `default-hooks.yaml`. Only register hooks whose conditions match enabled integrations:
- **proj** hooks: register if `git_tracking.enabled` (tracking flush hooks) or `sandbox_integration` (sandbox sync hook)
- **todoist** hooks: register if `todoist_enabled`
- **trello** hooks: register if `trello_enabled`
- **zoxide** hooks: register if `zoxide_integration`
- **worktree** hooks: register if `worktree_integration` (sandbox hooks) or `zoxide_integration` (zoxide hooks)
- **sandbox** hooks: register if `sandbox_integration`

Report how many hooks were registered: "Registered N default hooks for: proj, todoist, zoxide"

### 8c. Validate hook condition paths
Inspect the `condition` field of each registered hook. Known fixes:
- `todoist.enabled` should be `sync.todoist.enabled`
- `todoist.auto_sync` should be `sync.todoist.auto_sync`
- `trello.enabled` should be `sync.trello.enabled`
- `trello.auto_sync` should be `sync.trello.auto_sync`
- `zoxide.enabled` should be `zoxide_integration`

If mismatches found, list them and offer to fix by editing `~/.claude/hooks.yaml`.

If hooks plugin is not detected, skip all of step 8 with: "Hooks plugin not detected — skipping hook registration. Hooks enable automatic sync between plugins."

## Step 9: Confirmation

Display: "proj plugin configured! Configuration saved to `~/.claude/proj.yaml`"

Show a summary of what was set up:
```
Setup complete:
  Config: ~/.claude/proj.yaml
  Plugins: sandbox, worktree, hooks, todoist, zoxide
  MCP rules: 7 servers auto-allowed
  Sandbox: initialized (3 paths)
  Hooks: 12 registered
```

## Step 10: Next steps

"Run `/proj:init` to start tracking your first project."

Suggested next: `1. /proj:init` -- create your first project | `2. /proj:load` -- load an existing project

## Prerequisites

- None (this is the first-time setup wizard).

## Error Handling

- **Already configured**: shows current values, asks to reconfigure. If declined, stops.
- **Config init failure**: displays error from `config_init` and stops.
- **Plugin detection failure**: treats plugin as not installed, continues with others.
- **Credential init failure**: displays error from the init tool and continues to the next plugin (non-blocking).
- **Sandbox plugin not detected**: skips all permission/sandbox setup with a note.
- **Hooks plugin not detected**: skips hook registration with a note.
- **Hooks server unreachable**: warns user with options to continue or stop.
- **No hooks registered**: attempts to register default hooks for detected plugins.
- **Mismatched hook conditions**: lists affected hooks and offers to fix.
- **MCP rule verification failure**: displays warning about missing rules.

## Output

Confirmation: `proj plugin configured! Configuration saved to ~/.claude/proj.yaml`. Summary of what was configured. Next step guidance to run `/proj:init`.
