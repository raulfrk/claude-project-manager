---

---
name: init-plugin
desc: First-time setup wizard for proj plugin. Run this before via any other /proj:* commands. Creates ~/.claude/proj.yaml with your preferences.
allowed-tools: Read, mcp__proj__config_init, mcp__proj__config_load, mcp__proj__config_update, mcp__plugin_sandbox_sandbox__sandbox_add_write_path, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_set_deny, Bash, mcp__proj__tracking_git_flush, mcp__plugin_router_router__router_list_tool, mcp__plugin_router_router__router_register_tool, mcp__plugin_worktree_worktree__wt_list_repos, mcp__plugin_worktree_worktree__zoxide_query, mcp__plugin_todoist_todoist__todoist_find_projects, mcp__plugin_trello_trello__list_boards, mcp__plugin_jira_jira__jira_list_projects, mcp__plugin_trello_trello__trello_init, mcp__plugin_jira_jira__jira_init, mcp__plugin_todoist_todoist__todoist_init


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Set up proj plugin. Required before any `/proj:*` cmd.

Wizard uses **load-once pattern**: Step 0 reads all config files into named vars; subsequent prompts show cur val as bracketed default. Enter keeps existing; type overrides. First-run (no configs) → hardcoded defaults.

## Step 0: Load existing config files

Before prompting, load every config file once into named var. Later steps ref these vars for defaults.

Init top-of-skill tracking set:

```
warnings_emitted = set()    # tracks which files have already warned — prevents duplicate warnings
```

Load each config file via `Read` on absolute path, parse w/ `yaml.safe_load`. On any err (missing/read fail/YAML parse fail) → set var to `None`. Warn once per file — check `warnings_emitted` before printing, add filename to set.

1. **proj_config** — Read `~/.claude/proj.yaml`:
 - Missing → `proj_config = None` (silent; first-run expected)
 - Parse fail → `proj_config = None`, warn once: `"Warning: ~/.claude/proj.yaml exists but could not be parsed (<error>). Using hardcoded defaults for proj fields."`
2. **todoist_config** — Read `~/.claude/todoist.yaml`: missing → `None` (silent); parse fail → `None` + warn once
3. **trello_config** — Read `~/.claude/trello.yaml`: same pattern
4. **jira_config** — Read `~/.claude/jira.yaml`: same pattern
5. **sandbox_state** — Call `mcp__plugin_sandbox_sandbox__sandbox_list` w/ `scope="user"`, `format="json"`:
 - Success → parse JSON, store as `sandbox_state`
 - Fail → `sandbox_state = None` (silent; Step 2 handles detection)

After this, every prompt in Steps 3/4/7 reads default from matching var via safe nested access (`(proj_config or {}).get("tracking_dir", "~/projects/tracking")` style). Var `None` or field missing → hardcoded default.

**Masking helper** (Step 3 credential fields):

```
def mask_secret(value):
    if not value:
        return "[not set]"
    if len(value) < 8:
        return "****"
    return f"****{value[-4:]}"
```

Non-sensitive fields (`trello.api_key`, `jira.base_url`, `jira.default_user`, `jira.default_project`) shown raw, not masked.

## Step 1: Check existing config

Call `mcp__proj__config_load`. If configured:
- Show all cur vals formatted
- Ask: "Reconfigure? [no]"
- Declined → "Existing config kept — no changes made." Stop.

## Step 2: Detect installed plugins

Auto-detect plugins by calling lightweight MCP tools. Do NOT ask user — detect programmatically.

Check each plugin:
- **sandbox**: `mcp__plugin_sandbox_sandbox__sandbox_list` w/ `scope="user"`, `format="json"`
- **worktree**: `mcp__plugin_worktree_worktree__wt_list_repos`
- **router**: `mcp__plugin_router_router__router_list_tool`
- **todoist**: `mcp__plugin_todoist_todoist__todoist_find_projects` w/ `name=""`
- **trello**: `mcp__plugin_trello_trello__list_boards`
- **jira**: `mcp__plugin_jira_jira__jira_list_projects`

Note: zoxide tools (`zoxide_boost`, `zoxide_query`, `zoxide_remove`) are part of worktree plugin. No separate zoxide plugin detection needed.

Tool call fail → plugin not installed. Continue silently.

Report detection results:
```
Detected plugins: sandbox, worktree, router, todoist
Not found: trello, jira
```

## Step 3: Plugin Credential Setup

Each detected plugin w/ credentials: prompt via Step 0 vals as defaults. Per-field masking: sensitive fields (`*_token`, `api_token`, `personal_access_token`) → `****<last4>` if ≥8 chars, `****` if shorter, `[not set]` when absent. Non-sensitive fields shown raw.

