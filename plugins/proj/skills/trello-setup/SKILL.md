---
name: trello-setup
description: Ensure the proj label and project card exist on the Trello board. Sub-skill of trello-sync.
disable-model-invocation: "true"
allowed-tools: mcp__trello__get_board, mcp__trello__list_boards, mcp__proj__proj_get_active, mcp__proj__config_load
argument-hint: ""
---

Ensure the `proj` label and project card exist on the configured Trello board. This is a sub-skill used by `/proj:trello-sync`.

## Steps

### 1. Read config and active project

- Call `mcp__proj__config_load` -- read `trello.*` config values. Note `default_board_id`, `default_list`.
- Call `mcp__proj__proj_get_active` -- get active project name, per-project trello config, and `trello_card_id` from project meta.
- Check prerequisites:
  - `trello.enabled` must be `true`. If not, stop: "Trello sync not enabled. Set `trello.enabled: true` in `~/.claude/proj.yaml`."
  - A board ID must be set (per-project `trello.board_id` or global `trello.default_board_id`). If neither is set, stop and ask the user to configure a board ID.
- Resolve effective board ID = per-project `trello.board_id` if set, else global `trello.default_board_id`.

**Failure: Trello MCP server unavailable**
If the Trello MCP server is not reachable -- for example, a tool call raises a
tool-not-found error, returns a connection error, or is simply not registered -- stop immediately
and say:

> "Trello MCP server 'trello' is not available. Verify the server is running and that the
> MCP server is registered with the name `trello`."

Do not proceed with any further steps.

### 2. Ensure `proj` label exists

- Call `mcp__trello__get_board` with `boardId` set to the effective board ID to retrieve board labels.
- If no label named `proj` exists, create one (name `proj`, color `blue`).
- Record the label ID.

### 3. Ensure project card exists

- If `trello_card_id` is set on the project meta, verify the card exists and is not archived.
  - If valid, return the card ID and label ID.
- If no card exists or the card is invalid:
  - Resolve the target list from the board (matching `trello.default_list`, default "Active", case-insensitive; fallback to the first list).
  - Create a new card with `name` = project name and `idLabels` = the `proj` label ID.
  - Record the returned card ID for linking by downstream sub-skills.

Return the board ID, card ID, and label ID for use by downstream sub-skills (trello-fetch).

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta is the stable link to the project's Trello card.
