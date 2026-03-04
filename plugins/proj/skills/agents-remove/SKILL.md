---
name: agents-remove
description: Remove an agent override for a project step. Use when the user says "remove agent", "clear agent", or "reset <step> to default".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_remove_agent, mcp__proj__proj_get_agents
argument-hint: "[step]"
---

Remove an agent override for a project step. Arguments: $ARGUMENTS (required — step name)

1. Parse $ARGUMENTS for the step name. If missing, ask:
   - "Which step to clear? (research, decompose, define, or execute)"

2. Call `mcp__proj__proj_remove_agent` with the step.

3. On success: confirm the override was removed and show the updated agent listing via `mcp__proj__proj_get_agents`.

4. On error (invalid step): surface the error message clearly.

💡 Suggested next:
(1) /proj:agents-list — verify the change
(2) /proj:agents-set — set a different agent
