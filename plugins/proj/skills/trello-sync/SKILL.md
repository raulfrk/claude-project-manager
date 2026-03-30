---
name: trello-sync
description: Manually trigger a full bidirectional Trello sync for the active project. Each project is a single Trello card; root todos with children become checklists, leaf root todos become items in a "Tasks" checklist. Use when the user says "sync with Trello", "sync trello", or "trello sync".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__proj_list, mcp__proj__proj_get, mcp__proj__proj_trello_diff, mcp__proj__proj_trello_apply, mcp__proj__config_load, mcp__proj__tracking_git_flush, mcp__trello__list_boards, mcp__trello__get_board, mcp__trello__update_board, mcp__trello__get_card_checklists, mcp__trello__create_checklist, mcp__trello__add_checklist_item, mcp__trello__update_checklist_item, mcp__trello__delete_checklist, mcp__trello__rename_checklist_item, mcp__trello__delete_checklist_item, mcp__trello__rename_checklist
context: fork
agent: general-purpose
---

Full bidirectional Trello sync. Supports two modes:
- **Single-project mode**: when an active project is set, sync that project only.
- **Batch mode**: when no active project is set, sync all Trello-enabled projects.

## Mode Detection

Call `mcp__proj__proj_session_context`.
- If a project is returned → run **single-project mode** (the existing flow below, starting at "Sub-skill chain"). Use the returned config and integration data throughout.
- If no active project (error or "No active project" message) → run **batch mode** (see "Batch Mode" section).

---

## Batch Mode

When no active project is set, sync all Trello-enabled projects in a single run.

**Batch 1.** Load global config and project list

- Call `mcp__proj__config_load` to get global trello config (`trello.enabled`, `trello.default_board_id`, `trello.default_list`).
- Call `mcp__proj__proj_list` to get all non-archived projects.

**Batch 2.** Gather project metadata

For each project returned by `proj_list`, call `mcp__proj__proj_get` with `project_name=<name>` to get full metadata including per-project trello config and `trello_card_id`.

**Batch 3.** Categorize projects

Sort each project into one of three buckets:

- **Linked**: has `trello_card_id` set → will sync.
- **Unlinked but Trello-enabled**: Trello is enabled (either per-project `trello.enabled` is `true`, or the global `trello.enabled` is `true` and the project does not explicitly disable it) but no `trello_card_id` → offer to link.
- **Trello not enabled**: Trello is not enabled for this project → skip silently.

Display a categorization summary:

```
Trello batch sync — project scan:
  Linked (will sync):        project-a, project-b
  Unlinked (Trello-enabled): project-c, project-d
  Skipped (not enabled):     project-e
```

**Batch 4.** Sync linked projects

For each **linked** project, run the full single-project sync flow (steps 1–8 below) with `project_name=<name>` passed explicitly to each MCP tool call instead of relying on the active project. Specifically:
- In step 1 (Setup), use the project's metadata from Batch 2 instead of calling `proj_get_active`.
- In step 5 (Compute diff), pass `project_name=<name>` to `mcp__proj__proj_trello_diff`.
- In step 6 (Push), pass `project_name=<name>` to `mcp__proj__proj_trello_apply`.
- In step 7 (Git flush), call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Trello (<name>)"`.

Collect per-project results (success/failure, counts).

**Batch 5.** Offer to link unlinked projects

If there are **unlinked but Trello-enabled** projects, present them to the user:

```
These projects have Trello enabled but no linked card:
  1. project-c
  2. project-d

Link these projects to Trello? (y/n/select)
```

- **y**: link all listed projects.
- **n**: skip all.
- **select**: let the user pick which ones to link (e.g., "1,2" or "project-c").

For each confirmed project, create a Trello card using the same pattern as steps 2–3 of the single-project flow:
1. Resolve effective board ID (per-project `trello.board_id` or global `trello.default_board_id`).
2. Ensure the `proj` label exists on the board (call `mcp__trello__get_board` with `boardId`, create label if missing).
3. Resolve the target list (matching `trello.default_list`, default "Active", case-insensitive; fallback to first list).
4. Create a card with `name` = project name, `idLabels` = the `proj` label ID.
5. Store the card ID: call `mcp__proj__proj_trello_apply` with `project_name=<name>` and `link_trello_card_id=<new_card_id>`.
6. Run the full sync flow (steps 4–8) for the newly linked project.

