---
name: agents-list
description: List all agent overrides for the active project. Use when the user asks "what agents", "show agents", "list agents", or "agent overrides".
allowed-tools: mcp__proj__proj_get_agents
---

List all agent overrides.

1. Call `mcp__proj__proj_get_agents` (no arguments required).

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
