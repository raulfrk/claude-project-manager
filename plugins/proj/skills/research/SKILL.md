---
name: research
description: Research implementation approach for one or more todos. For a single todo uses an isolated Explore agent. For multiple todos spawns parallel Explore agents. Use when asked "research 1", "how do I implement 1", or "research all pending todos".
disable-model-invocation: "true"
context: fork
agent: Explore
allowed-tools: mcp__proj__proj_get_todo_context, mcp__proj__content_set_research, mcp__proj__todo_set_content_flag, Read, Glob, Grep, WebSearch, WebFetch, mcp__proj__proj_resolve_agent, Task
argument-hint: "<todo-id> [or 'all' or '1,2,3']"
---

**Agent resolution (run first):**
1. Call `mcp__proj__proj_resolve_agent` with `step="research"` (and `project_name` if known)
2. Parse the JSON result: `{"agent": "<name>", "warning": "<msg or null>"}`
3. If `warning` is non-null: display it to the user before proceeding
4. If `agent` is `"Explore"`: proceed with the normal skill instructions below
5. If `agent` differs: use the Task tool to spawn an agent of type `agent` with the full skill instructions below (replacing $ARGUMENTS with the actual todo ID), then return its result

Research implementation approach for: $ARGUMENTS

**If a single todo ID is provided** (e.g. `/proj:research 1`):

**Guard:** If `$ARGUMENTS` is empty or blank, stop immediately and output:
> Todo ID required. Usage: /proj:research <todo-id>

1. Call `mcp__proj__proj_get_todo_context` with the todo ID to get the todo, requirements, and research in one call. If the tool returns not-found, stop and output: "Todo <id> not found." If the todo has a non-empty `notes` field, treat it as additional context (e.g. description pulled from Todoist) — it may contain design constraints or prior decisions that should inform your research.
2. Research the implementation approach:
   - Explore the codebase for existing patterns (Read, Glob, Grep)
   - Research external libraries or APIs if needed (WebSearch, WebFetch)
   - Consider 2-3 different approaches
3. Write a structured `research.md`:
   ```markdown
   # Research: <todo title>

   ## Approach Options
   ### Option 1: <name>
   <description, pros, cons>

   ### Option 2: <name>
   <description, pros, cons>

   ## Recommended Approach
   <which option and why>

   ## Key Dependencies
   - <library/API/file>

   ## Risks
   - <risk 1>

   ## References
   - <link or file path>
   ```
4. Call `mcp__proj__content_set_research` with the content.
5. Call `mcp__proj__todo_set_content_flag` with `has_research=True`.

**If multiple todos are provided** (e.g. `/proj:research all` or `/proj:research 1,2`):

The skill runs in the main conversation (not a fork) for multiple todos.
Spawn one parallel Explore Task agent per todo, each receiving the todo title and requirements.
Collect all research results and write each `research.md`.
If a Task agent fails (error or timeout), log the failure for that todo ID and continue processing remaining todos. At the end, report any failed todo IDs in a summary.

💡 Suggested next: (1) /proj:decompose <id> — break into subtasks based on research  (2) /proj:execute <id> — implement using the research findings
