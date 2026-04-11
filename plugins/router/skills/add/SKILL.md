---
name: add
description: Register a new MCP-to-MCP hook linking a trigger tool to a target tool on a server.
allowed-tools: mcp__plugin_router_router__router_register_tool
argument-hint: "<trigger_tool> <target_tool> <server> [param_mapping=JSON] [blocking=true|false] [condition=EXPR] [--verification] [feedback_mapping=JSON] [feedback_tool=TOOL]"
context: fork
agent: general-purpose
---

Register a new hook in the hooks registry.

**Parse $ARGUMENTS** for these fields:
- `trigger_tool` (required) — the MCP tool that fires the hook
- `target_tool` (required) — the MCP tool to call when triggered
- `server` (required) — the MCP server hosting the target tool
- `param_mapping` (optional) — JSON string mapping target params to source fields using `${}` templates, default `{}`
- `blocking` (optional) — `true` or `false`, default `false`
- `condition` (optional) — expression to gate the hook, default `null`
- `--verification` (optional flag) — register as a verification hook (runs after primary hooks to check expected state was achieved)
- `feedback_mapping` (optional) — JSON string mapping result dot-paths to target param names for automatic writeback, default `{}`
- `feedback_tool` (optional) — the tool on the trigger's server to call with the mapped results

If $ARGUMENTS is empty or missing required fields, run interactive Q&A:
1. "What tool should trigger this hook?" (trigger_tool)
2. "What tool should be called?" (target_tool)
3. "Which MCP server hosts the target tool?" (server)
4. "Param mapping as JSON (or leave empty for `{}`):" (param_mapping)
5. "Should the trigger wait for the target to complete? (yes/no, default: no)" (blocking)
6. "Condition expression to gate execution (or leave empty):" (condition)
7. "Is this a verification hook? (yes/no, default: no)" (verification)
8. "Do you want feedback writeback? (yes/no, default: no)" — if yes:
   - "Feedback mapping as JSON (e.g. `{"result.id": "task_id"}`): " → feedback_mapping
   - "Feedback tool name (the tool on the trigger's server to call with results): " → feedback_tool
   - If blocking=false was set and verification is NOT true: auto-set blocking=true with warning "Feedback requires blocking=true — overriding your blocking setting"
   - If feedback_mapping is {} (empty) but feedback_tool is set: warn "No params will be mapped to feedback_tool — is this intentional? (yes/no)" and proceed only on yes
   - Both feedback_mapping and feedback_tool are required together; prompt for the missing one if only one is provided

**Register**: Call `mcp__plugin_router_router__router_register_tool` with the collected values. If `--verification` flag is present or the user answered yes to the verification question, pass `verification=True`. If `feedback_mapping` and `feedback_tool` have been provided (non-default), include them in the register call parameters.

**On success**, display the created hook:
```
Registered hook <id>:
  trigger: <trigger_tool>
  target:  <target_tool> @ <server>
  mapping: <param_mapping>
  blocking: yes/no
  verification: yes/no
  condition: <condition or none>
  feedback_mapping: <value>   (only when feedback was configured)
  feedback_tool: <value>      (only when feedback was configured)
```

**On error** (duplicate, cycle, invalid JSON), display the error message from the tool response.

## Prerequisites

- Router plugin MCP server is running and reachable.

## Error Handling

- **No arguments and not interactive**: starts interactive Q&A to collect required fields.
- **Duplicate hook**: displays error from `router_register_tool`.
- **Cycle detected**: displays error from `router_register_tool`.
- **Invalid param_mapping JSON**: displays error from `router_register_tool`.
- **Router MCP unavailable**: displays error from tool call and stops.

## Output

On success: registered hook details (ID, trigger, target, server, mapping, blocking, verification, condition). On error: error message from tool.
