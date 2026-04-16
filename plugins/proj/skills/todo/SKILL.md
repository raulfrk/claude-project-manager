---
name: todo
description: Manage project todos — add, complete, list, view tree, set dependencies, delete. Use when the user says "add todo", "mark done", "list todos", "show todo tree", or "1 blocks 2".
allowed-tools: mcp__plugin_proj_proj__todo_add, mcp__plugin_proj_proj__todo_list, mcp__plugin_proj_proj__todo_get, mcp__plugin_proj_proj__todo_update, mcp__plugin_proj_proj__todo_complete, mcp__plugin_proj_proj__todo_delete, mcp__plugin_proj_proj__todo_ready, mcp__plugin_proj_proj__todo_tree, mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__proj_update_meta, mcp__plugin_proj_proj__tracking_git_flush, mcp__plugin_proj_proj__proj_identify_batches, mcp__plugin_proj_proj__todo_notes_patch, mcp__plugin_proj_proj__todo_notes_append
argument-hint: "[add|update|done|list|tree|block|unblock|delete] [args]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Manage project todos. Parse $ARGUMENTS for operation.

**First**: `mcp__plugin_proj_proj__proj_session_context` → get active project name, config, integrations. Pass `project.name` to all `todo_*` calls. Use `config.default_priority` as default.

**add** `<title>` — add todo
 - Smart parent inference: title starts w/ number (e.g. `3 Fix bug`, `4.2 Improve error handling`) → check if ID exists:
 - Extract leading token matching `^\d+(\.\d+)*` + space
 - `mcp__plugin_proj_proj__todo_get` w/ token as ID
 - Exists → `parent=<token>`, `title=<rest>`
 - Not exists → full orig string as title, no parent
 - Parse optional inline params after title:
 `priority=<high|medium|low>`, `tags=<tag1,tag2>`, `blocked_by=<id1,id2>`, `due=<date>`
 - Defaults: priority from config, no tags/blocks/due
 - `mcp__plugin_proj_proj__todo_add` w/ parsed vals. Include `due_date=<value>` if `due` provided.

**update** `<id> [tags=tag1,tag2 | title=... | priority=... | notes=... | due_date=...]` — update todo fields
 - Parse key=value pairs; `mcp__plugin_proj_proj__todo_update`; show updated todo
 - Notes-only updates: prefer `todo_notes_patch` (find/replace) or `todo_notes_append` (append) over `todo_update(notes=...)`. Full replacement only for complete rewrites.

**notes-patch** `<id> <find> <replace> [count=1]` — find/replace in todo notes
 - Call `mcp__plugin_proj_proj__todo_notes_patch`

**notes-append** `<id> <text>` — append text to todo notes
 - Call `mcp__plugin_proj_proj__todo_notes_append`

**done** `<id>` — mark complete (e.g. "done 2")
 - `mcp__plugin_proj_proj__todo_complete`

**list** [all|pending|ready|blocked] [--prio|--priorities] [--full] — list w/ optional filter

Parse flags:
 - `--full` present → `full_mode=True`, pass `compact=False` to underlying tool
 - `--full` absent → `full_mode=False`, pass `compact=True` to underlying tool (default behavior)
 - `--prio`/`--priorities` → `prio_mode=True` (overrides `--full`; always uses structured JSON internally)

Subcommand → tool map (set `C = not full_mode` except for `--prio` which always uses False):
 - Default (no filter): `mcp__plugin_proj_proj__todo_tree` w/ `include_done=False, compact=C` — open tasks hierarchy, done filtered out
 - `all`: `mcp__plugin_proj_proj__todo_tree` w/ `include_done=True, compact=C` — all todos incl done
 - `ready`: `mcp__plugin_proj_proj__todo_ready` w/ `compact=C` — no-blocker todos
 - `blocked`: `mcp__plugin_proj_proj__todo_list` w/ `status="pending", blocked=True, compact=C` — server-side blocked filter (no prose post-filter needed)

