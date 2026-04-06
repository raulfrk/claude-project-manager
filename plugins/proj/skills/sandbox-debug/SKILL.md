---
name: sandbox-debug
description: Debug permission and sandbox issues for a specific path or tool
allowed-tools: mcp__plugin_sandbox_sandbox__sandbox_check, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_list
argument-hint: "<path_or_tool_name>"
context: fork
agent: general-purpose
---

# sandbox-debug

Diagnose why a specific path or tool may not have the expected permissions under the dual-layer permission model (permissions.allow + sandbox.filesystem.allowWrite).

**1.** Parse arguments

The user provides: `<path_or_tool_name>`

**2.** Check sandbox state

Call `mcp__plugin_sandbox_sandbox__sandbox_list()` to confirm whether sandbox mode is active. Include the result in the diagnostic output.

**3.** Determine type and diagnose

**If a filesystem path** (starts with `/`, `~`, or `.`):

Perform dual-layer diagnosis:

- **Layer 1 — permissions.allow**: Call `mcp__plugin_sandbox_sandbox__sandbox_check(path=<path>)`. Determine whether the path is allowed or denied by `permissions.allow` rules.
- **Layer 2 — sandbox write paths**: Call `mcp__plugin_sandbox_sandbox__sandbox_list(scope="all", format="json")`. Check whether the path appears in `sandbox.filesystem.allowWrite`. Report whether the path is writable under sandbox rules.

Both layers must allow the path for full write access. Report each layer's status independently so the user can see exactly which layer blocks access.

**If a tool/MCP server name** (no path separators):
- Call `mcp__plugin_sandbox_sandbox__sandbox_list(scope="all", format="json")`.
- Search the MCP allow rules for a matching server entry.
- If found, confirm the tool is allowed and show the rule.
- If not found, explain the server is not in the allow list.

**4.** Display diagnostic

Show a clear summary:
- **Sandbox active**: yes/no
- **Status**: allowed or denied (per layer for filesystem paths)
- **Reason**: which rule grants access, or what rule is missing in each layer
- **Fix**: the specific `sandbox-setup` invocation to resolve the issue

For filesystem paths, show a table:

| Layer | Status | Detail |
|---|---|---|
| permissions.allow | allowed/denied | matching rule or "no rule covers this path" |
| sandbox.allowWrite | allowed/denied | matching path or "path not in allowWrite list" |

**5.** Suggestion

If the path or tool is denied, suggest: "Run `sandbox-setup` to configure the missing permission layer."

Do NOT suggest `perms:grant` — all fixes should go through `sandbox-setup`.

## Prerequisites

- Perms plugin MCP server is running and reachable.
- A path or tool name must be provided as argument.

## Error Handling

- **No arguments**: asks the user what to diagnose.
- **Perms MCP unavailable**: displays error from tool call and stops.

## Output

Diagnostic summary with: Sandbox state (active/inactive), Status per layer (allowed/denied), Reason (matching rule or what's missing), Fix (specific `sandbox-setup` invocation).
