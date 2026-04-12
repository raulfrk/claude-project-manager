---
name: trello-sync
description: Manually trigger a full bidirectional Trello sync for the active project. Card-per-todo model -- each todo becomes its own Trello card in the tasks list; project gets a tracking card in the projects list. Use when the user says "sync with Trello", "sync trello", or "trello sync".
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__proj_list, mcp__proj__proj_get, mcp__proj__proj_trello_diff, mcp__proj__proj_trello_apply, mcp__proj__proj_trello_full_sync, mcp__proj__config_load, mcp__proj__tracking_git_flush, mcp__trello__list_boards, mcp__trello__get_board, mcp__trello__update_board, mcp__trello__get_cards_by_list_id, mcp__trello__get_card, mcp__trello__add_card_to_list, mcp__trello__update_card_details, mcp__trello__move_card, mcp__trello__archive_card, mcp__trello__add_attachment, mcp__trello__get_labels, mcp__trello__get_lists, mcp__trello__create_list, mcp__trello__batch_create_cards, mcp__trello__toggle_card_label
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Full bidirectional Trello sync via **card-per-todo model**: each todo maps to own Trello card. Project-level tracking uses separate project card.

## Sync Model

- **Todo cards**: each todo → Trello card in `tasks` list (`done` list when completed).
 - Card title fmt: `[project-name] [todo-id] Title`
 - Card desc contains status, priority, tags, blocked_by, children, notes.
- **Project card**: single tracking card in `projects` list summarizing all todos.
- **Parent-child links**: child cards attached to parent cards via Trello card-to-card attachments.
- **Change detection**: each todo carries `trello_sync_state` snapshot (synced title, list, desc hash). Last-changed-wins w/ conflict detection.

## Mode Detection

Call `mcp__proj__proj_session_context`.
- Project returned → **single-project mode**.
- No active project → **batch mode**.


## Batch Mode

No active project → sync all Trello-enabled projects in single run.

**Batch 1.** Load global config + project list

- `mcp__proj__config_load` → global trello config (`trello.enabled`, `trello.default_board_id`).
- `mcp__proj__proj_list` → all non-archived projects.

**Batch 2.** Gather project metadata

Each project from `proj_list`: call `mcp__proj__proj_get(project_name=<name>)` → full metadata incl per-project trello config + `trello_card_id`.

**Batch 3.** Categorize projects

Sort each project into three buckets:

- **Linked**: has `trello_card_id` → will sync.
- **Unlinked but Trello-enabled**: Trello enabled, no `trello_card_id` → offer to link.
- **Trello not enabled**: skip silently.

Categorization summary:

```
Trello batch sync -- project scan:
  Linked (will sync):        project-a, project-b
  Unlinked (Trello-enabled): project-c, project-d
  Skipped (not enabled):     project-e
```

**Batch 4.** Sync linked projects

Each **linked** project: run full single-project sync flow w/ `project_name=<name>` passed to each MCP call. Collect per-project results.

**Batch 5.** Offer to link unlinked projects

If **unlinked but Trello-enabled** projects exist:

```
These projects have Trello enabled but no linked card:
  1. project-c
  2. project-d

Link these projects to Trello? (y/n/select)
```

Each confirmed project:
1. Resolve effective board ID.
2. Ensure `proj` label exists on board.
3. Resolve target list (matching list_mappings.projects, case-insensitive).
4. Create project tracking card.
5. Store card ID via `mcp__proj__proj_trello_apply`.
6. Run full sync flow for newly linked project.

**Batch 6.** Final summary

```
Trello batch sync complete.
  Synced:       N projects
  Newly linked: M projects
  Skipped:      K projects
  Failures:     F projects [list names if any]
```


## Single-Project Mode (Accelerated Path)

When `proj_trello_full_sync` available, use 3-call flow:

1. **`mcp__proj__proj_session_context`** — get project name + config (already called in Mode Detection)
2. **`mcp__proj__proj_trello_full_sync(project_name=name)`** — exec full sync server-side
3. **`mcp__proj__tracking_git_flush`** — commit tracking changes

### Response handling

- **`"status": "success"`**: show `summary.pull` + `summary.push` counts. If `summary.up_to_date`: "Everything up to date."
- **`"status": "partial_success"`**: show summary + list each err. Offer one retry: `proj_trello_full_sync(retry_failures=response.retry_token)`. Retry also partial_success → report remaining errs, stop.
- **`"status": "needs_confirmation"`**: each entry in `pull_delete_pending` → prompt "Delete local todo X? [Y/n]". `todo_delete` confirmed entries, re-run `proj_trello_full_sync`.
- **`"status": "error"`**: show err msg, stop.

### Fallback

`proj_trello_full_sync` not available (tool-not-found) → fall back to **Legacy Multi-Step Flow** below.


## Single-Project Mode (Legacy Multi-Step Flow)

**1.** Setup

- Use `proj_session_context` result from Mode Detection. Extract:
 - `integrations.trello.enabled`, `integrations.trello.board_id`, `integrations.trello.card_id`
 - `project.name`, `config.tracking_dir`
- Check prerequisites (enabled, board ID set). Stop w/ clear msg if not met.
- Effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Failure: Trello MCP unavailable**
Trello MCP server unreachable → stop:

> "Trello MCP server not available. Check your MCP server config and restart Claude Code."

**2.** Ensure configured labels exist (delegated to `trello-setup`)

