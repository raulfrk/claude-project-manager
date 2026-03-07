---
name: decompose
description: Break a large todo into smaller sub-todos based on its requirements and research. Use when asked "decompose 1", "break down 1", or "split 1 into subtasks".
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_get, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__todo_add_child, mcp__proj__todo_tree, mcp__proj__todo_block, mcp__proj__todo_update, mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__claude_ai_Todoist__add-tasks, mcp__sentry__find-projects, Task
argument-hint: "<todo-id>"
---

Decompose todo $ARGUMENTS into sub-todos.

1. Call `mcp__proj__todo_get` to get the todo.
2. Call `mcp__proj__content_get_requirements` to read requirements.md (if available).
3. Call `mcp__proj__content_get_research` to read research.md (if available).

3.5. **Assess atomicity** — before proposing any breakdown, evaluate whether this todo is already atomic (not meaningfully decomposable) using qualitative judgment based on:
   - **Title and notes** — is it a single focused operation, or does it span multiple distinct concerns?
   - **requirements.md** (if loaded) — does it specify separable phases or multiple unrelated systems?
   - **research.md** (if loaded) — does the research outline independent sub-problems?

   A todo is **atomic** if ALL of the following hold:
   - Single focused operation (e.g. edit one file, add one function, write one docs section)
   - Fits in one coding session with no multi-day scope
   - No distinct phases that are separable concerns (design + implement + test counted as one unless they touch unrelated systems)

   **When in doubt, do not auto-skip.** If borderline, proceed to step 4 and let the user decide via the normal confirmation prompt.

   If atomic: print `↩ Skipping decompose for <id> — already atomic.` and stop — do not proceed to steps 4–9.

4. Analyze the todo and propose a **multi-level** breakdown:
   - Identify 3-8 concrete root-level sub-tasks.
   - For each sub-task, assess if it is **large** (warrants nested children) or a **leaf** (single focused operation):
     - ✓ **Large** — contains 3+ distinct implementation phases (e.g. design, implement, test, deploy)
     - ✓ **Large** — touches 2+ unrelated systems/files (e.g. server code + SKILL.md + tests)
     - ✗ **Leaf** — single focused operation: edit one file, add one function, write one docs section
   - For large sub-tasks, propose 2-4 nested children inline. Apply the same large/leaf assessment recursively — nest as deep as needed.
   - Consider dependencies at all levels (which must come first?). Assign priorities to all tasks.
   - Each leaf sub-task should be implementable in a focused coding session.

4.5. **Analyze shared-file conflicts for safe batching:**

   **Goal**: Predict which files each subtodo will **write** and add `blocked_by` between any pair sharing a write target, so they never land in the same parallel batch.

   **Step A — Predict write files** using these heuristics:
   - **Research cross-reference**: If research.md names specific files, use those as ground truth.
   - **Same-module heuristic**: Subtodos touching the same Python module/package likely share `__init__.py`, shared type files, and import re-exports.
   - **Test co-location**: An implementation subtodo and its corresponding test subtodo share test files (`conftest.py`, fixtures, the test file itself).
   - **Implicit shared files**: Always check whether subtodos will touch common project-wide files:
     - `plugin.json`, `marketplace.json` (version bumps)
     - `CLAUDE.md`, `README.md` (docs updates)
     - `__init__.py` (module exports)
     - `conftest.py`, test fixtures (shared test infra)
     - SKILL.md files (skill instruction updates)
   - **Title overlap**: Subtodos whose titles reference the same system, feature, or file likely share write targets even if not explicitly stated.

   **Step B — Build conflict table** (internal, not shown to user):
   ```
   | Subtodo | Predicted write files       | Shares files with |
   |---------|-----------------------------|--------------------|
   | X.1     | models.py, __init__.py      | X.2                |
   | X.2     | models.py, test_models.py   | X.1                |
   | X.3     | tools.py                    | (none)             |
   ```

   **Step C — Add `blocked_by` relationships** for each pair sharing a write target:
   - The subtodo that lays groundwork blocks the one that builds on it.
   - When order is ambiguous, prefer the simpler/shallower subtodo as the blocker.
   - Record the shared filename — it will be shown in step 5's display.

   **Safety-first principle**: When in doubt whether two subtodos share a write target, **add the `blocked_by`**. False positives (unnecessary sequential execution) are far less costly than false negatives (parallel write conflicts that corrupt files).

   If no shared files are found after applying all heuristics, skip silently.

