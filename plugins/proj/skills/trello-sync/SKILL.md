---
name: trello-sync
description: Manually trigger a full bidirectional Trello sync for the active project. Card-per-todo model -- each todo becomes its own Trello card in the tasks list; project gets a tracking card in the projects list. Use when the user says "sync with Trello", "sync trello", or "trello sync".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__proj_list, mcp__proj__proj_get, mcp__proj__proj_trello_diff, mcp__proj__proj_trello_apply, mcp__proj__proj_trello_full_sync, mcp__proj__config_load, mcp__proj__tracking_git_flush, mcp__trello__list_boards, mcp__trello__get_board, mcp__trello__update_board, mcp__trello__get_cards_by_list_id, mcp__trello__get_card, mcp__trello__add_card_to_list, mcp__trello__update_card_details, mcp__trello__move_card, mcp__trello__archive_card, mcp__trello__add_attachment, mcp__trello__get_labels, mcp__trello__create_label, mcp__trello__get_lists, mcp__trello__create_list, mcp__trello__batch_create_cards
context: fork
agent: general-purpose
---

Full bidirectional Trello sync using the **card-per-todo model**: each todo maps to its own Trello card. Project-level tracking uses a separate project card.

## Sync Model

- **Todo cards**: each todo becomes a Trello card in the `tasks` list (or `done` list when completed).
  - Card title format: `[project-name] [todo-id] Title`
  - Card description contains status, priority, tags, blocked_by, children, notes.
- **Project card**: a single tracking card in the `projects` list summarizing all todos.
- **Parent-child links**: child cards are attached to parent cards via Trello card-to-card attachments.
- **Change detection**: each todo carries a `trello_sync_state` snapshot (synced title, list, description hash). Last-changed-wins logic with conflict detection.

## Mode Detection

Call `mcp__proj__proj_session_context`.
- If a project is returned -> run **single-project mode**.
- If no active project -> run **batch mode**.

---

## Batch Mode

When no active project is set, sync all Trello-enabled projects in a single run.

**Batch 1.** Load global config and project list

- Call `mcp__proj__config_load` to get global trello config (`trello.enabled`, `trello.default_board_id`).
- Call `mcp__proj__proj_list` to get all non-archived projects.

**Batch 2.** Gather project metadata

For each project returned by `proj_list`, call `mcp__proj__proj_get` with `project_name=<name>` to get full metadata including per-project trello config and `trello_card_id`.

**Batch 3.** Categorize projects

Sort each project into one of three buckets:

- **Linked**: has `trello_card_id` set -> will sync.
- **Unlinked but Trello-enabled**: Trello is enabled but no `trello_card_id` -> offer to link.
- **Trello not enabled**: skip silently.

Display a categorization summary:

```
Trello batch sync -- project scan:
  Linked (will sync):        project-a, project-b
  Unlinked (Trello-enabled): project-c, project-d
  Skipped (not enabled):     project-e
```

**Batch 4.** Sync linked projects

For each **linked** project, run the full single-project sync flow with `project_name=<name>` passed explicitly to each MCP tool call. Collect per-project results.

**Batch 5.** Offer to link unlinked projects

If there are **unlinked but Trello-enabled** projects, present them to the user:

```
These projects have Trello enabled but no linked card:
  1. project-c
  2. project-d

Link these projects to Trello? (y/n/select)
```

For each confirmed project:
1. Resolve effective board ID.
2. Ensure the `proj` label exists on the board.
3. Resolve the target list (matching list_mappings.projects, case-insensitive).
4. Create a project tracking card.
5. Store the card ID via `mcp__proj__proj_trello_apply`.
6. Run the full sync flow for the newly linked project.

**Batch 6.** Final summary

```
Trello batch sync complete.
  Synced:       N projects
  Newly linked: M projects
  Skipped:      K projects
  Failures:     F projects [list names if any]
```

---

## Single-Project Mode (Accelerated Path)

When `proj_trello_full_sync` is available, use this 3-call flow:

1. **`mcp__proj__proj_session_context`** -- get project name and config (already called in Mode Detection)
2. **`mcp__proj__proj_trello_full_sync(project_name=name)`** -- executes the full sync cycle server-side
3. **`mcp__proj__tracking_git_flush`** -- commit tracking changes

### Response handling

- **`"status": "success"`**: display `summary.pull` and `summary.push` counts, then stop. If `summary.up_to_date` is true, say "Everything up to date."
- **`"status": "partial_success"`**: display the summary and list each error. Offer one retry: call `proj_trello_full_sync(retry_failures=response.retry_token)`. If retry also returns partial_success, report remaining errors and stop.
- **`"status": "needs_confirmation"`**: for each entry in `pull_delete_pending`, prompt "Delete local todo X? [Y/n]". Then call `todo_delete` for confirmed entries and re-run `proj_trello_full_sync`.
- **`"status": "error"`**: display the error message and stop.

### Fallback

If `proj_trello_full_sync` is not available (tool-not-found error), fall back to the **Legacy Multi-Step Flow** below.

---

## Single-Project Mode (Legacy Multi-Step Flow)

**1.** Setup

- Use the `proj_session_context` result from Mode Detection. Extract:
  - `integrations.trello.enabled`, `integrations.trello.board_id`, `integrations.trello.card_id`
  - `project.name`, `config.tracking_dir`