- Delegate to `trello-setup` sub-skill — owns label preflight (name normalization, case-sensitivity, tiebreak for duplicate names, orphan logging). SOLE source of non-empty label validation. Reads `integrations.trello.proj_label_name` + `integrations.trello.proj_task_label_name` from `session_context`; binds to existing board label or creates one.
- Record returned `proj_label_id` + `proj_task_label_id`. Do NOT re-validate label names, re-implement label creation, or read `sync.trello.*` directly. Single access pattern: `session_context.integrations.trello.*`.

**3.** Ensure required lists exist

- `mcp__trello__get_lists(boardId)`.
- Verify lists for: `list_mappings.tasks`, `list_mappings.done`, `list_mappings.projects`.
- Missing list → `mcp__trello__create_list`.
- Record list IDs.

**4.** Ensure project tracking card exists

- `trello_card_id` set → `mcp__trello__get_card` to verify.
 - Card missing/archived → need new card.
 - Card valid → skip to step 5.
- No card:
 - `mcp__trello__add_card_to_list(listId=projects list, name=project name, label_ids=[proj_label_id])`.
 - Record returned card ID.
 - `mcp__proj__proj_trello_apply(link_project_card_id=new card ID)`.

**5.** Fetch Trello card state

- `mcp__trello__get_cards_by_list_id` for tasks + done lists.
- `mcp__trello__get_lists` for list metadata.
- Optionally fetch project tracking card state.
- Format as JSON: `{"cards": [...], "lists": [...], "project_card": {...}, "proj_label_id": "<proj_label_id>", "proj_task_label_id": "<proj_task_label_id>"}`.
- Two label ID keys let `proj_trello_diff` detect cards missing expected label → emit `push_update_labels` entries. Omit (or pass empty strings) only if Step 2 failed to resolve label — label enforcement skipped for this run.

**6.** Compute diff

- `mcp__proj__proj_trello_diff(trello_cards_json=card state JSON, auto_apply=true, project_name=active project name)`.
- Response includes:
 - `plan` — full diff w/ card-level ops (create, update, move, archive)
 - `project_info` — board_id, trello_card_id
 - `auto_applied` — counts of pull ops already applied locally

**7.** Execute push ops

Process each push op from plan via appropriate Trello MCP tools.

**Create cards** (`push_create_card`):
Each entry:
- `mcp__trello__add_card_to_list(listId from list_name, name=title, desc=desc, label_ids=[proj_task_label_id])`.
- Record returned card ID.
- Cards w/ `parent_todo_id`: attach link to parent card via `mcp__trello__add_attachment`.
- Batch-link all new card IDs: `mcp__proj__proj_trello_apply` w/:
  ```json
  {"link_card_ids": [{"todo_id": "<id>", "card_id": "<new_card_id>"}, ...]}
  ```

Multiple cards → prefer `mcp__trello__batch_create_cards` (pass `label_ids=[proj_task_label_id]` once at batch level; applies to every card) to reduce round-trips.

**Update cards** (`push_update_card`):
Each entry: `mcp__trello__update_card_details(cardId, name, desc)`.

**Move cards** (`push_move_card`):
Each entry: `mcp__trello__move_card(cardId, listId)`.

**Archive cards** (`push_archive_card`):
Each entry: `mcp__trello__archive_card(cardId)`.

**Update labels** (`push_update_labels`):
Each entry in `plan.push_update_labels`:
- Each label ID in `add_label_ids`: `mcp__trello__toggle_card_label(cardId=entry card_id, labelId=label ID, action="add")`. `action` arg required — do not omit.
- `toggle_card_label(..., action="add")` idempotent: Trello `POST /cards/{id}/idLabels` silently succeeds if label present; retry on transient errs safe.
- Extras (labels beyond `proj` / `proj-task`) on card never removed — strictly add-only.

**Update project card** (`project_card_update`):
If true: update project tracking card desc via `mcp__trello__update_card_details`.

**Create lists** (`lists_to_create`):
Each list name: `mcp__trello__create_list` before creating cards.

After all pushes: `mcp__proj__proj_trello_apply(push_confirmed=true)` to record `trello_sync_state` snapshots.

**8.** Git tracking flush

`mcp__proj__tracking_git_flush(commit_message="Sync: Trello")`.

**9.** Summary

Show only if changes occurred:

```
Trello sync complete.
<- Pulled from Trello: {updated} updated, {completed} completed, {reopened} reopened
-> Pushed to Trello:   {cards_created} cards created, {cards_updated} updated, {cards_moved} moved, {cards_archived} archived
```

All counts zero: "Trello sync complete. Everything up to date."


## Error Handling

- Trello not enabled → `Trello sync not enabled.`, stop.
- No board ID → stop, ask user to config board ID.
- Trello MCP unavailable → `Trello MCP server not available.`, stop.
- Partial push failures → report individually.
- Git flush err → show err, don't roll back synced changes.

## Output

- Single-project: sync summary w/ pulled + pushed counts. All zero: `Trello sync complete. Everything up to date.`
- Batch: per-project results, then overall summary (synced, newly linked, skipped, failures counts).

## Notes

- All Trello MCP tool names: `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta = stable link to project Trello tracking card.
- `trello_card_id` on each todo = stable link to its Trello card.
- `trello_sync_state` on each todo tracks last-synced title, list, desc hash for change detection.
- Auto-apply on pull: `auto_apply=true` → title updates, completions, reopens from Trello applied locally in same diff call.
- Conflict resolution: both local + Trello changed since last sync → more recently updated side wins.

Suggested next: `1. /proj:todo list` — review todos after sync | `2. /proj:todo add` — add new todo (pushed to Trello on next sync)
