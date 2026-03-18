---
name: trello-sync
description: Manually trigger a full bidirectional Trello sync for the active project. Each project is a single Trello card; root todos with children become checklists, leaf root todos become items in a "Tasks" checklist. Use when the user says "sync with Trello", "sync trello", or "trello sync".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__proj_trello_diff, mcp__proj__proj_trello_apply, mcp__proj__config_load, mcp__proj__tracking_git_flush
context: fork
agent: general-purpose
---

> **Note on allowed-tools:** Trello MCP tools (`mcp__{trello.mcp_server}__*`) are intentionally
> absent from `allowed-tools`. The Trello MCP server name is user-configurable via
> `trello.mcp_server` in the proj config (e.g. `"trello"`, `"my_trello"`, `"mcp-trello"`).
> Because the server name is only known at runtime, a static wildcard like
> `mcp__trello__*` would not match a differently-named server. Claude resolves the actual
> tool names dynamically after reading config and calls them without a pre-declared allow entry.

Full bidirectional Trello sync for the active project.

**Model**: one Trello card per project. Root todos with children become checklists (name = todo title). Their flattened descendants become checklist items (prefixed with ID path). Root leaf todos go into a "Tasks" catch-all checklist.

## Trello Tool Resolution

The Trello MCP server name is configurable. **Before making any Trello tool call**, read
`trello.mcp_server` from the config (via `mcp__proj__config_load`) and substitute it as the
prefix. All `mcp__trello__<tool>` references below are templates -- replace `trello` with the
actual server name from config.

Example: if `trello.mcp_server` is `my_trello`, call `mcp__my_trello__get_board_labels` not
`mcp__trello__get_board_labels`.

## Prerequisites

Before syncing, verify:
1. `trello.enabled` is `true` in config. If not, stop and tell the user to enable it with `mcp__proj__config_update(trello_enabled=True)`.
2. The active project has a `trello.board_id` set (from per-project config) or `trello.default_board_id` set globally. If neither is set, stop and ask the user to configure a board ID.

## Steps

### 1. Setup

- Call `mcp__proj__config_load` -- read `trello.*` config values. Note `mcp_server`, `default_board_id`, `default_list`.
- Call `mcp__proj__proj_get_active` -- get active project name, per-project trello config, and `trello_card_id` from project meta.
- Check prerequisites (enabled, board ID set). Stop with a clear message if not met.
- Resolve the Trello MCP server name for all subsequent calls.
- Resolve effective board ID = per-project `trello.board_id` if set, else global `trello.default_board_id`.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Trello MCP server '<server_name>' is not available. Verify the server is running and that
> `trello.mcp_server` in your proj config matches the registered MCP server name."

Do not proceed with any further sync steps.

### 2. Ensure `proj` label exists

- Call `mcp__trello__get_board_labels` with `boardId` set to the effective board ID.
- If no label named `proj` exists, call `mcp__trello__create_label` with `boardId`, `name="proj"`, `color="blue"`.
- Record the label ID for use in card creation.

### 3. Ensure project card exists

- If `trello_card_id` is set on the project meta, call `mcp__trello__get_card` to verify the card exists.
  - If the card is missing or archived, treat as needing a new card (proceed below).
  - If the card exists and is valid, skip to step 4.
- If no card exists:
  - Resolve the target list: call `mcp__trello__get_lists` with `boardId` and find the list matching `trello.default_list` (default: "Active") by name (case-insensitive). If not found, use the first list on the board.
  - Call `mcp__trello__create_card` (or `mcp__trello__add_card_to_list`) with:
    - `listId` = resolved list ID
    - `name` = project name
    - `idLabels` = the `proj` label ID
  - Record the returned card ID.
  - Call `mcp__proj__proj_trello_apply` with `link_trello_card_id` set to the new card ID.

### 4. Fetch card state

