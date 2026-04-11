---
name: sandbox
description: Unified sandbox management — auto-detects state, sets up permissions, checks sync, audits configuration, and debugs issues
allowed-tools: mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_batch_setup, mcp__plugin_sandbox_sandbox__sandbox_add_write_path, mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow, mcp__plugin_sandbox_sandbox__sandbox_add_skill_allow, mcp__plugin_sandbox_sandbox__sandbox_check, mcp__plugin_sandbox_sandbox__sandbox_reconcile, mcp__plugin_proj_proj__notes_append, mcp__plugin_proj_proj__proj_perms_sync, mcp__plugin_proj_proj__proj_session_context, Edit
argument-hint: "[--setup] [--debug <path|tool>] [--apply] [path_or_server] [scope]"
---

# sandbox

Unified sandbox management skill. Auto-detects the current state and runs the appropriate flow, or accepts explicit flags to target a specific mode.

## Argument Parsing

Parse `$ARGUMENTS` for:

- `--setup` — force SETUP flow even if sandbox is already configured
- `--debug <path|tool>` — run DEBUG flow for the given path or tool name
- `--apply` — in CHECK flow, automatically add all missing rules instead of report-only
- Bare `<path_or_server> [scope]` (no flags) — AD-HOC GRANT: add a single permission

If `--debug` is present, go directly to the **DEBUG** flow.
If `--setup` is present, go directly to the **SETUP** flow.
If a bare path or server name is provided (no `--` flags), go to the **AD-HOC GRANT** flow.
If no arguments, proceed to **AUTO-DETECT**.

---

## Auto-detect

**1.** Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to check current state.

- If sandbox mode is **not enabled** or **not configured** (no write paths, no MCP rules): run **SETUP** flow.
- If sandbox mode is **enabled and configured**: run **CHECK** flow.

---

## SETUP Flow

Full sandbox initialization. Idempotent — safe to re-run.

**S1.** Check sandbox state

Call `mcp__plugin_sandbox_sandbox__sandbox_list()`.

- If sandbox is NOT enabled: warn the user that sandbox mode is not yet active and ask them to confirm before proceeding. If the user declines, stop.
- If sandbox is already enabled: proceed.

**S2.** Auto-backup current permissions

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to snapshot the current permissions. Then call `mcp__plugin_proj_proj__notes_append` with:
- `project_id`: the active project ID (from session context), or `"claude-project-manager"` if running outside a project session
- `text`: a timestamped block containing the full `sandbox_list` output, formatted as:
  ```
  ## Sandbox-setup auto-backup (YYYY-MM-DDTHH:MM)
  <sandbox_list output>
  ```

**S3.** Batch setup permissions

