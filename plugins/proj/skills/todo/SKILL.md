---
name: todo
description: Manage project todos — add, complete, list, view tree, set dependencies, delete. Use when the user says "add todo", "mark done", "list todos", "show todo tree", or "1 blocks 2".
allowed-tools: mcp__proj__todo_add, mcp__proj__todo_list, mcp__proj__todo_get, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_block, mcp__proj__todo_unblock, mcp__proj__todo_delete, mcp__proj__todo_ready, mcp__proj__todo_tree, mcp__proj__proj_session_context, mcp__proj__proj_update_meta, mcp__proj__tracking_git_flush
argument-hint: "[add|update|done|list|tree|block|unblock|delete] [args]"
context: fork
agent: general-purpose
---

Manage project todos. Parse $ARGUMENTS to determine the operation:

**First**: Call `mcp__proj__proj_session_context` to get the active project name, config, and integration settings. Extract `project.name` and pass it to all subsequent `mcp__proj__todo_*` tool calls. Use `config.default_priority` for default priority and `integrations.trello` for sync checks.

**add** `<title>` — add a new todo
  - **Smart parent inference**: if the title starts with a number (e.g. `3 Fix bug` or `4.2 Improve error handling`), check whether that ID is an existing todo:
    - Extract the leading token matching `^\d+(\.\d+)*` followed by a space
    - Call `mcp__proj__todo_get` with that token as the ID
    - If the todo exists: pass `parent=<token>` and `title=<rest of string>` to `todo_add`
    - If the todo does not exist: use the full original string as the title, no parent
  - Parse optional inline params from the remaining arguments after the title:
    `priority=<high|medium|low>`, `tags=<tag1,tag2>`, `blocked_by=<id1,id2>`, `due=<date>`
  - Defaults: priority from config (`config.default_priority` from session context), no tags, no blocks, no due date
  - If Trello auto-sync (`integrations.trello.enabled` and project has `trello_card_id` from session context):
    - Determine checklist: if parent todo has `trello_checklist_id`, use that. Otherwise call `mcp__trello__get_card_checklists(card_id)` to find existing "Tasks" checklist; if none, call `mcp__trello__create_checklist(card_id, name="Tasks")` and store `trello_checklist_id` on the root todo.
    - Call `mcp__trello__add_checklist_item(checklist_id, name=title)`
    - Capture the returned item ID as `trello_checklist_item_id`.
  - Call `mcp__proj__todo_add` with parsed values. Include `due_date=<value>` if `due` param was provided. Include `trello_checklist_item_id` if captured above.

**update** `<id> [tags=tag1,tag2 | title=... | priority=... | notes=... | due_date=...]` — update a todo's fields
  - Parse the key=value pairs from the arguments
  - Call `mcp__proj__todo_update` with the provided fields
  - If Trello auto-sync AND todo has `trello_checklist_item_id`:
    - If `title` was changed: call `mcp__trello__rename_checklist_item(card_id, checklist_id, item_id, name=new_title)` where card_id comes from project's `trello_card_id`, checklist_id from todo's parent's `trello_checklist_id`
  - Show the updated todo

**done** `<id>` — mark a todo complete (e.g. "done 2")
  - Call `mcp__proj__todo_complete`
  - If Trello auto-sync AND todo has `trello_checklist_item_id`:
    - Call `mcp__trello__update_checklist_item(card_id, checklist_id, item_id, state="complete")` where card_id from project's `trello_card_id`

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
  - Before deleting, call `mcp__proj__todo_get` to read the todo's `trello_checklist_item_id` for the Trello delete call.
  - Call `mcp__proj__todo_delete`
  - If Trello auto-sync AND todo has `trello_checklist_item_id`:
    - Call `mcp__trello__delete_checklist_item(card_id, checklist_id, item_id)` where card_id from project's `trello_card_id`

If $ARGUMENTS is empty or ambiguous, output usage: "Usage: /proj:todo [add|update|done|list|tree|block|unblock|delete] [args]"
Always confirm the action taken and show the resulting todo.

**Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Todo update"`.

💡 After adding a vague todo → suggest /proj:define <id>
   After adding a technical todo → suggest /proj:define <id>
   After completing a todo → suggest /proj:status for overview
