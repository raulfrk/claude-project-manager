---
name: sandbox
description: Unified sandbox management — auto-detects state, sets up permissions, checks sync, audits configuration, and debugs issues
allowed-tools: mcp__plugin_proj_proj__sandbox_sandbox_list, mcp__plugin_proj_proj__sandbox_sandbox_batch_setup, mcp__plugin_proj_proj__sandbox_sandbox_batch_revoke, mcp__plugin_proj_proj__sandbox_sandbox_add_write_path, mcp__plugin_proj_proj__sandbox_sandbox_check, mcp__plugin_proj_proj__sandbox_sandbox_reconcile, mcp__plugin_proj_proj__notes_append, mcp__plugin_proj_proj__proj_perms_sync, mcp__plugin_proj_proj__proj_session_context, Edit
argument-hint: "[--setup] [--debug <path|tool>] [--apply] [path_or_server] [scope]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

# sandbox

Unified sandbox mgmt. Auto-detects state, runs appropriate flow, or accepts flags for specific mode.

## Arg Parsing

Parse `$ARGUMENTS`:

- `--setup` — force SETUP even if configured
- `--debug <path|tool>` — DEBUG flow for given target
- `--apply` — CHECK flow auto-adds missing rules
- Bare `<path_or_server> [scope]` (no flags) — AD-HOC GRANT

`--debug` → **DEBUG**; `--setup` → **SETUP**; bare path/server → **AD-HOC GRANT**; no args → **AUTO-DETECT**.


## Auto-detect

**1.** `mcp__plugin_proj_proj__sandbox_sandbox_list()`

- Not enabled/configured (no write paths, no MCP rules) → **SETUP**.
- Enabled + configured → **CHECK**.


## SETUP Flow

Full sandbox init. Idempotent.

**S1.** Check state via `mcp__plugin_proj_proj__sandbox_sandbox_list()`.

- NOT enabled → warn user, confirm before proceeding. Declined → stop.
- Already enabled → proceed.

**S2.** Auto-backup cur permissions

`mcp__plugin_proj_proj__sandbox_sandbox_list()` for snapshot. Then `mcp__plugin_proj_proj__notes_append` w/:
- `project_id`: active project ID (from session ctx), or `"claude-project-manager"` if outside project
- `text`: timestamped block w/ full `sandbox_list` output:
  ```
  ## Sandbox-setup auto-backup (YYYY-MM-DDTHH:MM)
  <sandbox_list output>
  ```

**S3.** Batch setup

`mcp__plugin_proj_proj__sandbox_sandbox_batch_setup()` single atomic call:

- `mcp_servers`: `["plugin_router_router", "plugin_proj_proj", "plugin_sandbox_sandbox", "plugin_worktree_worktree", "plugin_trello_trello", "plugin_jira_jira", "plugin_todoist_todoist"]`
- `paths`: `["//home/raul/projects/**", "//home/raul/projects/tracking/**", "//home/raul/worktrees/**", "//home/raul/.claude/skills/**", "//home/raul/.claude/plugins/**", "//tmp/**"]`
- `skill_prefixes`: `["proj:", "worktree:", "router:", "review:"]`
- `target`: `"settings"`

**S4.** Set sandbox write paths via `mcp__plugin_proj_proj__sandbox_sandbox_batch_setup()` for all project paths.

**S5.** Add explicit Read permissions

Edit `~/.claude/settings.json` — append to `permissions.allow` (skip existing):
- `"Read(//home/raul/projects/**)"`
- `"Read(//home/raul/projects/tracking/**)"`
- `"Read(//home/raul/worktrees/**)"`
- `"Read(//home/raul/.claude/skills/**)"`
- `"Read(//home/raul/.claude/plugins/**)"`
- `"Read(//tmp/**)"`

**S6.** Verify via `mcp__plugin_proj_proj__sandbox_sandbox_list()`.

**S7.** Print: "Sandbox permissions configured for N MCP servers, M filesystem paths, P skill prefixes." (N/M/P from verification)


## CHECK Flow

Compare expected vs actual, report, optionally auto-fix.

**C1.** `mcp__plugin_proj_proj__proj_session_context` for config/project metadata. No active project → "No active project. Run `/proj:load` to load one." Stop.

**C2.** `mcp__plugin_proj_proj__sandbox_sandbox_list(scope="user")`.

- Sandbox false → "Sandbox mode not enabled. Run `/proj:sandbox --setup` to init." Stop.
- Tool fails → "Sandbox MCP server not available." Stop.

**C3.** Get rules via `mcp__plugin_proj_proj__sandbox_sandbox_list(scope="user", format="json")`. Extract:
- `actual_rules` = `mcp_allow` list
- `actual_sandbox_paths` = `write_paths` list
- `actual_skill_allow` = `skill_allow` list
- `actual_deny_rules` = `deny` list (omit if absent)

