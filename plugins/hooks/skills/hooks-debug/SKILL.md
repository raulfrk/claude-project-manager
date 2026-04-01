---
context: fork
agent: general-purpose
---

# hooks-debug

Display a summary of recent hook activity (successes and failures).

**1.** Call `mcp__plugin_hooks_hooks__hooks_invocations_tool` with `type="all"` and `limit=50`.

**2.** Parse the response. Separate entries by `_type`:
- `_type="invocation"` — successful hook executions
- `_type="failure"` — hook failures

**3.** Display the summary:

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

- Show at most 10 rows per table (most recent first). If more exist, note "... and N more."
- If a table has 0 entries, omit it.
- If no entries at all: output "No hook activity recorded yet."
- Truncate long error strings to 80 chars.

Suggested next: `1. /hooks:list` — see registered hooks | `2. /hooks:recover` — retry failed hooks
