---
name: perms-audit
description: Audit current permissions showing filesystem, MCP, and sandbox status
allowed-tools: mcp__plugin_perms_perms__perms_list, mcp__plugin_perms_perms__perms_is_sandbox_enabled, mcp__plugin_perms_perms__perms_check, mcp__plugin_perms_perms__perms_cleanup_stale
context: fork
agent: general-purpose
---

# perms-audit

Audit and display the current permission configuration.

**1.** List all permissions

Call `mcp__plugin_perms_perms__perms_list(scope="all", format="json")`.

**2.** Parse and display

From the JSON result, display a structured summary:

**Filesystem Allow Rules**
- Count of rules
- List each path

**MCP Allow Rules**
- Count of rules
- List each server name

**Sandbox Status**
- Whether sandbox mode is enabled or disabled

**3.** Check for stale paths

Call `mcp__plugin_perms_perms__perms_cleanup_stale()`.

If stale paths are found, display them under a "Stale Permissions" section with a warning.

**4.** Suggestions

- If there are stale or missing permissions, suggest `perms:grant` to add or `perms:debug` to investigate.
- If everything looks clean, confirm that permissions are in good shape.

## Prerequisites

- Perms plugin MCP server is running and reachable.

## Error Handling

- **Perms MCP unavailable**: displays error from tool call and stops.
- **Stale paths found**: displays them under a "Stale Permissions" section with a warning.

## Output

Structured summary with sections: Filesystem Allow Rules (count + list), MCP Allow Rules (count + list), Sandbox Status (enabled/disabled), and optionally Stale Permissions.
