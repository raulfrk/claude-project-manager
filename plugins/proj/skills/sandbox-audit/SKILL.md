---
name: sandbox-audit
description: Audit current permissions showing filesystem, MCP, sandbox write paths, deny rules, and network domains
allowed-tools: mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_list, mcp__plugin_sandbox_sandbox__sandbox_check, mcp__plugin_sandbox_sandbox__sandbox_reconcile
context: fork
agent: general-purpose
---

# sandbox-audit

Audit and display the current sandbox and permission configuration.

**1.** Check sandbox status

Call `mcp__plugin_sandbox_sandbox__sandbox_list()`.

Display whether sandbox mode is **enabled** or **disabled**. If disabled, display a warning and suggest running `sandbox-setup` to initialize sandbox mode.

**2.** List all permissions

Call `mcp__plugin_sandbox_sandbox__sandbox_list(scope="all", format="json")`.

**3.** Parse and display

From the JSON result, display a structured summary with these sections:

**Sandbox Write Paths**
- Count of configured write paths
- List each path

**Filesystem Allow Rules**
- Count of rules
- List each path

**MCP Allow Rules**
- Count of rules
- List each server/tool name

**Network Allowed Domains**
- Count of allowed domains
- List each domain

**Deny Rules**
- Count of deny rules
- List each denied path or pattern
- If none, display "No deny rules configured"

**4.** Check for stale paths

Call `mcp__plugin_sandbox_sandbox__sandbox_reconcile()`.

If stale paths are found, display them under a "Stale Entries" section with a warning.

**5.** Suggestions

- If sandbox is disabled, suggest `sandbox-setup` to initialize.
- If there are stale or missing permissions, suggest `sandbox-grant` to add or `sandbox-debug` to investigate.
- If mixed legacy and sandbox rules are detected, flag the legacy rules and suggest cleanup.
- If everything looks clean, confirm that the sandbox configuration is in good shape.

## Prerequisites

- Perms plugin MCP server is running and reachable.

## Error Handling

- **Perms MCP unavailable**: displays error from tool call and stops.
- **Empty settings**: displays zero counts gracefully for all sections.
- **No sandbox section**: reports sandbox disabled and suggests `sandbox-setup`.
- **Stale paths found**: displays them under a "Stale Entries" section with a warning.

## Output

Structured summary with sections: Sandbox Status (enabled/disabled), Sandbox Write Paths (count + list), Filesystem Allow Rules (count + list), MCP Allow Rules (count + list), Network Allowed Domains (count + list), Deny Rules (count + list), and optionally Stale Entries.
