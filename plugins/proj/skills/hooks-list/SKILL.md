---
name: hooks-list
description: List all registered MCP-to-MCP hooks, grouped by trigger tool, showing status and routing info.
allowed-tools: mcp__hooks__hooks_list_tool
argument-hint: "[trigger_tool]"
context: fork
agent: general-purpose
---

List all registered hooks from the hooks registry.

**Parse $ARGUMENTS**:
- If a trigger tool name is provided, pass it as `trigger_tool` to filter results.
- If empty, list all hooks.

**1.** Call `mcp__hooks__hooks_list_tool` with optional `trigger_tool` filter.

**2.** Parse the JSON response. If `hooks` array is empty:
- Output: "No hooks registered. Run `/proj:hooks-add` to create one."
- Stop.

**3.** Group hooks by `trigger_tool`. For each group, display a header and table:

```
## trigger_tool_name

| ID | Target | Server | Blocking | Condition | Status |
|----|--------|--------|----------|-----------|--------|
| hook-001 | target_tool | server_name | yes/no | condition or — | active/inactive/always |
```

- **Blocking**: "yes" if `blocking` is true, "no" otherwise.
- **Condition**: the `condition` string, or "—" if null.
- **Status**: use the `condition_status` field from the response ("always", "active", or "inactive").

**4.** Check for `verification_hooks` array in the response. If present and non-empty, display a separate section:

```
## Verification Hooks

| ID | Trigger | Target | Server | Condition | Status |
|----|---------|--------|--------|-----------|--------|
| verify-todoist-complete | todo_complete | todoist_verify_complete | todoist | todoist.enabled and todoist.auto_sync | active |
```

- Verification hooks are always blocking — omit the Blocking column.
- Include the `trigger` column since verification hooks are not grouped by trigger.
- **Condition** and **Status** follow the same rules as primary hooks.

**5.** After all sections, show a summary line:
`N hook(s) registered across M trigger(s). V verification hook(s).`

## Prerequisites

- Hooks plugin MCP server is running and reachable.

## Error Handling

- **Hooks MCP unavailable**: displays error from tool call and stops.
- **No hooks registered**: displays "No hooks registered. Run `/proj:hooks-add` to create one." and stops.

## Output

Hooks grouped by trigger tool in tables (ID, Target, Server, Blocking, Condition, Status). Separate section for verification hooks. Summary line with total counts.
