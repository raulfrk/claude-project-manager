---
name: activity
description: Display a summary of recent hook activity (successes and failures).
allowed-tools: mcp__plugin_router_router__router_invocations_tool
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Show recent hook activity (successes/failures).

**1.** `mcp__plugin_router_router__router_invocations_tool` w/ `type="all"`, `limit=50`.

**2.** Parse response. Separate by `_type`:
- `_type="invocation"` → successes
- `_type="failure"` → failures

**3.** Display summary:

```
### Hook Activity (last 50 events)

**Successes**: N invocations

| Timestamp | Hook ID | Trigger Tool | Target Tool |
|-----------|---------|--------------|-------------|
| ...       | ...     | ...          | ...         |

**Failures**: N failures

| Timestamp | Hook ID | Trigger Tool | Error |
|-----------|---------|--------------|-------|
| ...       | ...     | ...          | ...   |
```

- Max 10 rows/table (most recent first). More exist → "... and N more."
- 0 entries → omit table.
- No entries at all → "No hook activity recorded yet."
- Truncate long err strings to 80 chars.

Suggested next: `1. /router:list` — see registered hooks | `2. /router:recover` — retry failed hooks
