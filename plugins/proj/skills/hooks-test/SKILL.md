---
name: hooks-test
description: Test-fire a hook by ID to verify it executes correctly.
allowed-tools: mcp__hooks__hooks_fire_tool, mcp__hooks__hooks_list_tool
argument-hint: "<hook_id> [source_result_json]"
context: fork
agent: general-purpose
---

Test a registered hook by firing its trigger.

**Parse $ARGUMENTS**:
- First arg: `hook_id` (required) — the hook to test.
- Second arg (optional): `source_result_json` — a JSON string to use as the source result for template resolution. Defaults to `{}`.

If $ARGUMENTS is empty, output usage: "Usage: `/proj:hooks-test <hook_id> [source_result_json]`"

**1.** Call `mcp__hooks__hooks_list_tool` to look up the hook by ID. Find the hook entry whose `id` matches. If not found, output "Hook '<hook_id>' not found. Run `/proj:hooks-list` to see available hooks." and stop.

**2.** Extract the `trigger_tool` from the matched hook.

**3.** Call `mcp__hooks__hooks_fire_tool` with:
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

Suggested next: (1) /proj:hooks-debug — inspect failures (if errors occurred)