**C4.** `mcp__plugin_proj_proj__proj_perms_sync`:
- `actual_rules` = mcp_allow from C3
- `actual_sandbox_paths` = write_paths from C3
- `actual_skill_allow` = skill_allow from C3
- `actual_deny_rules` = deny from C3 (omit if absent)
- `sandbox_mode` = true
- `apply` = true if `--apply`, false otherwise

**C5.** `mcp__plugin_proj_proj__sandbox_sandbox_reconcile()`. Stale paths found → show under "Stale Entries" w/ warning.

**C6.** Report sections:

- **Sandbox Status**: enabled/disabled
- **Sandbox Write Paths**: count + list
- **Filesystem Allow Rules**: count + list
- **MCP Allow Rules**: count + list
- **Skill Allow Rules**: count + list
- **Network Allowed Domains**: count + list
- **Deny Rules**: count + list (or "No deny rules configured")
- **Sync Result**: from C4 (missing rules, applied fixes, or "all in sync")
- **Stale Entries**: from C5 (or "none")

Deny rule warnings (lines starting "Warning") → display prominently at end.

**C7.** Suggestions

- Missing rules + no `--apply` → suggest `sandbox --apply`.
- Stale entries → suggest cleanup.
- Mixed legacy + sandbox rules → flag legacy, suggest cleanup.
- All clean → confirm good shape.


## DEBUG Flow

Targeted diagnostics for specific path/tool.

**D1.** Parse target from `--debug <path_or_tool>`. No target → ask: "What path or tool to debug?"

**D2.** `mcp__plugin_proj_proj__sandbox_sandbox_list()` — confirm sandbox active.

**D3.** Determine type, diagnose:

**Filesystem path** (starts w/ `/`, `~`, `.`): dual-layer diagnosis:

- Layer 1 — `permissions.allow`: `mcp__plugin_proj_proj__sandbox_sandbox_check(path=<path>)`. Allowed/denied?
- Layer 2 — sandbox write paths: `mcp__plugin_proj_proj__sandbox_sandbox_list(scope="all", format="json")`. Path in `sandbox.filesystem.allowWrite`? Writable?

Both layers must allow for full write access. Report each independently.

**Tool/MCP server** (no path separators):
- `mcp__plugin_proj_proj__sandbox_sandbox_list(scope="all", format="json")`
- Search MCP allow rules for match.
- Found → confirm allowed, show rule. Not found → explain not in allow list.

**D4.** Diagnostic summary:
- **Sandbox active**: yes/no
- **Status**: allowed/denied (per layer for paths)
- **Reason**: granting rule or missing rule per layer
- **Fix**: specific `sandbox --setup` invocation

Filesystem path table:

| Layer | Status | Detail |
|---|---|---|
| permissions.allow | allowed/denied | matching rule or "no rule covers this path" |
| sandbox.allowWrite | allowed/denied | matching path or "path not in allowWrite list" |

**D5.** If denied → suggest: "Run `/proj:sandbox --setup` to configure missing permission layer."

Do NOT suggest `/proj:sandbox-setup` — all fixes via `/proj:sandbox`.


## AD-HOC GRANT Flow

Bare args (path/server, no `--` flags).

**A1.** Parse: `<path_or_mcp_server> [scope]`. `scope` defaults `user`. Valid: `user`, `project`.

**A2.** Determine type:

- Filesystem path (starts `/`, `~`, `.`) → `mcp__plugin_proj_proj__sandbox_sandbox_add_write_path(path=<path>, scope=<scope>)`
- MCP server (no path separators) → `mcp__plugin_proj_proj__sandbox_sandbox_batch_setup(mcp_servers=[<name>])`
- No recognizable arg → ask: 1) "Grant access to what? (path or MCP server)" 2) "Scope? (user/project)" — default `user`.

**A3.** Show confirmation result.


## Prerequisites

- Sandbox plugin MCP server running + reachable.
- CHECK flow: active project loaded.
- SETUP flow: project should be loaded (prompt if missing).

## Err Handling

- Sandbox MCP unavailable → show err, stop.
- No active project (CHECK) → "No active project. Run `/proj:load` to load one." Stop.
- Invalid path/server → show err, stop.
- Already configured → idempotent, reports cur state.
- No args + ambiguous input → interactive Q&A.


## Deprecated Skills

Old skills replaced by this unified skill. Still work, removed in future.

| Old skill | Equivalent |
|---|---|
| `/proj:sandbox-setup` | `/proj:sandbox --setup` |
| `/proj:sandbox-setup <path> [scope]` | `/proj:sandbox <path> [scope]` |
| `/proj:sandbox-audit` | `/proj:sandbox` (auto-detect → CHECK) |
| `/proj:sandbox-sync` | `/proj:sandbox` (CHECK includes sync) |
| `/proj:sandbox-sync --apply` | `/proj:sandbox --apply` |
| `/proj:sandbox-debug <target>` | `/proj:sandbox --debug <target>` |
