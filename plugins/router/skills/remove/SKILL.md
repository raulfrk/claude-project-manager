---
name: remove
description: Remove a registered hook by ID.
allowed-tools: mcp__plugin_router_router__router_unregister_tool, mcp__plugin_router_router__router_list_tool
argument-hint: "<hook_id>"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Remove hook from registry.

**Parse $ARGUMENTS**:
- Hook ID provided (e.g. `hook-001`) → use directly
- Two tool names provided (e.g. `trigger_tool target_tool`) → `mcp__plugin_router_router__router_list_tool` to find matching hook by trigger+target. Multiple matches → list, ask user to pick
- Empty → output: "Hook ID required. Usage: `/router:remove <hook_id>` or `/router:remove <trigger_tool> <target_tool>`"

**Remove**: `mcp__plugin_router_router__router_unregister_tool(hook_id)`

Success →
```
Removed hook <hook_id>.
```

Not found →
```
Hook `<hook_id>` not found. Run `/router:list` to see available hooks.
```

## Prerequisites

Router plugin MCP server running/reachable.

## Error Handling

- No args → "Hook ID required. Usage: `/router:remove <hook_id>`", stop
- Not found → "Hook `<hook_id>` not found. Run `/router:list` to see available hooks."
- Router MCP unavailable → display err, stop

## Output

- Success: `Removed hook <hook_id>.`
- Not found: `Hook \`<hook_id>\` not found.`
