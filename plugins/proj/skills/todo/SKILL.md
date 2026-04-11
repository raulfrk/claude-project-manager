---
name: todo
description: Manage project todos — add, complete, list, view tree, set dependencies, delete. Use when the user says "add todo", "mark done", "list todos", "show todo tree", or "1 blocks 2".
allowed-tools: mcp__plugin_proj_proj__todo_add, mcp__plugin_proj_proj__todo_list, mcp__plugin_proj_proj__todo_get, mcp__plugin_proj_proj__todo_update, mcp__plugin_proj_proj__todo_complete, mcp__plugin_proj_proj__todo_block, mcp__plugin_proj_proj__todo_unblock, mcp__plugin_proj_proj__todo_delete, mcp__plugin_proj_proj__todo_ready, mcp__plugin_proj_proj__todo_tree, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__proj_update_meta, mcp__plugin_proj_proj__tracking_git_flush, mcp__plugin_proj_proj__proj_identify_batches
argument-hint: "[add|update|done|list|tree|block|unblock|delete] [args]"
---

Manage project todos. Parse $ARGUMENTS to determine the operation:

**First**: Call `mcp__plugin_proj_proj__proj_session_context` to get the active project name, config, and integration settings. Extract `project.name` and pass it to all subsequent `mcp__plugin_proj_proj__todo_*` tool calls. Use `config.default_priority` for default priority.

**add** `<title>` — add a new todo
  - **Smart parent inference**: if the title starts with a number (e.g. `3 Fix bug` or `4.2 Improve error handling`), check whether that ID is an existing todo:
    - Extract the leading token matching `^\d+(\.\d+)*` followed by a space
    - Call `mcp__plugin_proj_proj__todo_get` with that token as the ID
    - If the todo exists: pass `parent=<token>` and `title=<rest of string>` to `todo_add`
    - If the todo does not exist: use the full original string as the title, no parent
  - Parse optional inline params from the remaining arguments after the title:
    `priority=<high|medium|low>`, `tags=<tag1,tag2>`, `blocked_by=<id1,id2>`, `due=<date>`
  - Defaults: priority from config (`config.default_priority` from session context), no tags, no blocks, no due date
  - Call `mcp__plugin_proj_proj__todo_add` with parsed values. Include `due_date=<value>` if `due` param was provided.

**update** `<id> [tags=tag1,tag2 | title=... | priority=... | notes=... | due_date=...]` — update a todo's fields
  - Parse the key=value pairs from the arguments
  - Call `mcp__plugin_proj_proj__todo_update` with the provided fields
  - Show the updated todo

**done** `<id>` — mark a todo complete (e.g. "done 2")
  - Call `mcp__plugin_proj_proj__todo_complete`

**list** [all|pending|ready|blocked] [--prio|--priorities] — list todos with optional filter
  - Default (no filter): call `mcp__plugin_proj_proj__todo_tree` — shows open tasks as a hierarchy, filtering out done todos
  - `all`: call `mcp__plugin_proj_proj__todo_tree` — shows all todos including done as a hierarchy
  - `ready`: call `mcp__plugin_proj_proj__todo_ready` — shows todos with no blockers as a flat list
  - `blocked`: call `mcp__plugin_proj_proj__todo_list` with `status: "pending"` then filter to those with non-empty `blocked_by`
  - `--prio` or `--priorities` (can combine with `all`):
    1. Call `mcp__plugin_proj_proj__todo_tree` with `include_done=False` (or `include_done=True` if `all` filter also present)
    2. Flatten the tree to collect all todo objects and their nested `_children`
    3. Build the open set: all todo IDs from the flattened tree
    4. For each todo, filter its `blocked_by` list to only include IDs present in the open set (this resolves stale blockers from done/deleted todos)
    5. Call `mcp__plugin_proj_proj__proj_identify_batches` with all IDs from the open set
    6. If `cycles` is non-empty in the result, display a `### Circular Dependencies` warning section listing each cycle
    7. For each batch (tier) in the result, display as a section:
       ```
       ### Tier 0 — Start immediately
       - 🔲 **479** — Add /proj:prioritize skill *(high)* [blocks 474, 469, 471]
       - 🔲 **482** — Todo list by priority skill *(high)*

       ### Tier 1 — After Tier 0
       - 🔲 **474** — Verify hook feedback writeback *(medium)* [blocked by 479]
       ```
    8. Within each tier, sort todos by priority (high → medium → low), then by ID numerically
    9. If `all` filter was also present: show done todos in a separate `### Completed` section after all tiers, using the same display format (✅ icon)
  - Examples:
    - `/proj:todo list --prio` — show open todos grouped by blocking tiers
    - `/proj:todo list all --prio` — show all todos (including done) grouped by tiers, with completed todos in a separate section
    - `/proj:todo list --priorities` — alias for --prio
  - Display as nested bullet points with 2-space indent per level. Use status icons (✅ = done, 🔄 = in_progress, 🔲 = pending), bold ID, title, priority in italics. Always use the full, exact title from the todo — never abbreviate or summarize. If `"manual" in tags`, append `[manual]` after the priority. Blocked todos include `[blocked by X]` inline. Todos that block others include `[blocks Y]` inline. Order: `_(priority)_ [manual] [blocked by X] [blocks Y]`.
  - Example:
    ```
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write skills _(medium)_
    ```

**tree** — show todos as a hierarchy
  - Call `mcp__plugin_proj_proj__todo_tree`
  - Render as nested bullet points with 2-space indent per level. Apply the same status icons, bold ID, and inline metadata as `list` (including `[manual]` badge and `[blocked by X]`/`[blocks Y]` for dependency display).
  - Example:
    ```
    - ✅ **1** — Implement storage layer _(medium)_
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write tests _(low)_
    ```

**block** `1 blocks 2` — set blocking relationship
  - Call `mcp__plugin_proj_proj__todo_block`

**unblock** `<id>` — remove a blocking relationship
  - Call `mcp__plugin_proj_proj__todo_unblock`

**delete** `<id>` -- delete a todo
  - Call `mcp__plugin_proj_proj__todo_delete`

If $ARGUMENTS is empty or ambiguous, output: "Operation required. Usage: `/proj:todo [add|update|done|list|tree|block|unblock|delete] [args]`"
Always confirm the action taken and show the resulting todo.

**Git tracking flush**: Call `mcp__plugin_proj_proj__tracking_git_flush` with `commit_message="Todo: update"`.

## Prerequisites

- An active project must be loaded (call `proj_session_context` first).

## Error Handling

- **No active project**: displays error from `proj_session_context` and stops.
- **Empty or ambiguous arguments**: displays usage message.
- **Todo not found**: displays error from the relevant `todo_*` tool call.
- **Blocked todo completion**: displays error if trying to complete a blocked todo.

## Output

Confirmation of the action taken plus the resulting todo state. For list/tree operations: nested bullet points with status icons, bold IDs, titles, priority, manual/blocked badges.

Suggested next: After adding a todo: `1. /proj:define <id>` -- define requirements | After completing a todo: `1. /proj:status` -- see project overview
