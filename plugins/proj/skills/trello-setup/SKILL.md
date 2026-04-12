---
name: trello-setup
description: Ensure the configured project-card label and task-card label plus the project card exist on the Trello board. Sub-skill of trello-sync.
allowed-tools: mcp__trello__get_board, mcp__trello__list_boards, mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__config_load
---

> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Ensure configured `proj_label_name` (default `proj`, blue) and `proj_task_label_name` (default `proj-task`, green) labels + project card exist on configured Trello board. Sub-skill of `/proj:trello-sync`. SOLE owner of label non-empty validation; `/proj:trello-sync` delegates all label creation here.

**Naming footgun**: label name singular (`proj-task`, via `sync.trello.proj_task_label_name`). List name plural (`proj-tasks`, via `sync.trello.list_mappings.tasks`). One-char diff. Don't conflate.

**1.** Read config + active project

- `mcp__proj__proj_session_context` — read all config, project meta, integration settings.
 - Extract `integrations.trello.enabled`, `integrations.trello.board_id` (global default), `integrations.trello.card_id` (project's card), `integrations.trello.proj_label_name`, `integrations.trello.proj_task_label_name`, `project.name`.
- Prerequisites:
 - `integrations.trello.enabled` must be `true`. If not → "Trello sync not enabled. Run `/proj:init-plugin` to enable it."
 - Board ID must be set (per-project `trello.board_id` or global `integrations.trello.board_id`). Neither set → "sync.trello.default_board_id is empty but sync.trello.enabled is True — set board ID in proj.yaml or disable trello sync."
- Effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Label-name preflight (both `proj_label_name` and `proj_task_label_name`)**

Normalization pipeline on each name BEFORE any comparison/Trello API call. Pipeline MUST be identical on both sides of equality check.

1. `value.strip()` — trim whitespace. Trello silently trims on writes; comparing `NFC(strip(configured))` vs `NFC(strip(board_label.name))` prevents false-miss when user typed `"  proj  "` and Trello stored `"proj"`.
2. Stripped val empty → stop: `"Label name is empty — set sync.trello.proj_label_name in proj.yaml"` (or `proj_task_label_name`). Single source of non-empty validation.
3. Reject control chars (`\n`, `\t`, `\r`, any `ord(c) < 32`) → stop: `"Label name contains control characters — pick a printable name"`.
4. NFC-normalize via `unicodedata.normalize("NFC", value)`. Handles composed vs decomposed forms (e.g. `café` NFC vs `cafe` + combining acute NFD).
5. Soft length cap: `len(stripped_nfc_name) > 50` (see `trello_label_name_length_limit` in `plugins/proj/server/server/lib/models.py`) → log warning, don't block. Trello API accepts ~16384 chars but >50 hurts UX.

Comparison **case-sensitive**. `proj`, `Proj`, `PROJ` = three distinct labels. Don't lowercase either side.

**Failure: Trello MCP server unavailable**
Tool call raises tool-not-found/connection err/not registered → stop:

> "Trello MCP server not available. Check your MCP server config and restart Claude Code."

No further steps.

**2.** Ensure configured labels exist

- `proj_label_name` and `proj_task_label_name` = NFC-stripped vals from preflight.
- `mcp__trello__get_board` (or `mcp__trello__get_labels`) w/ effective board ID → get board labels.
- Each configured name (`proj_label_name` w/ preferred color `blue`, then `proj_task_label_name` w/ preferred color `green`), apply match/tiebreak:
 1. Filter `existing_labels` where `NFC(strip(name))` equals configured name (case-sensitive).
 2. **Zero** matches → `mcp__trello__create_label` w/ `boardId`, `name=<configured name>`, `color=<preferred color>`. Log: `"Created new label id=<id> name=<name> color=<color>"`. Record ID as `proj_label_id` / `proj_task_label_id`.
 3. **One** match → record ID. Log: `"Using existing label id=<id> name=<name> color=<color>"`. Lets user spot silent hijack of pre-existing label w/ same name.
 4. **Multiple** matches (Trello allows dup label names w/ diff colors on single board), tiebreak:
 - Prefer exact `(name, color)` match w/ preferred color.
 - Else prefer first entry in `get_labels` pagination order (stable per API call).
 - Else hard err: `"Multiple labels named '<name>' found on board: id=X color=Y, id=Z color=W. Delete one manually, then re-run trello-setup."`
- Both IDs used downstream: `proj_label_id` for project tracking card, `proj_task_label_id` for per-todo cards.

**Label rename orphan note**: user changes `sync.trello.proj_label_name` or `sync.trello.proj_task_label_name` in `proj.yaml` AFTER labels created → OLD label remains as orphan. No migration. To rename: update config, manually delete/rename old label on Trello. `Using existing label` / `Created new label` logs let you audit bindings.

**Trello built-in label hijack note**: Trello boards pre-seeded w/ colored labels (blue, green, yellow, etc.) users may have renamed. If someone renamed built-in blue label to `"proj"` before running this skill, match step silently binds to it. Orphan-log line (`Using existing label id=X name=N color=C`) = only detection; read it, decide whether to keep binding or delete old label and re-run.

**3.** Ensure project card exists

- `trello_card_id` set on project meta → verify card exists, not archived.
 - Valid → return card ID + label IDs.
- No card or invalid card:
 - Resolve target list from board (matching `trello.default_list`, default "Active", case-insensitive; fallback first list).
 - Create card w/ `name` = project name, `label_ids` = `[proj_label_id]`.
 - Record returned card ID for downstream linking.

Return board ID, card ID, `proj_label_id`, `proj_task_label_id` for trello-sync skill.

## Prerequisites

- Trello sync enabled (`trello.enabled: true`).
- Board ID set (per-project or global `trello.default_board_id`).
- Active project loaded.
- Trello MCP server running + reachable.

## Err Handling

- Trello not enabled → "Trello sync not enabled. Run `/proj:init-plugin` to enable it."
- No board ID → stop, ask user to configure.
- Trello MCP unavailable → "Trello MCP server not available. Check your MCP server config and restart Claude Code."
- Card missing/archived → create new card, link it.

## Output

Returns board ID, card ID, `proj_label_id`, `proj_task_label_id` for trello-sync skill.

## Notes

- All Trello MCP tool names: `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta = stable link to project's Trello card.
