---
name: trello-setup
description: Ensure the configured project-card label and task-card label plus the project card exist on the Trello board. Sub-skill of trello-sync.
allowed-tools: mcp__trello__get_board, mcp__trello__list_boards, mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__config_load
---

Ensure the configured `proj_label_name` (default `proj`, blue) and `proj_task_label_name` (default `proj-task`, green) labels plus the project card exist on the configured Trello board. This is a sub-skill used by `/proj:trello-sync`. It is the SOLE owner of label non-empty validation; `/proj:trello-sync` delegates all label creation here.

**Naming footgun**: the label name is singular (`proj-task`, set via `sync.trello.proj_task_label_name`). The list name is plural (`proj-tasks`, set via `sync.trello.list_mappings.tasks`). One-character difference. Do not conflate.

**1.** Read config and active project

- Call `mcp__proj__proj_session_context` — read all config, project metadata, and integration settings in one call.
  - From the result, extract `integrations.trello.enabled`, `integrations.trello.board_id` (global default), `integrations.trello.card_id` (project's card), `integrations.trello.proj_label_name`, `integrations.trello.proj_task_label_name`, and `project.name`.
- Check prerequisites:
  - `integrations.trello.enabled` must be `true`. If not, stop with: "Trello sync not enabled. Run `/proj:init-plugin` to enable it."
  - A board ID must be set (per-project `trello.board_id` or global `integrations.trello.board_id`). If neither is set, stop with: "sync.trello.default_board_id is empty but sync.trello.enabled is True — set the board ID in proj.yaml or disable trello sync."
- Resolve effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Label-name preflight (applied to both `proj_label_name` and `proj_task_label_name`)**

Run the following normalization pipeline on each configured name BEFORE any comparison or Trello API call. The pipeline MUST be identical on both sides of any equality check.

1. `value.strip()` — leading/trailing whitespace removed. Trello itself silently trims leading/trailing whitespace on label writes, so comparing `NFC(strip(configured))` vs `NFC(strip(board_label.name))` prevents a false-miss when the user typed `"  proj  "` and Trello stored `"proj"`.
2. If the stripped value is empty (or the configured field was empty to begin with), stop with: `"Label name is empty — set sync.trello.proj_label_name in proj.yaml"` (or `proj_task_label_name` respectively). This skill is the single source of non-empty validation.
3. Reject any control character (newline `\n`, tab `\t`, carriage return `\r`, or any character with `ord(c) < 32`). Stop with: `"Label name contains control characters — pick a printable name"`.
4. NFC-normalize via `unicodedata.normalize("NFC", value)`. This handles composed vs decomposed forms (e.g. `café` NFC vs `cafe` + combining acute NFD).
5. Soft length cap: if `len(stripped_nfc_name) > 50` (see `trello_label_name_length_limit` in `plugins/proj/server/server/lib/models.py`), log a warning but do NOT block. Trello's API accepts up to ~16384 chars but >50 hurts UX. Hard cap enforcement is out of scope for 506.

Comparison is **case-sensitive**. `proj`, `Proj`, and `PROJ` are three distinct labels. Trello is case-sensitive too; do not lowercase either side.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable — for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered — stop immediately
and say:

> "Trello MCP server not available. Check your MCP server configuration and restart Claude Code."

Do not proceed with any further steps.

**2.** Ensure configured label-name labels exist

- Let `proj_label_name` and `proj_task_label_name` be the NFC-stripped values from the preflight above.
- Call `mcp__trello__get_board` (or `mcp__trello__get_labels`) with `boardId` set to the effective board ID to retrieve board labels.
- For each configured name (`proj_label_name` with preferred color `blue`, then `proj_task_label_name` with preferred color `green`), apply the match/tiebreak rule:
  1. Filter `existing_labels` down to labels whose `NFC(strip(name))` equals the configured name (case-sensitive).
  2. If the filter produces **zero** matches, create a new label via `mcp__trello__create_label` with `boardId`, `name=<configured name>`, `color=<preferred color>`. Log: `"Created new label id=<id> name=<name> color=<color>"`. Record the returned ID as `proj_label_id` / `proj_task_label_id`.
  3. If the filter produces **exactly one** match, record its ID. Log: `"Using existing label id=<id> name=<name> color=<color>"`. This log line lets the user spot silent hijack of a pre-existing label with the same name (see "Trello built-in label hijack" below).
  4. If the filter produces **multiple** matches (Trello allows duplicate label names with different colors on a single board), apply this tiebreak:
     - **First**: prefer an exact `(name, color)` match with the preferred color.
     - **Else**: prefer the first entry in `get_labels` pagination order (stable per API call).
     - **Else**: hard error with `"Multiple labels named '<name>' found on board: id=X color=Y, id=Z color=W. Delete one manually, then re-run trello-setup."`
- Both IDs are used downstream: `proj_label_id` for the project tracking card and `proj_task_label_id` for per-todo cards.

**Label rename orphan note**: if the user changes `sync.trello.proj_label_name` or `sync.trello.proj_task_label_name` in `proj.yaml` AFTER labels were already created on the board, the OLD label remains on the board as an orphan. This skill does not migrate it. To rename: update the config, then manually delete or rename the old label on Trello. The `Using existing label` / `Created new label` logs let you audit what was bound.

**Trello built-in label hijack note**: Trello boards are pre-seeded with colored labels (blue, green, yellow, etc.) that users may have renamed. If someone renamed the built-in blue label to `"proj"` BEFORE running this skill, the match step above will silently bind to that pre-existing label. The orphan-log line (`Using existing label id=X name=N color=C`) is the only detection; read it and decide whether to keep the binding or delete the old label and re-run.

**3.** Ensure project card exists

- If `trello_card_id` is set on the project meta, verify the card exists and is not archived.
  - If valid, return the card ID and label IDs.
- If no card exists or the card is invalid:
  - Resolve the target list from the board (matching `trello.default_list`, default "Active", case-insensitive; fallback to the first list).
  - Create a new card with `name` = project name and `label_ids` = `[proj_label_id]`.
  - Record the returned card ID for linking by downstream sub-skills.

Return the board ID, card ID, `proj_label_id`, and `proj_task_label_id` for use by the trello-sync skill.

## Prerequisites

- Trello sync must be enabled (`trello.enabled: true` in config).
- A board ID must be set (per-project or global `trello.default_board_id`).
- Active project must be loaded.
- Trello MCP server must be running and reachable.

## Error Handling

- **Trello not enabled**: displays "Trello sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **No board ID configured**: stops and asks the user to configure a board ID.
- **Trello MCP unavailable**: displays "Trello MCP server not available. Check your MCP server configuration and restart Claude Code." and stops.
- **Card missing or archived**: creates a new card and links it.

## Output

Returns board ID, card ID, `proj_label_id`, and `proj_task_label_id` for use by the trello-sync skill.

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta is the stable link to the project's Trello card.
