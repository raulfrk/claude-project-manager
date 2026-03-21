---
name: trello-push
description: Execute push operations to Trello (create/update/complete/delete checklists and items). Sub-skill of trello-sync.
allowed-tools: mcp__trello__create_checklist, mcp__trello__batch_add_checklist_items, mcp__trello__batch_update_checklist_items, mcp__trello__update_checklist_item, mcp__trello__delete_checklist_item, mcp__trello__rename_checklist, mcp__trello__rename_checklist_item
argument-hint: "<diff-plan-json>"
---

Execute push operations to Trello from the diff plan. This is a sub-skill used by `/proj:trello-sync`.

Accepts the diff plan produced by `/proj:trello-diff`.

## Steps

### 1. Accept diff plan

- Receive the diff plan JSON (output from trello-diff).
- Extract the `trello_card_id` from `project_info`.

### 2. Create checklists (`push_create_checklist`)

For each entry:
- Call `mcp__trello__create_checklist` with `cardId` = trello_card_id, `name` = entry name.
- Record the returned checklist ID for linking and for resolving item creation below.

### 3. Create items (`push_create_item`)

When multiple items target the same checklist, use `mcp__trello__batch_add_checklist_items` to
create them in a single call (each item dict has `name` and optional `checked`). Group by
checklist ID and make one batch call per checklist.

- Resolve `checklist_id`: use the entry's `checklist_id` if set, or the newly created checklist ID (from step 2, matched by todo's parent).
- Record returned item IDs for linking.

### 4. Update items (`push_update_item`) and complete items (`push_complete_item`)

When multiple items need updating on the same card, use `mcp__trello__batch_update_checklist_items`
with `card_id` and an `updates` array (each entry has `checklist_id`, `item_id`, and optional
`name`/`state`).

For single items or fallback:
- Call `mcp__trello__update_checklist_item` to update the check item name or state.

### 5. Delete items (`push_delete_item`)

For each entry:
- Call `mcp__trello__delete_checklist_item` to remove the check item.

### 6. Rename checklists (`push_rename_checklist`)

For each entry:
- Call `mcp__trello__rename_checklist` to rename the checklist.

Return the creation results (new checklist IDs and item IDs) for use by downstream sub-skills (trello-link).

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
- Batch tools (`batch_add_checklist_items`, `batch_update_checklist_items`) reduce round-trips and return `{successes, failures}` for partial-failure handling.
