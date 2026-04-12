---
name: recover
description: Recover from hook failures by retrying or clearing failed entries.
allowed-tools: mcp__plugin_router_router__router_recover_tool
argument-hint: "[hook_id | clear]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Recover from hook failures by retrying or clearing entries.

**Parse $ARGUMENTS**:
- `clear` — clear all failures w/o retry
- `<hook_id>` (e.g. `hook-001`) — retry failures for that hook
- Empty — list failures, offer interactive recovery

**Mode: clear**
`mcp__plugin_router_router__router_recover_tool` w/ `clear=true`.
Output: `Cleared <cleared> failure entries.`

**Mode: retry by hook_id**
`mcp__plugin_router_router__router_recover_tool` w/ `hook_id=<hook_id>`.
Parse JSON response, display:
```
Recovery for hook <hook_id>:
  Retried: <retried>
  Succeeded: <succeeded>
  Still failing: <still_failed>
```

`still_failed` > 0 → suggest `/router:debug` for details or `/router:recover clear` to discard.

**Mode: interactive (no args)**
1. `mcp__plugin_router_router__router_recover_tool` w/ no args → list all failures.
2. Empty → "No hook failures recorded. All hooks are healthy." Stop.
3. Show failures grouped by hook_id w/ counts.
4. Each hook_id: ask "Retry failures for `<hook_id>`? (yes/no/clear)"
 - yes → `mcp__plugin_router_router__router_recover_tool` w/ that `hook_id`
 - no → skip
 - clear → `mcp__plugin_router_router__router_recover_tool` w/ `clear=true`. Stop.

Show final summary of recovery actions.

## Prerequisites

Router plugin MCP server running & reachable.

## Error Handling

- Router MCP unavailable → show err, stop
- Hook ID not found → show err, stop

## Output

- clear: `Cleared <cleared> failure entries.`
- retry: Recovery summary w/ retried/succeeded/still_failed counts
- interactive: Failures grouped by hook_id w/ recovery actions
- No failures: `No hook failures recorded. All hooks are healthy.`
