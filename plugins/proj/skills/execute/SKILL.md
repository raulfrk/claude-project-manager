---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, Task, EnterPlanMode, ExitPlanMode
argument-hint: "[todo-id | range] e.g. 1 or 2-4"
---

Execute todo(s): $ARGUMENTS

**Determine scope from $ARGUMENTS:**
- Empty → call `mcp__proj__todo_list` with `status="in_progress"` to find any in-progress todo;
  if none, call `mcp__proj__todo_list` with `status="ready"`. Display the results and proceed
  with the first (or ask the user if multiple).
- Single ID (e.g. `1`) → execute that todo
- Range (e.g. `2-4`) → execute those todos

**For a single todo:**

1. Call `mcp__proj__todo_check_executable` with the todo ID.
   - If the result starts with "⚠️", display it as-is and **stop** — do not implement.
   - If the result is JSON, continue normally.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
   This returns the todo, its requirements, its research, and (if present) the parent todo in one call.
3. Call `EnterPlanMode`. Read all loaded context (requirements.md, research.md, notes) and explore the relevant source files. Create an implementation plan covering:
   - Files to modify/create
   - Key changes per file
   - Implementation order
   - Testing approach

   Call `ExitPlanMode` to present the plan for user review. The user will approve or request changes before you proceed.
4. Before implementing: call `mcp__proj__todo_update` with `status="in_progress"` to mark the todo as in_progress. Then review all context and implement the task. If the todo has a non-empty `notes` field, treat it as additional implementation context (e.g. constraints or design decisions pulled from Todoist) — it should inform your implementation approach.
5. On completion:
   - Call `mcp__proj__todo_complete`
   - If Todoist enabled: call `mcp__{todoist.mcp_server}__complete-tasks`
   - Update CLAUDE.md if relevant: `mcp__proj__claudemd_write`
   - Append a brief progress note: `mcp__proj__notes_append`

**For a range with independent todos (no blocked_by between them):**

Phase 1 — Plan (sequential, in main conversation):
For each todo in the range:
1. Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
3. Call `EnterPlanMode`. Create an implementation plan for this todo covering files to modify/create, key changes, implementation order, and testing approach.
4. Call `ExitPlanMode` for user review. The user will approve or request changes before moving to the next todo.

Phase 2 — Execute (parallel Task agents):
After all plans are approved, spawn one `general-purpose` Task agent per todo (excluding manual-skipped ones).
Each agent receives: the todo details, its requirements.md, its research.md, parent context, AND the approved implementation plan.
Each agent implements according to its approved plan and calls `todo_complete` when done.
Main conversation collects results and reports summary, including any skipped manual todos.

**For a range with dependencies:**

Phase 1 — Plan (sequential, in dependency order):
Execute in topological order (respect blocked_by chains). For each todo:
1. Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
2. Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
3. Call `EnterPlanMode`. Create an implementation plan for this todo.
4. Call `ExitPlanMode` for user review.

Phase 2 — Execute (sequential, in dependency order):
Execute each todo according to its approved plan, one at a time (respecting blocked_by chains). Each todo: mark in_progress, implement per plan, call `todo_complete` when done.

**Note:** Root todo execution does NOT auto-recurse into children. To execute children, specify their IDs explicitly.

💡 Suggested next: (1) /proj:save — save session and reconcile git  (2) /proj:status — see updated project overview