`--prio`/`--priorities` (combinable w/ `all`, ignores `--full`):
 1. `mcp__plugin_proj_proj__todo_tree` w/ `include_done=False, compact=False` (or `include_done=True` if `all` also present)
 2. Flatten tree → collect all todo objects + nested `_children`
 3. Build open set: all IDs from flattened tree
 4. Each todo: filter `blocked_by` to only IDs in open set (resolves stale blockers)
 5. `mcp__plugin_proj_proj__proj_identify_batches` w/ all open set IDs
 6. Non-empty `cycles` → `### Circular Dependencies` warning listing each cycle
 7. Each batch (tier):
       ```
       ### Tier 0 — Start immediately
       - 🔲 **479** — Add /proj:prioritize skill *(high)* [blocks 474, 469, 471]
       - 🔲 **482** — Todo list by priority skill *(high)*

       ### Tier 1 — After Tier 0
       - 🔲 **474** — Verify hook feedback writeback *(medium)* [blocked by 479]
       ```
 8. Within tier: sort by priority (high→medium→low), then ID numerically
 9. If `all` also present: done todos in separate `### Completed` section after all tiers (✅ icon)

Compact-mode rendering (default for non-`--prio` paths):
 - Tools return `{"result": "<lines>", "count": N, "truncated": K}`. Print the `result` string verbatim. Each line: `id | status | title | priority | tags` (or tree-indented for `todo_tree`).
 - If `truncated > 0`, the `result` string already ends with `... N more items`.

Full-mode rendering (when `--full` given):
 - Tools return indented JSON. Render as nested bullets w/ icons using the existing formatting rules in the bullet list below.

Rendering rules (apply to full-mode + `--prio` mode):
 - Nested bullets, 2-space indent per level. Icons: ✅=done, 🔄=in_progress, 🔲=pending. Bold ID, title, priority in italics. Use full exact title — never abbreviate. `"manual" in tags` → append `[manual]` after priority. Blocked → `[blocked by X]` inline. Blocks others → `[blocks Y]` inline. Tag matching `group:*` → extract value after `group:` → append `[group:<value>]` at end. Order: `_(priority)_ [manual] [blocked by X] [blocks Y] [group:X]`.
 - Example:
    ```
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2] [group:623]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write skills _(medium)_
    ```

Examples:
 - `/proj:todo list` — open todos, compact one-line-per-todo
 - `/proj:todo list --full` — open todos, full structured rendering
 - `/proj:todo list all` — all todos incl done, compact
 - `/proj:todo list ready` — ready todos, compact
 - `/proj:todo list blocked` — blocked todos, compact
 - `/proj:todo list --prio` — open todos grouped by blocking tiers (compact-independent)
 - `/proj:todo list all --prio` — all todos incl done, grouped by tiers, completed separate
 - `/proj:todo list --priorities` — alias for --prio

**tree** — todos as hierarchy
 - `mcp__plugin_proj_proj__todo_tree`
 - Nested bullets, 2-space indent. Same icons/bold ID/inline metadata as `list` (incl `[manual]`, `[blocked by X]`/`[blocks Y]`, `[group:X]`).
 - Example:
    ```
    - ✅ **1** — Implement storage layer _(medium)_
    - 🔲 **2** — Build API _(high)_
      - 🔄 **2.1** — Design endpoints _(high)_ [manual] [blocks 2.2] [group:623]
      - 🔲 **2.2** — Add auth _(medium)_ [blocked by 2.1]
    - 🔲 **3** — Write tests _(low)_
    ```

**block** `1 blocks 2` — set blocking relationship
 - `mcp__plugin_proj_proj__todo_update(todo_id=<blocked-id>, blocked_by_set=[<blocker-id>, ...])`

**unblock** `<id>` — remove all blockers
 - `mcp__plugin_proj_proj__todo_update(todo_id=<id>, blocked_by_set=[])`

**delete** `<id>` — `mcp__plugin_proj_proj__todo_delete`

Empty/ambiguous $ARGUMENTS → "Operation required. Usage: `/proj:todo [add|update|done|list|tree|block|unblock|delete] [args]`"
Always confirm action + show resulting todo.

**Git tracking flush**: `mcp__plugin_proj_proj__tracking_git_flush` w/ `commit_message="Todo: update"`.

## Prerequisites

Active project must be loaded (`proj_session_context` first).

## Err Handling

- No active project → err from `proj_session_context`, stop
- Empty/ambiguous args → usage msg
- Todo not found → err from relevant `todo_*` call
- Blocked todo completion → err

## Output

Confirmation + resulting todo state. List/tree: nested bullets w/ status icons, bold IDs, titles, priority, manual/blocked badges.

Suggested next: After add → `1. /superpowers:brainstorming <id>` | After done → `1. /proj:status`
