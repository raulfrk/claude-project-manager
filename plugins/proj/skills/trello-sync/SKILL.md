---
name: trello-sync
description: Manually trigger a full bidirectional Trello sync for root todos. Syncs root-level todos only — child/subtodos are never synced. Use when the user says "sync with Trello", "sync trello", or "trello sync".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_add, mcp__proj__config_load
---

Full bidirectional Trello sync for root todos in the active project.

Only root-level todos (those with no parent) are synced. Child todos are silently skipped.

## Trello Tool Resolution

The Trello MCP server name is configurable. **Before making any Trello tool call**, read
`trello.mcp_server` from the config (via `mcp__proj__config_load`) and substitute it as the
prefix. All `mcp__trello__<tool>` references below are templates — replace `trello` with the
actual server name from config.

Example: if `trello.mcp_server` is `my_trello`, call `mcp__my_trello__get_lists` not
`mcp__trello__get_lists`.

## Field Mapping

| Local field | Trello card field |
|---|---|
| `title` | card name |
| `status` (done) | card moved to "done" list |
| `due_date` (ISO date string) | card due date |

## Prerequisites

Before syncing, verify:
1. `trello.enabled` is `true` in config. If not, stop and tell the user to enable it with `mcp__proj__config_update(trello_enabled=True)`.
2. The active project has a `trello.board_id` set (from per-project config) or `trello.default_board_id` set globally. If neither is set, stop and ask the user to configure a board ID.

## List Resolution

Trello list IDs must be resolved before creating or moving cards. The config stores list names (or IDs) in `list_mappings.created` and `list_mappings.done`.

To resolve list names to IDs:
- Call `mcp__trello__get_lists` with `boardId` set to the effective board ID.
- Match by exact name (case-insensitive). If already an ID (all hex characters, length ~24), use as-is.
- Cache resolved IDs for the duration of the sync run.

Effective board ID = per-project `trello.board_id` if set, else global `trello.default_board_id`.
Effective list mappings = per-project `trello.list_mappings` if set, else global `trello.list_mappings`.

## Steps

### 1. Setup

- Call `mcp__proj__config_load` — read `trello.*` config values.
- Call `mcp__proj__proj_get_active` — get active project name and per-project trello config.
- Check prerequisites (enabled, board ID set). Stop with a clear message if not met.
- Resolve list names to IDs using `mcp__trello__get_lists`.

### 2. Fetch both sides

- Call `mcp__trello__get_cards_by_list_id` for the "created" list ID — collect open cards.
- Call `mcp__trello__get_cards_by_list_id` for the "done" list ID — collect done cards.
- Call `mcp__proj__todo_list` — get all active local root todos (filter: `parent` is null).
- Build lookup maps:
  - `trello_open_by_id`: card ID → open Trello card object (from created list)
  - `trello_done_by_id`: card ID → done Trello card object (from done list)
  - `local_by_card_id`: `trello_card_id` → local todo
  - `local_unlinked`: local root todos where `trello_card_id` is null

### 3. Trello → Local (pull)

**Cards in the "done" list** (from `trello_done_by_id`):
- For each done card:
  - If matched to a local todo (via `trello_card_id`): call `mcp__proj__todo_complete` if local is not already done.
  - If not matched: skip (card predates this integration or was created outside the plugin).
- Track: `closed_locally += 1`

**Cards in the "created" list** (from `trello_open_by_id`):
- For each open card:
  - If matched to a local todo (via `trello_card_id`):
    - Compare card `name` vs local `title`. If different: call `mcp__proj__todo_update` with updated title. Track: `updated_locally += 1`.
    - Compare card `due` date vs local `due_date`. If different: call `mcp__proj__todo_update` with updated `due_date`. Track: `updated_locally += 1` (only once per todo, even if both fields changed).
  - If not matched: This is a card created in Trello outside the plugin. Skip for now (v1 does not auto-import external Trello cards).

### 4. Local → Trello (push)

Process **root todos only** (skip any todo where `parent` is not null).

