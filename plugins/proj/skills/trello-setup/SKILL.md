---
name: trello-setup
description: Ensure the proj (blue) and proj-task (green) labels and project card exist on the Trello board. Sub-skill of trello-sync.
allowed-tools: mcp__trello__get_board, mcp__trello__list_boards, mcp__proj__proj_session_context, mcp__proj__proj_get_active, mcp__proj__config_load
---

Ensure the `proj` label and project card exist on the configured Trello board. This is a sub-skill used by `/proj:trello-sync`.

**1.** Read config and active project

- Call `mcp__proj__proj_session_context` -- read all config, project metadata, and integration settings in one call.
  - From the result, extract `integrations.trello.enabled`, `integrations.trello.board_id` (global default), `integrations.trello.card_id` (project's card), and `project.name`.
- Check prerequisites:
  - `integrations.trello.enabled` must be `true`. If not, stop with: "Trello sync not enabled. Run `/proj:init-plugin` to enable it."
  - A board ID must be set (per-project `trello.board_id` or global `integrations.trello.board_id`). If neither is set, stop and ask the user to configure a board ID.
- Resolve effective board ID = per-project `trello.board_id` if set, else global `integrations.trello.board_id`.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Trello MCP server not available. Check your MCP server configuration and restart Claude Code."

Do not proceed with any further steps.

**2.** Ensure `proj` and `proj-task` labels exist

- Call `mcp__trello__get_board` with `boardId` set to the effective board ID to retrieve board labels.
- For label name `proj` (color `blue`):
  - If no label named `proj` exists, create one (name `proj`, color `blue`).
  - Record its ID as `proj_label_id`.
- For label name `proj-task` (color `green`):
  - If no label named `proj-task` exists, create one (name `proj-task`, color `green`).
  - Record its ID as `proj_task_label_id`.
- Both IDs are used downstream: `proj_label_id` for the project tracking card and `proj_task_label_id` for per-todo cards.

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
