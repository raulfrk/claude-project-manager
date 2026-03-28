---
name: perms-debug
description: Debug permission issues for a specific path or tool
allowed-tools: mcp__plugin_perms_perms__perms_check, mcp__plugin_perms_perms__perms_list, mcp__plugin_perms_perms__perms_is_sandbox_enabled
argument-hint: "<path_or_tool_name>"
context: fork
agent: general-purpose
---

# perms-debug

Diagnose why a specific path or tool may not have the expected permissions.

**1.** Parse arguments

The user provides: `<path_or_tool_name>`

**2.** Determine type and diagnose

**If a filesystem path** (starts with `/`, `~`, or `.`):
- Call `mcp__plugin_perms_perms__perms_check(path=<path>)`.
- Display whether the path is currently allowed or denied.
- If denied, explain what rule is missing and show the exact command to fix it.

**If a tool/MCP server name** (no path separators):
- Call `mcp__plugin_perms_perms__perms_list(scope="all", format="json")`.
- Search the MCP allow rules for a matching server entry.
- If found, confirm the tool is allowed and show the rule.
- If not found, explain the server is not in the allow list.

**3.** Display diagnostic

Show a clear summary:
- **Status**: allowed or denied
- **Reason**: which rule grants access, or what rule is missing
- **Fix**: the specific `perms:grant` invocation to resolve the issue

**4.** Suggestion

If the path or tool is denied, suggest: "Run `perms:grant <path_or_tool> [scope]` to add the permission."

## Prerequisites

- Perms plugin MCP server is running and reachable.
- A path or tool name must be provided as argument.

## Error Handling

- **No arguments**: asks the user what to diagnose.
- **Perms MCP unavailable**: displays error from tool call and stops.

## Output

Diagnostic summary with: Status (allowed/denied), Reason (matching rule or what's missing), Fix (specific `perms:grant` invocation).
