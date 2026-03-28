---
name: hooks-remove
description: Remove a registered hook by ID.
allowed-tools: mcp__hooks__hooks_unregister_tool, mcp__hooks__hooks_list_tool
argument-hint: "<hook_id>"
context: fork
agent: general-purpose
---

Remove a hook from the hooks registry.

**Parse $ARGUMENTS**:
- If a hook ID is provided (e.g. `hook-001`), use it directly.
- If two tool names are provided (e.g. `trigger_tool target_tool`), call `mcp__hooks__hooks_list_tool` to find the matching hook ID by trigger+target pair. If multiple matches, list them and ask the user to pick one.
- If $ARGUMENTS is empty, output: "Hook ID required. Usage: `/proj:hooks-remove <hook_id>` or `/proj:hooks-remove <trigger_tool> <target_tool>`"

**Remove**: Call `mcp__hooks__hooks_unregister_tool` with the resolved `hook_id`.

**On success**, confirm:
```
Removed hook <hook_id>.
```

**On not found**, display:
```
Hook `<hook_id>` not found. Run `/proj:hooks-list` to see available hooks.
```

## Prerequisites

- Hooks plugin MCP server is running and reachable.

## Error Handling

- **No arguments**: displays "Hook ID required. Usage: `/proj:hooks-remove <hook_id>`" and stops.
- **Hook not found**: displays "Hook `<hook_id>` not found. Run `/proj:hooks-list` to see available hooks."
- **Hooks MCP unavailable**: displays error from tool call and stops.

## Output

- On success: `Removed hook <hook_id>.`
- On not found: `Hook \`<hook_id>\` not found.`
