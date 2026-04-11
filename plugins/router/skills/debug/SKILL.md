---
name: hooks-debug
description: Debug hook execution by listing recent failures with error details.
allowed-tools: mcp__plugin_hooks_hooks__hooks_recover_tool
context: fork
agent: general-purpose
---

List recent hook failures to help debug execution issues.

**1.** Call `mcp__plugin_hooks_hooks__hooks_recover_tool` with no arguments (lists all failures as a JSON array).

**2.** Parse the JSON response. If the array is empty:
- Output: "No hook failures recorded. All hooks are healthy."
- Stop.

**3.** Display failures as a table:

```
## Hook Failures

| # | Hook ID | Trigger | Target | Server | Error | Retries | Timestamp |
|---|---------|---------|--------|--------|-------|---------|-----------|
| 1 | hook-001 | trigger | target | server | error msg | 0 | 2026-03-26T... |
```

- **Hook ID**: if the failure entry has `verification_failed: true`, append `[verification]` after the hook ID (e.g., `verify-todoist-complete [verification]`).
- **Retries**: the `retry_count` field, default 0 if absent.
- **Timestamp**: the `timestamp` field.

**4.** Show a summary:
`N failure(s) recorded.`

**5.** Display suggested next actions.

## Prerequisites

- Hooks plugin MCP server is running and reachable.

## Error Handling

- **Hooks MCP unavailable**: displays error from tool call and stops.
- **No failures**: displays `No hook failures recorded. All hooks are healthy.` and stops.

## Output

Failures table (Hook ID, Trigger, Target, Server, Error, Retries, Timestamp) with summary count. Verification failures marked with `[verification]` badge.
