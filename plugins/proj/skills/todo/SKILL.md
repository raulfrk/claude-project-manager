---
name: todo
description: Manage project todos — add, complete, list, view tree, set dependencies, delete. Use when the user says "add todo", "mark done", "list todos", "show todo tree", or "1 blocks 2".
disable-model-invocation: "true"
allowed-tools: mcp__proj__todo_add, mcp__proj__todo_list, mcp__proj__todo_get, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_block, mcp__proj__todo_unblock, mcp__proj__todo_delete, mcp__proj__todo_ready, mcp__proj__todo_tree, mcp__proj__config_load, mcp__proj__proj_get_active, mcp__proj__proj_update_meta, mcp__proj__tracking_git_flush
argument-hint: "[add|update|done|list|tree|block|unblock|delete] [args]"
context: fork
agent: general-purpose
---

Manage project todos. Parse $ARGUMENTS to determine the operation:

**First**: Call `mcp__proj__proj_get_active` to get the active project name. Pass this `project_name` to all subsequent `mcp__proj__todo_*` tool calls.

**add** `<title>` — add a new todo
  - **Smart parent inference**: if the title starts with a number (e.g. `3 Fix bug` or `4.2 Improve error handling`), check whether that ID is an existing todo:
    - Extract the leading token matching `^\d+(\.\d+)*` followed by a space
    - Call `mcp__proj__todo_get` with that token as the ID
    - If the todo exists: pass `parent=<token>` and `title=<rest of string>` to `todo_add`
    - If the todo does not exist: use the full original string as the title, no parent
  - Parse optional inline params from the remaining arguments after the title:
    `priority=<high|medium|low>`, `tags=<tag1,tag2>`, `blocked_by=<id1,id2>`, `due=<date>`
  - Defaults: priority from config (via `mcp__proj__config_load`), no tags, no blocks, no due date
  - Call `mcp__proj__todo_add` with parsed values. Include `due_date=<value>` if `due` param was provided.
  - If Todoist auto_sync:
    - Call `mcp__proj__proj_get_active` to read `todoist_project_id`.
    - If `todoist_project_id` is null: stop with "Todoist project not linked. Set todoist_project_id via mcp__proj__proj_update_meta first."
    - Call `mcp__{todoist.mcp_server}__add-tasks` with content (title), priority (local to Todoist mapped: high->p2, medium->p3, low->p4), labels (from tags -- pass the tags list directly as labels), `projectId` = `todoist_project_id`, and -- if `due` was set -- `dueString` = `<due value>`.
    - Store the returned task ID: call `mcp__proj__todo_update` with `todo_id=<local todo id>` and `todoist_task_id=<id returned by add-tasks>`.

**update** `<id> [tags=tag1,tag2 | title=... | priority=... | notes=... | due_date=...]` — update a todo's fields
  - Parse the key=value pairs from the arguments
  - Call `mcp__proj__todo_update` with the provided fields
  - If Todoist auto_sync AND the todo has a `todoist_task_id`:
    - If `tags` were changed: include `labels` set to the new tags list (full replacement) in the Todoist update
    - If `notes` were changed: include `description` set to the new notes value in the Todoist update (immediately pushes to Todoist without waiting for `/proj:sync`)
    - If `due_date` was changed: include `dueString` set to the new `due_date` value in the Todoist update
    - Combine all changed fields into a single `mcp__{todoist.mcp_server}__update-tasks` call
  - Show the updated todo

**done** `<id>` — mark a todo complete (e.g. "done 2")
  - Call `mcp__proj__todo_complete`
  - If Todoist auto_sync: call `mcp__{todoist.mcp_server}__complete-tasks`

**list** [all|pending|ready|blocked] — list todos with optional filter
  - Default (no filter): call `mcp__proj__todo_tree` — shows open tasks as a hierarchy, filtering out done todos
  - `all`: call `mcp__proj__todo_tree` — shows all todos including done as a hierarchy
  - `ready`: call `mcp__proj__todo_ready` — shows todos with no blockers as a flat list
  - `blocked`: call `mcp__proj__todo_list` with `status: "pending"` then filter to those with non-empty `blocked_by`
  - Display as nested bullet points with 2-space indent per level. Use status icons (✅ = done, 🔄 = in_progress, 🔲 = pending), bold ID, title, priority in italics. Always use the full, exact title from the todo — never abbreviate or summarize. If `"manual" in tags`, append `[manual]` after the priority. Blocked todos include `[blocked by X]` inline. Order: `_(priority)_ [manual] [blocked by X]`.
  - Example:
    ```
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write skills _(medium)_
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

**delete** `<id>` -- delete a todo
  - Call `mcp__proj__todo_delete`

If $ARGUMENTS is empty or ambiguous, output usage: "Usage: /proj:todo [add|update|done|list|tree|block|unblock|delete] [args]"
Always confirm the action taken and show the resulting todo.

**Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Todo update"`.

💡 After adding a vague todo → suggest /proj:define <id>
   After adding a technical todo → suggest /proj:define <id>
   After completing a todo → suggest /proj:status for overview