Masking via `mask_secret()` from Step 0. Enter keeps existing (no re-init); new val overrides + triggers init. Non-blocking — undetected/skipped plugins → continue.

### Trello (if detected)

Use `trello_config` from Step 0.

1. Compute displays:
 - `key_display` = raw (non-sensitive)
 - `token_display` = `mask_secret(trello_config.get("token", ""))`
2. Both present + non-empty → show `"Trello: ✓ credentials configured (key: <key_display>, token: <token_display>)"`, ask `"Reconfigure Trello credentials? [no]"`. No → skip.
3. Else prompt:
 - `"Trello API key? [<key_display or 'required'>]"`
 - `"Trello API token? [<token_display>]"` — validate new val ≥8 chars
4. Val changed → `mcp__plugin_trello_trello__trello_init` w/ final `api_key` + `token`
5. Err → show, continue. Success → `"Trello: ✓ credentials saved to ~/.claude/trello.yaml"`

### Jira (if detected)

Use `jira_config` from Step 0.

1. Compute displays:
 - `base_url_display` = raw; `token_display` = masked; `user_display` = raw; `project_display` = raw
2. `base_url` + `personal_access_token` both present → show `"Jira: ✓ credentials configured (base_url: <base_url_display>, token: <token_display>)"`, ask reconfigure. No → skip.
3. Else prompt:
 - `"Jira base URL? (e.g. https://yourcompany.atlassian.net) [<base_url_display or 'required'>]"`
 - `"Jira personal access token? [<token_display>]"`
 - `"Jira default user (email or account ID)? [<user_display or 'optional'>]"`
 - `"Jira default project? [<project_display or 'optional'>]"`
4. `base_url` or `personal_access_token` changed → `mcp__plugin_jira_jira__jira_init` w/ final vals
5. Err → show, continue. Success → `"Jira: ✓ credentials saved to ~/.claude/jira.yaml"`

### Todoist (if detected)

Use `todoist_config` from Step 0.

1. `token_display` = `mask_secret(todoist_config.get("api_token", ""))`
2. `api_token` present → show `"Todoist: ✓ credentials configured (token: <token_display>)"`, ask reconfigure. No → skip.
3. Else prompt: `"Todoist API token? [<token_display>]"`
4. Val changed → `mcp__plugin_todoist_todoist__todoist_init` w/ final `api_token`
5. Err → show, continue. Success → `"Todoist: ✓ credentials saved to ~/.claude/todoist.yaml"`

No sync plugins detected → skip entirely.

## Step 4: Collect config (grouped)

Present questions in logical groups, collect as batch. Each prompt default from `proj_config` via safe nested access: `(proj_config or {}).get("field", <hardcoded_default>)`. Booleans render `[yes]`/`[no]`. Missing → hardcoded default.

Path default not on disk → append ` (not found)` to bracket.

### Group A: Core paths
- **Tracking dir** — `"Where should project tracking data be stored? [<proj_config.tracking_dir or '~/projects/tracking'>]"`
 - All projects share single tracking repo here. Each project gets subdir.
- **Projects base dir** — `"Default directory where project content lives (e.g. ~/projects)? [<proj_config.projects_base_dir or 'blank to skip'>]"`
 - If set, `/proj:init` uses `<base>/<project-name>` as content path when no explicit path given.
 - Store as `projects_base_dir` (null if blank)

### Group B: Permissions & sandbox (if sandbox detected)
- **Permissions** — `"Auto-grant Claude read/edit permissions for project directories? [<yes/no from proj_config.auto_grant_permissions, default yes>]"`
- **MCP auto-allow** — `"Auto-allow plugin MCP tools so Claude never prompts for permission? [<yes/no from proj_config.auto_allow_mcps, default yes>]"`
 - Adds wildcard MCP rules for all detected plugins
- **Sandbox setup** — `"Initialize sandbox mode for project directories? [<yes/no from proj_config.sandbox_integration, default yes>]"`
 - Sets up sandbox paths for projects root, tracking root, archive dest; adds default deny rules

### Group C: Sync integrations (detected plugins only)

Each detected sync plugin: ask config sub-group. Flags from `proj_config.sync.<plugin>.*` via safe nested traversal.

**Todoist** (if detected):
- `"Enable Todoist sync? [<yes/no from proj_config.sync.todoist.enabled, default no>]"`
- Yes: `"Auto-sync on every project command? [<yes/no from proj_config.sync.todoist.auto_sync, default yes>]"`
- Yes: `"Todoist MCP server name (must match your MCP config)? [<proj_config.sync.todoist.mcp_server or 'claude_ai_Todoist'>]"` → store as `todoist_mcp_server`

