---
name: perms-sync
description: Check if Claude Code settings match the active project's expected permission rules. Reports missing MCP allow rules and sandbox write paths. Use when asked "check permissions", "perms sync", "are my permissions correct", or "verify settings".
argument-hint: "[--apply]"
allowed-tools: mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_perms_perms__perms_list, mcp__proj__proj_perms_sync, mcp__proj__proj_session_context
context: fork
agent: general-purpose
---

Check if Claude Code settings match the active project's expected permission rules.

**Arguments:** Parse `$ARGUMENTS`:
- `--apply` — if present, automatically add all missing rules (default: report only)

**Steps:**

**1.** Call `mcp__proj__proj_session_context` to get config and project metadata. If no active project, stop with: "No active project. Run `/proj:load` to load one."

**2.** Get sandbox mode: Call `mcp__plugin_perms_perms__perms_is_sandbox_enabled` with `scope="user"`.
   - Parse the result: if it contains `"true"`, set `sandbox_mode = true`, otherwise `sandbox_mode = false`.
   - If the tool call fails (perms plugin not available), display: "Perms MCP server not available. Check your MCP server configuration and restart Claude Code." and stop.

**3.** Get current rules: Call `mcp__plugin_perms_perms__perms_list` with `scope="user"` and `format="json"`.
   - Parse the JSON result. Extract from the user scope entry:
     - `actual_rules` = the `permissions_allow` list
     - `actual_sandbox_paths` = the `sandbox_allow_write` list (if `sandbox_mode` is true; otherwise empty list)
     - `actual_deny_rules` = the `permissions_deny` list (if present in the JSON; otherwise omit)
   - If the tool call fails, display: "Perms MCP server not available. Check your MCP server configuration and restart Claude Code." and stop.

**4.** Run sync check: Call `mcp__proj__proj_perms_sync` with:
   - `actual_rules` = the `permissions_allow` list from step 3
   - `actual_sandbox_paths` = the `sandbox_allow_write` list from step 3 (empty list if sandbox_mode is false)
   - `actual_deny_rules` = the `permissions_deny` list from step 3 (omit if not present)
   - `sandbox_mode` = the boolean from step 2
   - `apply` = true if `--apply` flag was present, false otherwise

**5.** Display the result from `proj_perms_sync`. If the result contains a deny rules warning (lines starting with "⚠️"), display it prominently at the end of the output.

## Prerequisites

- An active project must be loaded.
- Perms plugin MCP server must be running and reachable.

## Error Handling

- **No active project**: displays "No active project. Run `/proj:load` to load one." and stops.
- **Perms MCP unavailable**: displays "Perms MCP server not available." and stops.
- **Sync check error**: displays error from `proj_perms_sync` and stops.

## Output

Sync check result: missing MCP allow rules, missing sandbox write paths, and (if `--apply` was used) confirmation of rules added. Summary of current vs expected state.

Suggested next: `1. /proj:status` -- see project overview
