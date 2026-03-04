---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, mcp__proj__proj_get_active, mcp__claude_ai_Todoist__complete-tasks, mcp__proj__config_load, Task, mcp__proj__proj_resolve_agent
argument-hint: "[todo-id | range] e.g. 1 or 2-4"
---

**Agent resolution (run first):**
1. Call `mcp__proj__proj_resolve_agent` with `step="execute"` (and `project_name` if known)
2. Parse the JSON result: `{"agent": "<name>", "warning": "<msg or null>"}`
3. If `warning` is non-null: display it to the user before proceeding
4. If `agent` is `"general-purpose"`: proceed with the normal skill instructions below
5. If `agent` differs: use the Task tool to spawn an agent of type `agent` with the full skill instructions below (replacing $ARGUMENTS with the actual todo ID), then return its result

Execute todo(s): $ARGUMENTS

**Determine scope from $ARGUMENTS:**
- Empty → execute the currently in-progress or next ready todo
- Single ID (e.g. `1`) → execute that todo
- Range (e.g. `2-4`) → execute those todos

**For a single todo:**

1. Call `mcp__proj__todo_check_executable` with the todo ID.
   - If the result starts with "⚠️", display it as-is and **stop** — do not implement.
   - If the result is JSON, continue normally.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
   This returns the todo, its requirements, its research, and (if present) the parent todo in one call.
3. Review all context, then implement the task. If the todo has a non-empty `notes` field, treat it as additional implementation context (e.g. constraints or design decisions pulled from Todoist) — it should inform your implementation approach.
6. On completion:
   - Call `mcp__proj__todo_complete`
   - If Todoist enabled: call `mcp__claude_ai_Todoist__complete-tasks`
   - Update CLAUDE.md if relevant: `mcp__proj__claudemd_write`
   - Append a brief progress note: `mcp__proj__notes_append`

**For a range with independent todos (no blocked_by between them):**

- Spawn one `general-purpose` Task agent per todo using the Task tool
- Each agent receives: the todo details, its requirements.md, its research.md, and parent context
- Each agent MUST call `mcp__proj__todo_check_executable` before implementing. If the result starts with "⚠️", skip execution (do NOT call `todo_complete`) and include `⚠️ Todo <id> [manual] — skipped execute` in the result.
- Each agent executes independently and calls `todo_complete` when done (unless skipped)
- Main conversation collects results and reports summary, including any skipped manual todos

**For a range with dependencies:**

- Execute in topological order (respect blocked_by chains)
- Before executing each todo in the sequence, call `mcp__proj__todo_check_executable`. If the result starts with "⚠️", skip that todo (do NOT call `todo_complete`) and note it as `⚠️ Todo <id> [manual] — skipped execute`.
- Run sequentially, one at a time

**Note:** Root todo execution does NOT auto-recurse into children. To execute children, specify their IDs explicitly.

💡 Suggested next: (1) /proj:update — record progress and reconcile with git  (2) /proj:status — see updated project overview
