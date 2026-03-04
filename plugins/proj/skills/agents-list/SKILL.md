---
name: agents-list
description: List all agent overrides for the active project. Use when the user asks "what agents", "show agents", "list agents", or "agent overrides".
allowed-tools: mcp__proj__proj_get_agents
disable-model-invocation: "true"
---

List all agent overrides for the active project.

The default agent types are "general-purpose" (for research and execute steps) and "Plan" (for decompose and define steps).

1. Call `mcp__proj__proj_get_agents` (no arguments required).
   - If this fails or returns an error (no active project), stop and output:
     "No active project loaded. Run /proj:load to select a project first."

2. Display the result clearly showing:
   - All 4 steps (research, decompose, define, execute)
   - Override agent name if set, or "(default: <type>)" if using default
   - Example output format:
     ```
     ## Agent Overrides

     - research: my-research-agent
     - decompose: (default: Plan)
     - define: my-define-agent
     - execute: (default: general-purpose)
     ```

💡 Suggested next: /proj:agents-set — override an agent
