---
name: test
description: Test-fire a hook by ID to verify it executes correctly.
allowed-tools: mcp__plugin_router_router__router_fire_tool, mcp__plugin_router_router__router_list_tool
argument-hint: "<hook_id> [source_result_json]"
context: fork
agent: general-purpose
---

Test a registered hook by firing its trigger.

**Parse $ARGUMENTS**:
- First arg: `hook_id` (required) — the hook to test.
- Second arg (optional): `source_result_json` — a JSON string to use as the source result for template resolution. Defaults to `{}`.

If $ARGUMENTS is empty, output: "Hook ID required. Usage: `/router:test <hook_id> [source_result_json]`"

**1.** Call `mcp__plugin_router_router__router_list_tool` to look up the hook by ID. Find the hook entry whose `id` matches. If not found, stop with: "Hook `<hook_id>` not found. Run `/router:list` to see available hooks."

**2.** Extract the `trigger_tool` from the matched hook.

**3.** Call `mcp__plugin_router_router__router_fire_tool` with:
- `trigger_tool` = the hook's trigger_tool
- `source_result` = the provided source_result_json or `{}`

**4.** Parse the JSON response and display results:

```
Test fire for hook <hook_id> (<trigger_tool> -> <target_tool>):

  Hooks fired: <hooks_fired>
  Skipped (condition): <skipped>
  Errors: <count>
```

If there are errors, list each:
```
  - <hook_id>: <error>
```

If there are blocking results, show them:
```
  Results:
  - <hook_id>: <result>
```

If `hooks_fired` is 0 and `skipped` > 0, note: "Hook was skipped — check its condition."

## Prerequisites

- Router plugin MCP server is running and reachable.
- A hook ID must be provided.

## Error Handling

- **No arguments**: displays "Hook ID required. Usage: `/router:test <hook_id>`" and stops.
- **Hook not found**: displays "Hook `<hook_id>` not found. Run `/router:list` to see available hooks." and stops.
- **Router MCP unavailable**: displays error from tool call and stops.

## Output

Test fire summary: hooks fired count, skipped count, errors count. If errors, lists each with hook_id and error. If blocking results, shows them. If skipped, notes the condition.
