---
name: recover
description: Recover from hook failures by retrying or clearing failed entries.
allowed-tools: mcp__plugin_router_router__router_recover_tool
argument-hint: "[hook_id | clear]"
context: fork
agent: general-purpose
---

Recover from hook failures by retrying or clearing entries.

**Parse $ARGUMENTS**:
- `clear` — clear all failure entries without retrying.
- `<hook_id>` (e.g. `hook-001`) — retry all failures for that specific hook.
- Empty — list failures and offer interactive recovery.

**Mode: clear**
Call `mcp__plugin_router_router__router_recover_tool` with `clear=true`.
Display: `Cleared <cleared> failure entries.`

**Mode: retry by hook_id**
Call `mcp__plugin_router_router__router_recover_tool` with `hook_id=<hook_id>`.
Parse the JSON response and display:
```
Recovery for hook <hook_id>:
  Retried: <retried>
  Succeeded: <succeeded>
  Still failing: <still_failed>
```

If `still_failed` > 0, suggest: "Failures persist — use `/router:debug` for error details, or `/router:recover clear` to discard."

**Mode: interactive (no args)**
1. Call `mcp__plugin_router_router__router_recover_tool` with no arguments to list all failures.
2. If empty, output: "No hook failures recorded. All hooks are healthy." and stop.
3. Display failures grouped by hook_id with counts.
4. For each hook_id with failures, ask: "Retry failures for `<hook_id>`? (yes/no/clear)"
   - **yes**: call `mcp__plugin_router_router__router_recover_tool` with that `hook_id`
   - **no**: skip
   - **clear**: call `mcp__plugin_router_router__router_recover_tool` with `clear=true` and stop

Display final summary of all recovery actions taken.

## Prerequisites

- Router plugin MCP server is running and reachable.

## Error Handling

- **Router MCP unavailable**: displays error from tool call and stops.
- **Hook ID not found**: displays error from `router_recover_tool` and stops.

## Output

- **clear mode**: `Cleared <cleared> failure entries.`
- **retry mode**: Recovery summary with retried/succeeded/still_failed counts.
- **interactive mode**: Failures grouped by hook_id, with recovery actions taken.
- **No failures**: `No hook failures recorded. All hooks are healthy.`
