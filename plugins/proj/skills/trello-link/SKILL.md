---
name: trello-link
description: Link returned Trello IDs to local todos and flush git tracking. Sub-skill of trello-sync.
allowed-tools: mcp__proj__proj_trello_apply, mcp__proj__tracking_git_flush
argument-hint: "<creation-results-json>"
---

Link Trello IDs back to local todos after push operations. This is a sub-skill used by `/proj:trello-sync`.

Accepts the creation results produced by `/proj:trello-push`.

**1.** Accept creation results

- Receive the creation results JSON (output from trello-push) containing new checklist IDs and item IDs mapped to local todo IDs.

**2.** Link IDs locally

- Call `mcp__proj__proj_trello_apply` with the link data:
  ```json
  {
    "link_trello_ids": [
      {"todo_id": "<todo_id>", "trello_checklist_id": "<new_checklist_id>"},
      {"todo_id": "<todo_id>", "trello_checklist_item_id": "<new_item_id>"}
    ]
  }
  ```
- If a new card was created (from trello-setup), also include `link_trello_card_id` set to the new card ID.
- **Batch linking**: combine all ID links into a single `proj_trello_apply` call.

**3.** Git tracking flush

- Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Trello"`.

**4.** Display results

```
Trello sync complete.
<- Pulled from Trello: {created} created, {updated} updated, {completed} completed, {reopened} reopened
-> Pushed to Trello:   {checklists_created} checklists, {items_created} items created, {items_updated} updated, {items_completed} completed
```

If all counts are zero: "Trello sync complete. Everything up to date."

## Notes

- All Trello MCP tool names use the static pattern `mcp__trello__<tool_name>`.
- `trello_card_id` on project meta is the stable link to the project's Trello card.
- `trello_checklist_id` on root todos links to the Trello checklist.
- `trello_checklist_item_id` on all todos links to the Trello check item.
