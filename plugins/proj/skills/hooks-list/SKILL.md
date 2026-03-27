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

**Step 1**: Call `mcp__hooks__hooks_list_tool` with optional `trigger_tool` filter.

**Step 2**: Parse the JSON response. If `hooks` array is empty:
- Output: "No hooks registered."
- Suggest: "Use `/proj:hooks-add` to register a new hook."
- Stop.

**Step 3**: Group hooks by `trigger_tool`. For each group, display a header and table:

```
## trigger_tool_name

| ID | Target | Server | Blocking | Condition | Status |
|----|--------|--------|----------|-----------|--------|
| hook-001 | target_tool | server_name | yes/no | condition or — | active/inactive/always |
```

- **Blocking**: "yes" if `blocking` is true, "no" otherwise.
- **Condition**: the `condition` string, or "—" if null.
- **Status**: use the `condition_status` field from the response ("always", "active", or "inactive").

**Step 4**: After the table, show a summary line:
`N hook(s) registered across M trigger(s).`
