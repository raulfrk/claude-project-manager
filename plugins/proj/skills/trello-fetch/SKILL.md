---
name: trello-fetch
description: Fetch the Trello card state (checklists and items) for the active project. Sub-skill of trello-sync.
disable-model-invocation: "true"
allowed-tools: mcp__trello__get_card_checklists, mcp__proj__proj_get_active
argument-hint: ""
---

Fetch the current Trello card state for the active project. This is a sub-skill used by `/proj:trello-sync`.

## Steps

### 1. Get card ID

- Call `mcp__proj__proj_get_active` to get the project's `trello_card_id`.
- If no `trello_card_id` is set, stop: "No Trello card linked. Run `/proj:trello-setup` first."

### 2. Fetch checklists

- Call `mcp__trello__get_card_checklists` with `cardId` = the project's `trello_card_id`.
- The result is a JSON array of checklists, each with `id`, `name`, and `checkItems` array (each item has `id`, `name`, `state`).

### 3. Return card data

- Format the result as: `{"checklists": [<the array>]}`
- Return this card data for use by downstream sub-skills (trello-diff).

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
