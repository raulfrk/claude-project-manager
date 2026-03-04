---
name: agents-set
description: Set a specialized agent override for a project step. Use when the user says "set agent for", "use <agent-name> for", or "agent <step> <agent-name>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_set_agent, mcp__proj__proj_get_agents
argument-hint: "[step] [agent-name]"
---

Set an agent override for a project step. Arguments: $ARGUMENTS (required — step and agent name)

1. Parse $ARGUMENTS for `<step>` and `<agent-name>`. If either is missing, ask:
   - "Which step? (research, decompose, define, or execute)"
   - "Agent name? (the .md filename in .claude/agents/, without the .md extension)"

2. Call `mcp__proj__proj_set_agent` with the step and agent name.

3. On success: confirm the override was set and show the updated agent listing via `mcp__proj__proj_get_agents`.

4. On error (invalid step or missing agent file): surface the error message clearly to the user.

💡 Suggested next:
(1) /proj:agents-list — see all agent overrides
(2) /proj:agents-remove — remove an override
