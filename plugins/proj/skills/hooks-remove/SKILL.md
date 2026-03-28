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
- If $ARGUMENTS is empty, output usage: "Usage: `/proj:hooks-remove <hook_id>` or `/proj:hooks-remove <trigger_tool> <target_tool>`"

**Remove**: Call `mcp__hooks__hooks_unregister_tool` with the resolved `hook_id`.

**On success**, confirm:
```
Removed hook <hook_id>.
```

**On not found**, display:
```
Hook '<hook_id>' not found. Run /proj:hooks-list to see available hooks.
```

Suggested next: (1) /proj:hooks-list — see remaining hooks  (2) /proj:hooks-debug — check for failures