**Batch 6.** Final summary

Display a summary of the entire batch run:

```
Trello batch sync complete.
  Synced:       N projects
  Newly linked: M projects
  Skipped:      K projects
  Failures:     F projects [list names if any]
```

If there were failures, list the project name and a brief error description for each.

---

## Single-Project Mode

**Sub-skill chain**: This skill chains five sub-skills in sequence:
1. `/proj:trello-setup` -- ensure proj label and project card exist on the board
2. `/proj:trello-fetch` -- fetch card state (checklists, items)
3. `/proj:trello-diff` -- compute diff between local todos and Trello state
4. `/proj:trello-push` -- execute push operations to Trello
5. `/proj:trello-link` -- link returned Trello IDs to local todos and flush git

**Model**: one Trello card per project. Root todos with children become checklists (name = todo title). Their flattened descendants become checklist items (prefixed with ID path). Root leaf todos go into a "Tasks" catch-all checklist.

## Prerequisites

Before syncing, verify:
1. `trello.enabled` is `true` in config. If not, stop with: "Trello sync not enabled. Run `/proj:init-plugin` to enable it."
2. The active project has a `trello.board_id` set (from per-project config) or `trello.default_board_id` set globally. If neither is set, stop and ask the user to configure a board ID.

**1.** Setup

- Use the `proj_session_context` result from Mode Detection (already called above). Extract:
  - `integrations.trello.enabled`, `integrations.trello.board_id` (global default), `integrations.trello.card_id` (project's card)
  - `project.name`, `config.tracking_dir`
- Check prerequisites (enabled, board ID set). Stop with a clear message if not met.
- Resolve effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Trello MCP server not available. Check your MCP server configuration and restart Claude Code."

Do not proceed with any further sync steps.

**2.** Ensure `proj` label exists

- Call `mcp__trello__get_board_labels` with `boardId` set to the effective board ID.
- If no label named `proj` exists, call `mcp__trello__create_label` with `boardId`, `name="proj"`, `color="blue"`.
- Record the label ID for use in card creation.

**3.** Ensure project card exists

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

**4.** Fetch card state

- Call `mcp__trello__get_card_checklists` (or `mcp__trello__get_checklists` or similar) with `cardId` = the project's `trello_card_id`.
- The result should be a JSON array of checklists, each with `id`, `name`, and `checkItems` array (each item has `id`, `name`, `state`).
- Format this as: `{"checklists": [<the array>]}`

**5.** Compute diff

- Call `mcp__proj__proj_trello_diff` with:
  - `trello_card_json` = the formatted card state JSON from step 4
  - `auto_apply` = `true`
  - `project_name` = active project name (optional if already active)
- The response includes:
  - `plan` -- the full diff with all push/pull operations
  - `project_info` -- board_id, trello_card_id, default_list
  - `auto_applied` -- counts of pull operations already applied locally

**5b.** Handle pull_delete entries

If the diff contains `pull_delete` entries, these are todos whose linked Trello checklist items have been deleted. For each entry, display:

```
Todo "<title>" (id: <todo_id>) was deleted on Trello. Delete locally? [Y/n]
```

- **Y** (default): include the `todo_id` in the `pull_delete` list passed to `mcp__proj__proj_trello_apply`.
- **n**: skip — the local todo is preserved.

**Important**: Auto-sync setting does NOT bypass this confirmation. The `auto_apply=True` path in `proj_trello_diff` explicitly excludes `pull_delete` entries. They always require user confirmation.

If there are warnings about missing checklists, display them to the user but take no action (these indicate the entire checklist was removed, not individual items).

**6.** Execute push operations

Process each push operation from the plan by calling the appropriate Trello MCP tools.
All Trello tool names use the `mcp__trello__` prefix.

**Create checklists** (`push_create_checklist`):
For each entry:
- Call `mcp__trello__create_checklist` with `cardId` = trello_card_id, `name` = entry name.
- Record the returned checklist ID. Call `mcp__proj__proj_trello_apply` to link:
  ```json
  {"link_trello_ids": [{"todo_id": "<todo_id>", "trello_checklist_id": "<new_id>"}]}
  ```

**Create items** (`push_create_item`):
When multiple items target the same checklist, prefer `mcp__trello__batch_add_checklist_items` to
create them in a single call (each item dict has `name` and optional `checked`). The response
contains `successes` and `failures` arrays. For items across different checklists, group by
checklist ID and make one batch call per checklist.

For single items or fallback:
- Resolve `checklist_id`: use the entry's `checklist_id` if set, or the newly created checklist ID (from the step above, matched by todo's parent).
- Call `mcp__trello__add_checklist_item` with `checklistId`, `name`.
- Record the returned item ID. Call `mcp__proj__proj_trello_apply` to link:
  ```json
  {"link_trello_ids": [{"todo_id": "<todo_id>", "trello_checklist_item_id": "<new_id>"}]}
  ```

