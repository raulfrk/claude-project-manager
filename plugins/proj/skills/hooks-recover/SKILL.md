---
name: hooks-recover
description: Recover from hook failures by retrying or clearing failed entries.
allowed-tools: mcp__hooks__hooks_recover_tool
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
Call `mcp__hooks__hooks_recover_tool` with `clear=true`.
Display: `Cleared <cleared> failure entries.`

**Mode: retry by hook_id**
Call `mcp__hooks__hooks_recover_tool` with `hook_id=<hook_id>`.
Parse the JSON response and display:
```
Recovery for hook <hook_id>:
  Retried: <retried>
  Succeeded: <succeeded>
  Still failing: <still_failed>
```

If `still_failed` > 0, suggest: "Failures persist — use `/proj:hooks-debug` for error details, or `/proj:hooks-recover clear` to discard."

**Mode: interactive (no args)**
1. Call `mcp__hooks__hooks_recover_tool` with no arguments to list all failures.
2. If empty, output: "No failures to recover." and stop.
3. Display failures grouped by hook_id with counts.
4. For each hook_id with failures, ask: "Retry failures for `<hook_id>`? (yes/no/clear)"
   - **yes**: call `mcp__hooks__hooks_recover_tool` with that `hook_id`
   - **no**: skip
   - **clear**: call `mcp__hooks__hooks_recover_tool` with `clear=true` and stop

Display final summary of all recovery actions taken.
