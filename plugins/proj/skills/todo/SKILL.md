---
name: todo
description: Manage project todos — add, complete, list, view tree, set dependencies, delete. Use when the user says "add todo", "mark done", "list todos", "show todo tree", or "1 blocks 2".
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_add, mcp__proj__todo_list, mcp__proj__todo_get, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_block, mcp__proj__todo_unblock, mcp__proj__todo_delete, mcp__proj__todo_ready, mcp__proj__todo_tree, mcp__claude_ai_Todoist__add-tasks, mcp__claude_ai_Todoist__complete-tasks, mcp__claude_ai_Todoist__update-tasks, mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__sentry__find-projects
argument-hint: "[add|update|done|list|tree|block|unblock|delete] [args]"
---

Manage project todos. Parse $ARGUMENTS to determine the operation:

**add** `<title>` — add a new todo
  - **Smart parent inference**: if the title starts with a number (e.g. `3 Fix bug` or `4.2 Improve error handling`), check whether that ID is an existing todo:
    - Extract the leading token matching `^\d+(\.\d+)*` followed by a space
    - Call `mcp__proj__todo_get` with that token as the ID
    - If the todo exists: pass `parent=<token>` and `title=<rest of string>` to `todo_add`
    - If the todo does not exist: use the full original string as the title, no parent
  - Ask for priority (default: from config), tags (optional), blocked_by (optional)
  - Ask: "Due date? (optional, e.g. 'tomorrow', '2026-06-01')" — if the user provides a value, store it as `due_date`; if skipped, leave unset.
  - Call `mcp__proj__todo_add` — include `due_date=<value>` if the user provided one.
  - If Todoist auto_sync:
    - Call `mcp__proj__proj_get_active` to read `todoist_project_id`.
    - If `todoist_project_id` is null: call `mcp__sentry__find-projects`, present a numbered list of project names, ask "Which Todoist project should tasks for '<project name>' go to? (enter number)", then call `mcp__proj__proj_update_meta` with the chosen `todoist_project_id`. Use the chosen ID for this call.
    - Call `mcp__claude_ai_Todoist__add-tasks` with content (title), priority (local→Todoist mapped: high→p2, medium→p3, low→p4), labels (from tags — pass the tags list directly as labels), `projectId` = `todoist_project_id`, and — if `due_date` was set — `dueString` = `<due_date value>`.
    - Store the returned task ID: call `mcp__proj__todo_update` with `todo_id=<local todo id>` and `todoist_task_id=<id returned by add-tasks>`.

**update** `<id> [tags=tag1,tag2 | title=... | priority=... | notes=... | due_date=...]` — update a todo's fields
  - Parse the key=value pairs from the arguments
  - Call `mcp__proj__todo_update` with the provided fields
  - If Todoist auto_sync AND the todo has a `todoist_task_id`:
    - If `tags` were changed: include `labels` set to the new tags list (full replacement) in the Todoist update
    - If `notes` were changed: include `description` set to the new notes value in the Todoist update (immediately pushes to Todoist without waiting for `/proj:sync`)
    - If `due_date` was changed: include `dueString` set to the new `due_date` value in the Todoist update
    - Combine all changed fields into a single `mcp__claude_ai_Todoist__update-tasks` call
  - Show the updated todo

**done** `<id>` — mark a todo complete (e.g. "done 2")
  - Call `mcp__proj__todo_complete`
  - If Todoist auto_sync: call `mcp__claude_ai_Todoist__complete-tasks`

**list** [all|pending|ready|blocked] — list todos with optional filter
  - Default (no filter): call `mcp__proj__todo_list` with `status: "pending"` — shows only open tasks (pending + in_progress)
  - `all`: call `mcp__proj__todo_list` with no status filter — shows all todos including done
  - `ready`: call `mcp__proj__todo_ready` — shows todos with no blockers
  - `blocked`: call `mcp__proj__todo_list` with `status: "pending"` then filter to those with non-empty `blocked_by`
  - Display as bullet points with status icons (✅ = done, 🔄 = in_progress, 🔲 = pending), bold ID, title, priority in italics. Show children indented 2 spaces under their parent. If `"manual" in tags`, append `[manual]` after the priority. Blocked todos include `[blocked by X]` inline. Order: `_(priority)_ [manual] [blocked by X]`.
  - Example:
    ```
    - 🔄 **2** — Write MCP server _(high)_
    - 🔲 **3** — Write skills _(medium)_ [manual]
    - 🔲 **4** — Integration tests _(medium)_ [blocked by 2]
    ```

**tree** — show todos as a hierarchy
  - Call `mcp__proj__todo_tree`
  - Render as nested bullet points with 2-space indent per level. Apply the same status icons, bold ID, and inline metadata as `list` (including `[manual]` badge for manual-tagged todos).
  - Example:
    ```
    - ✅ **1** — Implement storage layer _(medium)_
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write tests _(low)_
    ```

**block** `1 blocks 2` — set blocking relationship
  - Call `mcp__proj__todo_block`

**unblock** `<id>` — remove a blocking relationship
  - Call `mcp__proj__todo_unblock`

**delete** `<id>` — delete a todo
  - Confirm before deleting
  - Call `mcp__proj__todo_delete`

If $ARGUMENTS is empty or ambiguous, ask the user what they'd like to do.
Always confirm the action taken and show the resulting todo.

💡 After adding a vague todo → suggest /proj:define <id>
   After adding a technical todo → suggest /proj:research <id>
   After completing a todo → suggest /proj:status for overview
