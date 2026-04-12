---
name: test
description: Test-fire a hook by ID to verify it executes correctly.
allowed-tools: mcp__plugin_router_router__router_fire_tool, mcp__plugin_router_router__router_list_tool
argument-hint: "<hook_id> [source_result_json]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Test registered hook by firing its trigger.

**Parse $ARGUMENTS**:
- First arg: `hook_id` (required)
- Second arg (opt): `source_result_json` — JSON string for template resolution. Default `{}`.

Empty $ARGUMENTS → "Hook ID required. Usage: `/router:test <hook_id> [source_result_json]`"

**1.** `mcp__plugin_router_router__router_list_tool` — find hook by ID. Not found → "Hook `<hook_id>` not found. Run `/router:list` to see available hooks."

**2.** Extract `trigger_tool` from matched hook.

**3.** `mcp__plugin_router_router__router_fire_tool` w/ `trigger_tool` + `source_result` (provided json or `{}`).

**4.** Parse JSON response, display:

```
Test fire for hook <hook_id> (<trigger_tool> -> <target_tool>):

  Hooks fired: <hooks_fired>
  Skipped (condition): <skipped>
  Errors: <count>
```

Errors → list each:
```
  - <hook_id>: <error>
```

Blocking results → show:
```
  Results:
  - <hook_id>: <result>
```

`hooks_fired` 0 + `skipped` > 0 → "Hook was skipped — check its condition."

## Prerequisites

- Router plugin MCP server running/reachable.
- Hook ID required.

## Error Handling

- No args → "Hook ID required. Usage: `/router:test <hook_id>`", stop.
- Hook not found → "Hook `<hook_id>` not found. Run `/router:list` to see available hooks.", stop.
- Router MCP unavailable → display err, stop.

## Output

Test fire summary: hooks fired/skipped/errors count. Errors → list each w/ hook_id + err. Blocking → show. Skipped → note condition.
