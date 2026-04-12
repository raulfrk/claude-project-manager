---
name: debug
description: Debug hook execution by listing recent failures with error details.
allowed-tools: mcp__plugin_router_router__router_recover_tool
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List recent hook failures for debug.

**1.** `mcp__plugin_router_router__router_recover_tool` w/ no args (returns JSON array).

**2.** Parse JSON. Empty array → output "No hook failures recorded. All hooks are healthy." Stop.

**3.** Show failures table:

```
## Hook Failures

| # | Hook ID | Trigger | Target | Server | Error | Retries | Timestamp |
|---|---------|---------|--------|--------|-------|---------|-----------|
| 1 | hook-001 | trigger | target | server | error msg | 0 | 2026-03-26T... |
```

- Hook ID: if `verification_failed: true`, append `[verification]` (e.g., `verify-todoist-complete [verification]`)
- Retries: `retry_count` field, default 0
- Timestamp: `timestamp` field

**4.** Summary: `N failure(s) recorded.`

**5.** Show suggested next actions.

## Prerequisites

Router plugin MCP server running/reachable.

## Err Handling

- Router MCP unavailable → show err, stop
- No failures → "No hook failures recorded. All hooks are healthy." Stop.

## Output

Failures table (Hook ID, Trigger, Target, Server, Error, Retries, Timestamp) w/ summary count. Verification failures marked `[verification]`.
