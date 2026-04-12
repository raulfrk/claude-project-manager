---
name: add
description: Register a new MCP-to-MCP hook linking a trigger tool to a target tool on a server.
allowed-tools: mcp__plugin_router_router__router_register_tool
argument-hint: "<trigger_tool> <target_tool> <server> [param_mapping=JSON] [blocking=true|false] [condition=EXPR] [--verification] [feedback_mapping=JSON] [feedback_tool=TOOL]"
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Register new hook in hooks registry.

**Parse $ARGUMENTS** for fields:
- `trigger_tool` (req) — MCP tool firing hook
- `target_tool` (req) — MCP tool called when triggered
- `server` (req) — MCP server hosting target
- `param_mapping` (opt) — JSON mapping target params to source fields via `${}` templates, default `{}`
- `blocking` (opt) — `true`/`false`, default `false`
- `condition` (opt) — expression gating hook, default `null`
- `--verification` (opt flag) — register as verification hook (runs after primary hooks to check expected state)
- `feedback_mapping` (opt) — JSON mapping result dot-paths to target param names for auto writeback, default `{}`
- `feedback_tool` (opt) — tool on trigger's server called w/ mapped results

$ARGUMENTS empty/missing req fields → interactive Q&A:
1. "What tool triggers this hook?" (trigger_tool)
2. "What tool gets called?" (target_tool)
3. "Which MCP server hosts target?" (server)
4. "Param mapping as JSON (or empty for `{}`):" (param_mapping)
5. "Should trigger wait for target? (yes/no, default: no)" (blocking)
6. "Condition expression gating exec (or empty):" (condition)
7. "Verification hook? (yes/no, default: no)" (verification)
8. "Want feedback writeback? (yes/no, default: no)" — if yes:
 - "Feedback mapping as JSON (e.g. `{"result.id": "task_id"}`): " → feedback_mapping
 - "Feedback tool name (tool on trigger's server called w/ results): " → feedback_tool
 - blocking=false + not verification → auto-set blocking=true w/ warning "Feedback requires blocking=true — overriding blocking setting"
 - feedback_mapping={} but feedback_tool set → warn "No params mapped to feedback_tool — intentional? (yes/no)", proceed only on yes
 - Both feedback_mapping + feedback_tool req together; prompt missing one if only one provided

**Register**: `mcp__plugin_router_router__router_register_tool` w/ collected vals. `--verification` flag or user answered yes → pass `verification=True`. If `feedback_mapping` + `feedback_tool` non-default → include in register call.

**On success**:
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

**On error** (duplicate/cycle/invalid JSON) → show err msg from tool response.

## Prerequisites

Router plugin MCP server running + reachable.

## Error Handling

- No args, not interactive → starts interactive Q&A
- Duplicate/cycle/invalid JSON → show err from `router_register_tool`
- Router MCP unavailable → show err, stop

## Output

Success: hook details (ID, trigger, target, server, mapping, blocking, verification, condition). Error: err msg from tool.