Call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup()` in a single atomic call with:

- `mcp_servers`: `["plugin_router_router", "plugin_proj_proj", "plugin_sandbox_sandbox", "plugin_worktree_worktree", "plugin_trello_trello", "plugin_jira_jira", "plugin_todoist_todoist", "plugin_zoxide_zoxide"]`
- `paths`: `["//home/raul/projects/**", "//home/raul/projects/tracking/**", "//home/raul/worktrees/**", "//home/raul/.claude/skills/**", "//home/raul/.claude/plugins/**", "//tmp/**"]`
- `skill_prefixes`: `["proj:", "worktree:", "router:", "review:"]`
- `target`: `"settings"`

**S4.** Set sandbox write paths

Call `mcp__plugin_sandbox_sandbox__sandbox_batch_setup()` to configure sandbox filesystem write rules for all project paths.

**S5.** Add explicit Read permissions

Add `Read(path)` entries to `permissions.allow` in `~/.claude/settings.json` for all sandbox paths. Use Edit on `~/.claude/settings.json` to append the following entries to the `permissions.allow` array (skip any already present):
- `"Read(//home/raul/projects/**)"`
- `"Read(//home/raul/projects/tracking/**)"`
- `"Read(//home/raul/worktrees/**)"`
- `"Read(//home/raul/.claude/skills/**)"`
- `"Read(//home/raul/.claude/plugins/**)"`
- `"Read(//tmp/**)"`

**S6.** Verify grants

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to verify all grants are present.

**S7.** Print summary

Display: "Sandbox permissions configured for N MCP servers, M filesystem paths, and P skill prefixes."

Replace N, M, P with the counts confirmed in the verification step.

---

## CHECK Flow

Compare expected vs actual sandbox state, display a report, and optionally auto-fix.

**C1.** Get session context

Call `mcp__plugin_proj_proj__proj_session_context` to get config and project metadata. If no active project, stop with: "No active project. Run `/proj:load` to load one."

**C2.** Get sandbox state

Call `mcp__plugin_sandbox_sandbox__sandbox_list` with `scope="user"`.

- If sandbox mode is false, display: "Sandbox mode is not enabled. Run `/proj:sandbox --setup` to initialize." and stop.
- If the tool call fails, display: "Sandbox MCP server not available." and stop.

**C3.** Get current rules

Call `mcp__plugin_sandbox_sandbox__sandbox_list` with `scope="user"` and `format="json"`. Extract:
- `actual_rules` = the `mcp_allow` list
- `actual_sandbox_paths` = the `write_paths` list
- `actual_skill_allow` = the `skill_allow` list
- `actual_deny_rules` = the `deny` list (if present; otherwise omit)

**C4.** Run sync check

Call `mcp__plugin_proj_proj__proj_perms_sync` with:
- `actual_rules` = mcp_allow list from C3
- `actual_sandbox_paths` = write_paths list from C3
- `actual_skill_allow` = skill_allow list from C3
- `actual_deny_rules` = deny list from C3 (omit if not present)
- `sandbox_mode` = true
- `apply` = true if `--apply` flag was present, false otherwise

**C5.** Audit — check for stale paths

Call `mcp__plugin_sandbox_sandbox__sandbox_reconcile()`.

If stale paths are found, display them under a "Stale Entries" section with a warning.

**C6.** Display report

Show a structured summary with these sections:

**Sandbox Status**: enabled/disabled

**Sandbox Write Paths**: count + list

**Filesystem Allow Rules**: count + list

**MCP Allow Rules**: count + list

**Skill Allow Rules**: count + list

**Network Allowed Domains**: count + list

**Deny Rules**: count + list (or "No deny rules configured")

**Sync Result**: output from C4 (missing rules, applied fixes, or "all in sync")

**Stale Entries**: output from C5 (or "none")

If the sync result contains deny rule warnings (lines starting with "Warning"), display them prominently at the end.

**C7.** Suggestions

- If missing rules were found and `--apply` was not used: suggest `sandbox --apply` to auto-fix.
- If stale entries exist: suggest cleanup.
- If mixed legacy and sandbox rules detected: flag legacy rules and suggest cleanup.
- If everything is clean: confirm the sandbox configuration is in good shape.

---

## DEBUG Flow

Targeted diagnostics for a specific path or tool.

**D1.** Parse the debug target from `--debug <path_or_tool>`.

If no target was provided after `--debug`, ask the user: "What path or tool would you like to debug?"

**D2.** Check sandbox state

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to confirm whether sandbox mode is active.

**D3.** Determine type and diagnose

**If a filesystem path** (starts with `/`, `~`, or `.`):

Perform dual-layer diagnosis:

- **Layer 1 -- permissions.allow**: Call `mcp__plugin_sandbox_sandbox__sandbox_check(path=<path>)`. Determine whether the path is allowed or denied by `permissions.allow` rules.
- **Layer 2 -- sandbox write paths**: Call `mcp__plugin_sandbox_sandbox__sandbox_list(scope="all", format="json")`. Check whether the path appears in `sandbox.filesystem.allowWrite`. Report whether the path is writable under sandbox rules.

Both layers must allow the path for full write access. Report each layer's status independently.

**If a tool/MCP server name** (no path separators):
- Call `mcp__plugin_sandbox_sandbox__sandbox_list(scope="all", format="json")`.
- Search the MCP allow rules for a matching server entry.
- If found, confirm the tool is allowed and show the rule.
- If not found, explain the server is not in the allow list.

**D4.** Display diagnostic

Show a clear summary:
- **Sandbox active**: yes/no
- **Status**: allowed or denied (per layer for filesystem paths)
- **Reason**: which rule grants access, or what rule is missing in each layer
- **Fix**: the specific `sandbox --setup` invocation to resolve the issue

For filesystem paths, show a table:

| Layer | Status | Detail |
|---|---|---|
| permissions.allow | allowed/denied | matching rule or "no rule covers this path" |
| sandbox.allowWrite | allowed/denied | matching path or "path not in allowWrite list" |

**D5.** Suggestion

If the path or tool is denied, suggest: "Run `/proj:sandbox --setup` to configure the missing permission layer."

Do NOT suggest `/proj:sandbox-setup` -- all fixes go through `/proj:sandbox`.

---

## AD-HOC GRANT Flow

Triggered when bare arguments are provided (a path or MCP server name, no `--` flags).

**A1.** Parse arguments: `<path_or_mcp_server> [scope]`

- `scope` defaults to `user` if not specified. Valid values: `user`, `project`.

**A2.** Determine type and act

**If a filesystem path** (starts with `/`, `~`, or `.`):
- Call `mcp__plugin_sandbox_sandbox__sandbox_add_write_path(path=<path>, scope=<scope>)`

**If an MCP server name** (no path separators):
- Call `mcp__plugin_sandbox_sandbox__sandbox_add_mcp_allow(server_name=<name>, scope=<scope>)`

**If no recognizable argument**, ask interactively:
1. "What would you like to grant access to? (filesystem path or MCP server name)"
2. "What scope? (user or project)" -- default to `user` if skipped.

**A3.** Show the confirmation result.

---

## Prerequisites

- Sandbox plugin MCP server must be running and reachable.
- For CHECK flow, an active project must be loaded.
- For SETUP flow, a project should be loaded (prompt user to load one first if missing).

## Error Handling

- **Sandbox MCP unavailable**: display error from tool call and stop.
- **No active project** (CHECK flow): display "No active project. Run `/proj:load` to load one." and stop.
- **Invalid path or server name**: display error from the sandbox tool and stop.
- **Already configured**: idempotent -- re-running reports current state without errors.
- **No arguments in ad-hoc mode with ambiguous input**: starts interactive Q&A.

---

## Deprecated Skills

The following standalone skills are replaced by this unified skill. They will continue to work but will be removed in a future release.

| Old skill | Equivalent |
|---|---|
| `/proj:sandbox-setup` | `/proj:sandbox --setup` |
| `/proj:sandbox-setup <path> [scope]` | `/proj:sandbox <path> [scope]` |
| `/proj:sandbox-audit` | `/proj:sandbox` (auto-detect runs CHECK when configured) |
| `/proj:sandbox-sync` | `/proj:sandbox` (CHECK flow includes sync) |
| `/proj:sandbox-sync --apply` | `/proj:sandbox --apply` |
| `/proj:sandbox-debug <target>` | `/proj:sandbox --debug <target>` |