- Call `mcp__trello__get_card_checklists` (or `mcp__trello__get_checklists` or similar) with `cardId` = the project's `trello_card_id`.
- The result should be a JSON array of checklists, each with `id`, `name`, and `checkItems` array (each item has `id`, `name`, `state`).
- Format this as: `{"checklists": [<the array>]}`

### 5. Compute diff

- Call `mcp__proj__proj_trello_diff` with:
  - `trello_card_json` = the formatted card state JSON from step 4
  - `auto_apply` = `true`
  - `project_name` = active project name (optional if already active)
- The response includes:
  - `plan` -- the full diff with all push/pull operations
  - `project_info` -- mcp_server, board_id, trello_card_id, default_list
  - `auto_applied` -- counts of pull operations already applied locally

### 6. Execute push operations

Process each push operation from the plan by calling the appropriate Trello MCP tools.
All Trello tool names use the resolved `mcp_server` prefix.

**Create checklists** (`push_create_checklist`):
For each entry:
- Call `mcp__trello__create_checklist` with `cardId` = trello_card_id, `name` = entry name.
- Record the returned checklist ID. Call `mcp__proj__proj_trello_apply` to link:
  ```json
  {"link_trello_ids": [{"todo_id": "<todo_id>", "trello_checklist_id": "<new_id>"}]}
  ```

**Create items** (`push_create_item`):
For each entry:
- Resolve `checklist_id`: use the entry's `checklist_id` if set, or the newly created checklist ID (from the step above, matched by todo's parent).
- Call `mcp__trello__create_checkitem` (or similar) with `checklistId`, `name`, `checked` (as "true"/"false" or state "complete"/"incomplete").
- Record the returned item ID. Call `mcp__proj__proj_trello_apply` to link:
  ```json
  {"link_trello_ids": [{"todo_id": "<todo_id>", "trello_checklist_item_id": "<new_id>"}]}
  ```

**Update items** (`push_update_item`):
For each entry:
- Call the appropriate Trello MCP tool to update the check item name.

**Complete items** (`push_complete_item`):
For each entry:
- Call the appropriate Trello MCP tool to mark the check item as complete.

**Delete items** (`push_delete_item`):
For each entry:
- Call the appropriate Trello MCP tool to delete the check item.

**Rename checklists** (`push_rename_checklist`):
For each entry:
- Call the appropriate Trello MCP tool to rename the checklist.

**Batch linking**: When multiple IDs need linking, batch them into a single `proj_trello_apply` call.

### 7. Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Trello"`.

### 8. Summary

Display only if changes occurred:

```
Trello sync complete.
<- Pulled from Trello: {created} created, {updated} updated, {completed} completed, {reopened} reopened
-> Pushed to Trello:   {checklists_created} checklists, {items_created} items created, {items_updated} updated, {items_completed} completed
```

If all counts are zero: "Trello sync complete. Everything up to date."

---

## Notes

- All Trello MCP tool names use the pattern `mcp__<mcp_server>__<tool_name>` where `<mcp_server>` comes from `trello.mcp_server` in config.
- The `delorenj/mcp-server-trello` tools include: `add_card_to_list`, `update_card_details`, `move_card`, `get_cards_by_list_id`, `get_lists`, `get_recent_activity`, `create_checklist`, `get_card_checklists`, `create_checkitem`, `update_checkitem`, `delete_checkitem`.
- `trello_card_id` on project meta is the stable link to the project's Trello card.
- `trello_checklist_id` on root todos links to the Trello checklist.
- `trello_checklist_item_id` on all todos links to the Trello check item.
- Checklist item names for non-root descendants use ID prefixes (e.g., `1.1: Child title`) for disambiguation.
- The "Tasks" checklist is a catch-all for root leaf todos (those with no children).

## Suggested next

- `/proj:todo list` -- review todos after sync
- `/proj:todo add` -- add a new todo (will be pushed to Trello on next sync)
- `/proj:trello-sync` -- run another sync after making local changes