**Trello** (if detected):
- `"Enable Trello sync? [<yes/no from proj_config.sync.trello.enabled, default no>]"`
- Yes: `"Auto-sync on every project command? [<yes/no from proj_config.sync.trello.auto_sync, default yes>]"`
- Yes: `"Default Trello board ID? [<proj_config.sync.trello.default_board_id or 'blank to set later'>]"`
- Yes: `"On delete action — archive or delete Trello cards? [<proj_config.sync.trello.on_delete or 'archive'>]"`
- Yes: `"Trello projects list name? [<proj_config.sync.trello.list_projects or 'Projects'>]"` — empty → shown default
- Yes: `"Trello tasks list name? [<proj_config.sync.trello.list_tasks or 'proj-tasks'>]"` — empty → shown default

**Jira** (if detected):
- `"Enable Jira sync? [<yes/no from proj_config.sync.jira.enabled, default no>]"`
- Yes: `"Default Jira user (email or account ID)? [<proj_config.sync.jira.default_user or 'blank to set later'>]"`

Skip sync sections for undetected plugins.

### Group D: Git
- **Git integration** — `"Enable git integration (detect commits, suggest todo updates)? [<yes/no from proj_config.git_integration, default yes>]"`
- **Git tracking** — `"Auto-commit tracking data (todos, notes, sessions) to the shared tracking repo? [<yes/no from proj_config.git_tracking.enabled, default no>]"`
 - All projects share single git-tracked repo at tracking dir.
 - Yes: `"Also push the tracking repo to GitHub as a private repo? [<yes/no from proj_config.git_tracking.github_enabled, default no>]"`
 - Yes: `"GitHub repo name? [<proj_config.git_tracking.github_repo_format or 'tracking'>]"` → store as `git_tracking_github_repo_format`

### Group E: Extras
- **Zoxide** (if detected) — `"Enable zoxide integration (boost project dirs in frecency)? [<yes/no from proj_config.zoxide_integration, default no>]"`
- **Worktree** (if detected) — shown as detected, no question (auto-enabled)
- **Default priority** — `"Default priority for new todos? (low/medium/high) [<proj_config.default_priority or 'medium'>]"`
 - Loaded val not low/medium/high → warn, use 'medium'
- **Archive purge** — `"Days after archiving before purgeable projects are eligible for purge? Leave empty for never. [<proj_config.archive.purge_after_days or 'none'>]"`
 - Store as `archive_purge_after_days` (None if blank, int if provided)

## Step 5: Show summary before applying

Before `config_init`, display settings summary:

```
Configuration summary:
  Core:
    tracking_dir: ~/projects/tracking
    projects_base_dir: ~/projects
  Detected plugins: sandbox, worktree, router, todoist
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
    default_priority: medium
    archive_purge: never

Apply this configuration? [yes]
```

Declined → return step 4.

## Step 6: Apply config

Call `mcp__proj__config_init` w/ all collected vals:
- Core: `tracking_dir`, `projects_base_dir`
- Permissions: `auto_grant_permissions`, `auto_allow_mcps`
- Plugins: `sandbox_integration` (auto-set), `worktree_integration` (auto-set), `zoxide_integration`
- Sync: `todoist_enabled`, `todoist_auto_sync`, `todoist_mcp_server`, `trello_enabled`, `trello_auto_sync`, `trello_default_board_id`, `trello_on_delete`, `trello_list_projects`, `trello_list_tasks`, `jira_enabled`, `jira_default_user`
- Git: `git_integration`, `git_tracking_enabled`, `git_tracking_github_enabled`, `git_tracking_github_repo_format`
- Extras: `default_priority`, `archive_purge_after_days`

Omit `todoist_mcp_server` when `todoist_enabled: false`.

## Step 7: Permission setup (if sandbox detected)

Uses `sandbox_state` from Step 0 to detect existing MCP rules/write paths/batch-setup paths → report idempotent no-ops vs re-applying. `sandbox_state` is `None` → re-fetch via `sandbox_list`.

Compute existing-rules view once:
```
existing_allow = set(sandbox_state.get("permissions_allow", [])) if sandbox_state else set()
existing_write = set(sandbox_state.get("write_paths", [])) if sandbox_state else set()
```

