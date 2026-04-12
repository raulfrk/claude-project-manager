---
name: list
description: List all registered MCP-to-MCP hooks, grouped by trigger tool, showing status and routing info.
allowed-tools: mcp__plugin_router_router__router_list_tool
argument-hint: "[trigger_tool]"
context: fork
agent: general-purpose
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

List all registered hooks from hooks registry.

**Parse $ARGUMENTS**: trigger tool name provided → pass as `trigger_tool` filter. Empty → list all.

**1.** `mcp__plugin_router_router__router_list_tool` w/ opt `trigger_tool` filter.

**2.** Parse JSON. Empty `hooks` array → output "No hooks registered. Run `/router:add` to create one." Stop.

**3.** Group hooks by `trigger_tool`. Each group: header + table:

```
## trigger_tool_name

| ID | Target | Server | Blocking | Condition | Status |
|----|--------|--------|----------|-----------|--------|
| hook-001 | target_tool | server_name | yes/no | condition or — | active/inactive/always |
```

- Blocking: `blocking` true → "yes", else "no"
- Condition: `condition` string or "—" if null
- Status: `condition_status` field ("always", "active", "inactive", "runtime")

**4.** Check `verification_hooks` array. Present + non-empty → separate section:

```
## Verification Hooks

| ID | Trigger | Target | Server | Condition | Status |
|----|---------|--------|--------|-----------|--------|
| verify-todoist-complete | todo_complete | todoist_verify_complete | todoist | todoist.enabled and todoist.auto_sync | active |
```

- Verification hooks always blocking — omit Blocking column
- Include `trigger` column (not grouped by trigger)
- Condition/Status: same rules as primary hooks

**5.** Summary: `N hook(s) registered across M trigger(s). V verification hook(s).`

## Prerequisites

Router plugin MCP server running + reachable.

## Error Handling

- Router MCP unavailable → show err, stop
- No hooks → "No hooks registered. Run `/router:add` to create one." Stop.

## Output

Hooks grouped by trigger in tables (ID, Target, Server, Blocking, Condition, Status). Separate section for verification hooks. Summary line w/ totals.
