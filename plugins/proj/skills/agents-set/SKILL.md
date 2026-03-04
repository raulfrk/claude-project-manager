---
name: agents-set
description: Set a specialized agent override for a project step. Use when the user says "set agent for", "use <agent-name> for", or "agent <step> <agent-name>".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_set_agent, mcp__proj__proj_get_agents
argument-hint: "[step] [agent-name]"
---

Set an agent override for a project step. Arguments: $ARGUMENTS (required — step and agent name)

1. Parse $ARGUMENTS for `<step>` and `<agent-name>`. If either is missing, ask:
   - "Which step? (define, research, decompose, or execute)"
   - "Agent name? (the .md filename in .claude/agents/, without the .md extension)"
   Validate `<step>` against the list `[define, research, decompose, execute]`. If invalid, stop and reply:
   "Invalid step '<step>'. Valid values: define, research, decompose, execute."

2. Check that there is an active project. If not, stop with: "No active project. Run /proj:load first."

3. Call `mcp__proj__proj_set_agent` with the step and agent name.

4. On success: print the confirmation line "Agent override set: step=`<step>`, agent=`<agent-name>` (project: `<project-name>`)." then show the full updated listing via `mcp__proj__proj_get_agents`.

5. On error (missing agent file or other failure): surface the error message clearly to the user.

💡 Suggested next:
(1) /proj:agents-list — see all agent overrides
(2) /proj:agents-remove — remove an override