- Check prerequisites (enabled, board ID set). Stop with a clear message if not met.
- Resolve effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable, stop immediately and say:

> "Trello MCP server not available. Check your MCP server configuration and restart Claude Code."

**2.** Ensure `proj` label exists

- Call `mcp__trello__get_labels` with `boardId` set to the effective board ID.
- If no label named `proj` exists, call `mcp__trello__create_label` with `boardId`, `name="proj"`, `color="blue"`.
- Record the label ID for use in card creation.

**3.** Ensure required lists exist

- Call `mcp__trello__get_lists` with `boardId`.
- Verify lists exist for: `list_mappings.tasks`, `list_mappings.done`, `list_mappings.projects`.
- For any missing list, call `mcp__trello__create_list` to create it.
- Record list IDs.

**4.** Ensure project tracking card exists

- If `trello_card_id` is set on the project meta, call `mcp__trello__get_card` to verify the card exists.
  - If the card is missing or archived, treat as needing a new card.
  - If the card exists and is valid, skip to step 5.
- If no card exists:
  - Call `mcp__trello__add_card_to_list` with:
    - `listId` = projects list ID
    - `name` = project name
    - `idLabels` = the `proj` label ID
  - Record the returned card ID.
  - Call `mcp__proj__proj_trello_apply` with `link_project_card_id` set to the new card ID.

**5.** Fetch Trello card state

- Call `mcp__trello__get_cards_by_list_id` for the tasks list and done list.
- Call `mcp__trello__get_lists` to get list metadata.
- Optionally fetch the project tracking card state.
- Format as JSON: `{"cards": [...], "lists": [...], "project_card": {...}}`

**6.** Compute diff

- Call `mcp__proj__proj_trello_diff` with:
  - `trello_cards_json` = the card state JSON from step 5
  - `auto_apply` = `true`
  - `project_name` = active project name
- The response includes:
  - `plan` -- the full diff with card-level operations (create, update, move, archive)
  - `project_info` -- board_id, trello_card_id
  - `auto_applied` -- counts of pull operations already applied locally

**7.** Execute push operations

Process each push operation from the plan by calling the appropriate Trello MCP tools.

**Create cards** (`push_create_card`):
For each entry:
- Call `mcp__trello__add_card_to_list` with `listId` (resolve from `list_name`), `name` = title, `desc` = desc.
- Record the returned card ID.
- For cards with `parent_todo_id`, attach a link to the parent card via `mcp__trello__add_attachment`.
- Batch-link all new card IDs: call `mcp__proj__proj_trello_apply` with:
  ```json
  {"link_card_ids": [{"todo_id": "<id>", "card_id": "<new_card_id>"}, ...]}
  ```

When multiple cards need creating, prefer `mcp__trello__batch_create_cards` to reduce round-trips.

**Update cards** (`push_update_card`):
For each entry:
- Call `mcp__trello__update_card_details` with `cardId`, `name`, `desc`.

**Move cards** (`push_move_card`):
For each entry:
- Call `mcp__trello__move_card` with `cardId`, `listId`.

**Archive cards** (`push_archive_card`):
For each entry:
- Call `mcp__trello__archive_card` with `cardId`.

**Update project card** (`project_card_update`):
- If true, update the project tracking card description via `mcp__trello__update_card_details`.

**Create lists** (`lists_to_create`):
- For each list name, call `mcp__trello__create_list` before creating cards.

After all pushes, call `mcp__proj__proj_trello_apply` with `push_confirmed=true` to record `trello_sync_state` snapshots.

**8.** Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Trello"`.

**9.** Summary

Display only if changes occurred:

```
Trello sync complete.
<- Pulled from Trello: {updated} updated, {completed} completed, {reopened} reopened
-> Pushed to Trello:   {cards_created} cards created, {cards_updated} updated, {cards_moved} moved, {cards_archived} archived
```

If all counts are zero: "Trello sync complete. Everything up to date."

---

## Error Handling

- **Trello not enabled**: displays `Trello sync not enabled.` and stops.
- **No board ID configured**: stops and asks the user to configure a board ID.
- **Trello MCP unavailable**: displays `Trello MCP server not available.` and stops.
- **Partial push failures**: individual failures are reported.
- **Git flush error**: displays error but does not roll back synced changes.

## Output

- **Single-project mode**: Sync summary showing pulled and pushed counts. If all zero: `Trello sync complete. Everything up to date.`
- **Batch mode**: Per-project results, then overall summary (synced, newly linked, skipped, failures counts).

## Notes

- All Trello MCP tool names use the pattern `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta is the stable link to the project's Trello tracking card.
- `trello_card_id` on each todo is the stable link to its Trello card.
- `trello_sync_state` on each todo tracks last-synced title, list, and description hash for change detection.
- **Auto-apply on pull**: When `auto_apply=true`, title updates, completions, and reopens from Trello are applied locally in the same diff call.
- **Conflict resolution**: When both local and Trello have changed since last sync, the more recently updated side wins.

Suggested next: `1. /proj:todo list` -- review todos after sync | `2. /proj:todo add` -- add a new todo (will be pushed to Trello on next sync)