**Update items** (`push_update_item`) and **Complete items** (`push_complete_item`):
When multiple items need updating on the same card, prefer `mcp__trello__batch_update_checklist_items`
with `card_id` and an `updates` array (each entry has `checklist_id`, `item_id`, and optional
`name`/`state`). The response contains `successes` and `failures` arrays.

For single items or fallback:
- Call the appropriate Trello MCP tool to update the check item name or mark it complete.

**Delete items** (`push_delete_item`):
For each entry:
- Call the appropriate Trello MCP tool to delete the check item.

**Rename checklists** (`push_rename_checklist`):
For each entry:
- Call the appropriate Trello MCP tool to rename the checklist.

**Batch linking**: When multiple IDs need linking, batch them into a single `proj_trello_apply` call.

**7.** Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Trello"`.

**8.** Summary

Display only if changes occurred:

```
Trello sync complete.
<- Pulled from Trello: {created} created, {updated} updated, {completed} completed, {reopened} reopened, {pull_deleted} deleted
-> Pushed to Trello:   {checklists_created} checklists, {items_created} items created, {items_updated} updated, {items_completed} completed
```

If all counts are zero: "Trello sync complete. Everything up to date."

---

## Error Handling

- **Trello not enabled**: displays `Trello sync not enabled.` and stops.
- **No board ID configured**: stops and asks the user to configure a board ID.
- **Trello MCP unavailable**: displays `Trello MCP server not available.` and stops.
- **Partial push failures**: batch tools return `{successes, failures}` — individual failures are reported.
- **Git flush error**: displays error but does not roll back synced changes.

## Output

- **Single-project mode**: Sync summary showing pulled (created, updated, completed, reopened) and pushed (checklists created, items created, updated, completed) counts. If all zero: `Trello sync complete. Everything up to date.`
- **Batch mode**: Per-project results, then overall summary (synced, newly linked, skipped, failures counts).

## Notes

- All Trello MCP tool names use the pattern `mcp__trello__<tool_name>`.
- The `delorenj/mcp-server-trello` tools include: `add_card_to_list`, `update_card_details`, `move_card`, `get_cards_by_list_id`, `get_lists`, `get_recent_activity`, `create_checklist`, `get_card_checklists`, `create_checkitem`, `update_checkitem`, `delete_checkitem`.
- Batch tools: `batch_create_cards`, `batch_add_checklist_items`, `batch_update_checklist_items`. These reduce round-trips when syncing multiple items and return `{successes, failures}` for partial-failure handling.
- `trello_card_id` on project meta is the stable link to the project's Trello card.
- `trello_checklist_id` on root todos links to the Trello checklist.
- `trello_checklist_item_id` on all todos links to the Trello check item.
- **Auto-linking on pull-create**: When `auto_apply=true`, items created in Trello and pulled locally get their `trello_checklist_item_id` (or `trello_checklist_id` for root checklists) stored on the newly created local todo atomically in the same `apply_changes` call. A `trello_sync_state` snapshot is also recorded on every synced todo after apply, enabling last-changed-wins on subsequent syncs.
- Checklist item names for non-root descendants use ID prefixes (e.g., `1.1: Child title`) for disambiguation.
- The "Tasks" checklist is a catch-all for root leaf todos (those with no children).

Suggested next: `1. /proj:todo list` -- review todos after sync | `2. /proj:todo add` -- add a new todo (will be pushed to Trello on next sync)