### 7a. MCP auto-allow
Build server list, call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup(mcp_servers=[...])` once:
- Always: `"claude_ai_Excalidraw"`, `"claude_ai_Mermaid_Chart"`
- `auto_allow_mcps: true` → also: `"plugin_proj_proj"`, `"plugin_sandbox_sandbox"`
- + worktree detected: `"plugin_worktree_worktree"`
- + router detected: `"plugin_router_router"`
- + todoist enabled: `todoist_mcp_server` val + `"plugin_todoist_todoist"`
- + trello enabled: `"plugin_trello_trello"`
- + jira enabled: `"plugin_jira_jira"`
- Filter out servers w/ wildcard rule `f"mcp__{server}__*"` already in `existing_allow` — report each as `"<rule> already present, skipping"`. Call only if filtered list non-empty.
- `zoxide_integration: true` + `"Bash(zoxide *)"` not in `existing_allow` → `mcp__plugin_sandbox_sandbox__sandbox_add_write_path` w/ `entry="Bash(zoxide *)"`. (zoxide tools are part of worktree plugin)

### 7b. Verify MCP rules
Re-read sandbox state via `mcp__plugin_sandbox_sandbox__sandbox_list` w/ `scope="user"`, `format="json"` (fresh; 7a may have mutated).
Parse `permissions_allow`.
- `sandbox_integration: true` → check `mcp__plugin_sandbox_sandbox__*` — warn if missing
- `worktree_integration: true` → check `mcp__plugin_worktree_worktree__*` — warn if missing

### 7c. Sandbox setup
- Compute `projects_root` from `projects_base_dir`
- Compute `tracking_root` from `tracking_dir`
- Compute `archive_destination` from archive config
- `sandbox_batch_setup` w/ `paths=[projects_root, tracking_root, archive_destination]`, `preserve_extra=true` — idempotent.

### 7d. Default deny rules
- `sandbox_set_deny` w/ `DEFAULT_DENY_RULES`

### 7e. Persist root paths
- `config_update` w/ `permissions_projects_root=<projects_root>`, `permissions_tracking_root=<tracking_root>`

Sandbox not detected → skip all step 7: "Sandbox plugin not detected — skipping permission and sandbox setup."

## Step 8: Hook setup (if router detected)

### 8a. Verify router connectivity
`mcp__plugin_router_router__router_list_tool` to check reachability.
- Unreachable → warn "Router server not reachable. You can check manually with `GET http://127.0.0.1:19100/health`." Offer: (1) Continue w/o hooks (2) Stop and fix. Continue → skip to step 9.
- Reachable → proceed.

### 8b. Check + register default hooks
Inspect hooks list.
- No hooks → warn "No hooks registered. Will attempt to register default hooks for detected plugins."

Each detected+enabled plugin: register default hooks via `mcp__plugin_router_router__router_register_tool` from plugin's `default-hooks.yaml`. Only register hooks matching enabled integrations:
- **proj**: `git_tracking.enabled` (tracking flush) or `sandbox_integration` (sandbox sync)
- **todoist**: `todoist_enabled`
- **trello**: `trello_enabled`
- **worktree**: `worktree_integration` (sandbox hooks) or `zoxide_integration` (zoxide hooks)
- **sandbox**: `sandbox_integration`

Report: "Registered N default hooks for: proj, todoist, worktree"

### 8c. Validate hook condition paths
Inspect `condition` field of each hook. Known fixes:
- `todoist.enabled` → `sync.todoist.enabled`
- `todoist.auto_sync` → `sync.todoist.auto_sync`
- `trello.enabled` → `sync.trello.enabled`
- `trello.auto_sync` → `sync.trello.auto_sync`
- `zoxide.enabled` → `zoxide_integration`

Mismatches found → list, offer fix by editing `~/.claude/hooks.yaml`.

Router not detected → skip all step 8: "Router plugin not detected — skipping hook registration. router plugin enables automatic sync between plugins."

## Step 9: Confirmation

Show: "proj plugin configured! Configuration saved to `~/.claude/proj.yaml`"

Summary of what was set up:
```
Setup complete:
  Config: ~/.claude/proj.yaml
  Plugins: sandbox, worktree, router, todoist
  MCP rules: 7 servers auto-allowed
  Sandbox: initialized (3 paths)
  Hooks: 12 registered
```

## Step 10: Next steps

"Run `/proj:init` to start tracking your first project."

Suggested next: `1. /proj:init` -- create first project | `2. /proj:load` -- load existing project

## Prerequisites

None (first-time setup wizard).

## Error Handling

| Condition | Action |
|---|---|
| Already configured | Show cur vals, ask reconfigure. Declined → stop |
| Config init fail | Show err, stop |
| Plugin detection fail | Treat as not installed, continue |
| Credential init fail | Show err, continue (non-blocking) |
| Sandbox not detected | Skip all perm/sandbox setup w/ note |
| Router not detected | Skip hook registration w/ note |
| Router unreachable | Warn w/ opts: continue or stop |
| No hooks registered | Register defaults for detected plugins |
| Mismatched hook conditions | List affected, offer fix |
| MCP rule verify fail | Warn about missing rules |

## Output

Confirmation: `proj plugin configured! Configuration saved to ~/.claude/proj.yaml`. Summary of config. Next step: run `/proj:init`.
