---
name: hooks-debug
description: Debug hook execution by listing recent failures with error details.
allowed-tools: mcp__hooks__hooks_recover_tool
argument-hint: ""
context: fork
agent: general-purpose
---

List recent hook failures to help debug execution issues.

**Step 1**: Call `mcp__hooks__hooks_recover_tool` with no arguments (lists all failures as a JSON array).

**Step 2**: Parse the JSON response. If the array is empty:
- Output: "No hook failures recorded."
- Stop.

**Step 3**: Display failures as a table:

```
## Hook Failures

| # | Hook ID | Trigger | Target | Server | Error | Retries | Timestamp |
|---|---------|---------|--------|--------|-------|---------|-----------|
| 1 | hook-001 | trigger | target | server | error msg | 0 | 2026-03-26T... |
```

- **Retries**: the `retry_count` field, default 0 if absent.
- **Timestamp**: the `timestamp` field.

**Step 4**: Show a summary:
`N failure(s) recorded.`

**Step 5**: Suggest next actions:
- "Use `/proj:hooks-recover <hook_id>` to retry a specific hook's failures."
- "Use `/proj:hooks-recover clear` to clear all failure entries."
