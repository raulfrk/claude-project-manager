---
name: trello-diff
description: Compute the diff between local todos and Trello card state. Sub-skill of trello-sync.
allowed-tools: mcp__proj__proj_trello_diff, mcp__proj__proj_get_active
argument-hint: "<card-data-json>"
---

Compute the diff between local todos and the Trello card state. This is a sub-skill used by `/proj:trello-sync`.

Accepts the card data produced by `/proj:trello-fetch`.

**1.** Accept card data

- Receive the Trello card state JSON (output from trello-fetch).

**2.** Compute diff

- Call `mcp__proj__proj_trello_diff` with:
  - `trello_card_json` = the card state JSON from step 1
  - `auto_apply` = `true`
  - `project_name` = active project name (optional if already active)
- The response includes:
  - `plan` -- the full diff with all push/pull operations
  - `project_info` -- board_id, trello_card_id, default_list
  - `auto_applied` -- counts of pull operations already applied locally

**3.** Display plan

Show the diff plan summarizing what will be pushed to Trello:

- `push_create_checklist` -- new checklists to create
- `push_create_item` -- new items to add
- `push_update_item` -- items to update (name changes)
- `push_complete_item` -- items to mark complete
- `push_delete_item` -- items to remove
- `push_rename_checklist` -- checklists to rename

Also show what was auto-applied locally (pull operations).

Return the diff plan for use by downstream sub-skills (trello-push).

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
- Pull operations are auto-applied locally by `proj_trello_diff` when `auto_apply=true`.