For each local root todo:
- **No `trello_card_id`** (unlinked): New local todo — push to Trello.
  - Call `mcp__trello__add_card_to_list` with:
    - `listId` = resolved "created" list ID
    - `name` = todo title
    - `desc` = todo notes (if any)
    - `due` = todo `due_date` (if set, as ISO date string)
  - Call `mcp__proj__todo_update` to store the returned card ID as `trello_card_id`.
  - Track: `created_in_trello += 1`

- **Has `trello_card_id`** and the card is in the open list: Update if local title or due_date differ.
  - Call `mcp__trello__update_card_details` with updated `name` and/or `due` as needed.
  - Track: `updated_in_trello += 1`

- **Has `trello_card_id`** and local todo is done but card is still in the created list:
  - Call `mcp__trello__move_card` to move to the "done" list ID.
  - Track: `updated_in_trello += 1`

### 5. Deleted/archived card propagation

For local open root todos where `trello_card_id` is set but the card appears in neither the "created" nor "done" lists:
- The card was likely archived or deleted externally. Complete the local todo.
- Track: `closed_locally += 1`

### 6. On-delete handling (local → Trello)

When a todo is deleted locally (detected if `trello_card_id` is set but the todo no longer appears in `todo_list`), this cannot be detected reliably without tombstones. Skip in v1 — note the limitation in the summary if relevant.

Note: actual card archiving/deletion on local todo delete is handled by the push step in the individual todo management workflow, not this full-sync skill. This skill is for reconciliation only.

### 7. Summary

Display only if changes occurred:

```
Trello sync complete.
← Pulled from Trello: {updated_locally} updated, {closed_locally} closed
→ Pushed to Trello:   {created_in_trello} created, {updated_in_trello} updated
```

If all counts are zero: "Trello sync complete. Everything up to date."

---

## Push-Only Operations (called from other skills/tools)

The following operations are performed by other skills (e.g., after `todo_add`, `todo_complete`, `todo_update`) when `trello.enabled` is true and the todo is a root todo. They are documented here for reference.

### Create card (on todo_add)

1. Verify todo has no parent. If it has a parent, skip silently.
2. Resolve list IDs (call `mcp__trello__get_lists` if not already resolved).
3. Call `mcp__trello__add_card_to_list` with `listId` = "created" list, `name` = title, `due` = due_date if set.
4. Store returned card ID via `mcp__proj__todo_update(trello_card_id=<id>)`.

### Update card title (on todo title change)

1. Verify todo is a root todo with `trello_card_id` set.
2. Call `mcp__trello__update_card_details` with `cardId` = `trello_card_id`, `name` = new title.

### Complete card (on todo_complete)

1. Verify todo is a root todo with `trello_card_id` set.
2. Resolve "done" list ID.
3. Call `mcp__trello__move_card` with `cardId` = `trello_card_id`, `listId` = "done" list ID.

### Update due date (on due_date change)

1. Verify todo is a root todo with `trello_card_id` set.
2. Call `mcp__trello__update_card_details` with `cardId` = `trello_card_id`, `due` = new due_date (or `null` to clear).

### Archive/delete card (on todo_delete)

1. Verify todo is a root todo with `trello_card_id` set.
2. Read `on_delete` config (effective: per-project override or global default).
3. If `on_delete == "archive"`: Call `mcp__trello__update_card_details` with `cardId` = `trello_card_id`, `closed` = true.
   - If the MCP server does not support `closed`, fall back to `mcp__trello__move_card` to the "done" list.
4. If `on_delete == "delete"`: Call `mcp__trello__delete_card` with `cardId` = `trello_card_id` (if available), or `mcp__trello__update_card_details` with `closed` = true as fallback.

---

## Notes

- All Trello MCP tool names use the pattern `mcp__<mcp_server>__<tool_name>` where `<mcp_server>` comes from `trello.mcp_server` in config.
- The `delorenj/mcp-server-trello` tools are: `add_card_to_list`, `update_card_details`, `move_card`, `get_cards_by_list_id`, `get_lists`, `get_recent_activity`.
- If `update_card_details` does not support `closed`, use `move_card` to the "Done" list as the archive equivalent.
- `trello_card_id` is stored on the local todo and is the stable link. Never overwrite it with a different card ID.