5. Present the proposed multi-level breakdown as **indented bullet points**:
   - Root tasks at level 0; each nesting level adds two spaces of indentation.
   - Format per line: `- 🔲 **ID** — title _(priority)_ [manual] [blocks X, blocked by Y]`
   - If a sub-todo is tagged `manual`, append `[manual]` after the priority.
   - For blocks added due to shared files (step 4.5), append the filename: `[blocks X (shared: filename.py)]`.
   - Children shown indented under their parent.

   Example:
   ```
   Proposed sub-todos for 1:
   - 🔲 **1.1** — Simple leaf task _(low)_
   - 🔲 **1.2** — Large task with phases _(high)_ [blocks 1.3 (shared: auth.py)]
     - 🔲 **1.2.1** — Phase A _(high)_
     - 🔲 **1.2.2** — Phase B _(medium)_
     - 🔲 **1.2.3** — Phase C _(medium)_
   - 🔲 **1.3** — Another leaf _(low)_ [blocked by 1.2 (shared: auth.py)]
   ```

6. Ask: "Does this breakdown look good? Any changes?" Allow the user to add, remove, rename, or restructure sub-todos at any level.

7. Create the confirmed todos — **parents before children**:
   - For each root-level sub-todo: call `mcp__proj__todo_add_child` on the parent todo.
   - For each nested child: call `mcp__proj__todo_add_child` on its immediate parent (using the ID returned from step 7 above).
   - For blocking relationships at any level: call `mcp__proj__todo_block`.

7.5. **Auto-sync new sub-todos to Todoist** (if enabled):
   - Call `mcp__proj__config_load`. If `todoist.enabled` is false or `auto_sync` is false: skip silently.
   - Call `mcp__proj__proj_get_active` to read `todoist_project_id` and `project.todoist.root_only`.
   - **Resolve `effective_root_only`**: `project.todoist.root_only ?? global.todoist.root_only ?? false`.
   - If `todoist_project_id` is null: call `mcp__sentry__find-projects`, present a numbered list of project names, ask "Which Todoist project should tasks for '<project name>' go to? (enter number)", then call `mcp__proj__proj_update_meta` with the chosen `todoist_project_id`. Use the chosen ID for the calls below.
   - Collect all newly created local todo IDs (from step 7) with their local parent IDs and the returned local IDs.
   - Push in depth order to handle parent→child linking:
     1. **Root subtodos** (parent = the decompose target): call `mcp__claude_ai_Todoist__add-tasks` in one bulk call.
        - Map each: `content` = title, `priority` = (high→p2, medium→p3, low→p4), `labels` = tags, `parentId` = the decompose target's `todoist_task_id` (if it has one), `projectId` = `todoist_project_id`.
        - For each returned task: call `mcp__proj__todo_update` to store `todoist_task_id`.
     2. **Nested children** (parent = another new subtodo): if `effective_root_only` is true, skip this step entirely — do not push child todos to Todoist. Otherwise, repeat with one bulk `add-tasks` call per depth level.
        - Use the `todoist_task_id` stored in the previous pass as their `parentId`.
        - For each returned task: call `mcp__proj__todo_update` to store `todoist_task_id`.
   - (If the decompose target itself lacks a `todoist_task_id`, omit `parentId` — the new subtodos will appear as top-level tasks in Todoist.)

8. Show the final tree via `mcp__proj__todo_tree`.

💡 Suggested next: (1) /proj:execute 1.1 — start with the first sub-todo  (2) /proj:run 1 — run the full workflow
