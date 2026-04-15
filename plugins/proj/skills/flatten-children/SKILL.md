---
name: flatten-children
description: Migrate nested child todos of a parent to flat top-level todos with group:<parent-id> tag, then delete originals. Use when the user says "flatten children", "migrate children to flat", or "flatten <id>".
allowed-tools: mcp__plugin_proj_proj__proj_session_context, mcp__plugin_proj_proj__todo_get, mcp__plugin_proj_proj__todo_list, mcp__plugin_proj_proj__todo_add, mcp__plugin_proj_proj__todo_delete, mcp__plugin_proj_proj__todo_update, mcp__plugin_proj_proj__todo_notes_append, mcp__plugin_proj_proj__tracking_git_flush, mcp__plugin_todoist_todoist__todoist_find_tasks, mcp__plugin_trello_trello__get_card, mcp__plugin_trello_trello__archive_card, mcp__plugin_jira_jira__jira_get_issue, mcp__plugin_jira_jira__jira_update_issues
argument-hint: "<parent-id>"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Migrate nested children of parent todo to flat top-level todos tagged `group:<parent_id>`, then delete originals.

**First**: `proj_session_context` → get active project name, config, integrations. Pass `project.name` to all `todo_*` calls.

Parse `$ARGUMENTS` → extract `<parent_id>`. Missing → abort: "Usage: `/proj:flatten-children <parent-id>`"

---

## Step 1 — Collect child data + skip already-migrated

`TaskCreate("Collect child data + skip already-migrated")` → mark in_progress

- `todo_get(parent_id)` → confirm parent exists; abort if not found
- `todo_list(parent_id=<parent_id>)` → get children array
- No children → abort: "Todo <parent_id> has no children. Nothing to flatten."
- Filter children: skip any already tagged `group:<parent_id>` (already migrated) → note skipped IDs
- Store `child_data[]`: `{id, title, priority, tags, notes, blocked_by, blocks}` for each remaining child
- All children already migrated → abort: "All children already migrated."

Mark completed.

---

## Step 2 — Create flat todos via todo_add

`TaskCreate("Create flat todos via todo_add")` → mark in_progress

- `created_ids = []`, `id_map = {}` (old child ID → new flat ID)
- Each child in `child_data`:
  - `new_tags = [...original_tags, "group:<parent_id>"]`
  - `todo_add(title=child.title, priority=child.priority, tags=new_tags, notes=child.notes)`
  - On success: append new ID to `created_ids`; record `id_map[child.id] = new_id`
  - On failure: `todo_delete` each ID in `created_ids` in reverse order → abort: "Failed to create flat todo for child <child.id>. Rolled back <N> created todos."
- All created → proceed

Mark completed.

---

## Step 3 — Set blocked_by edges

`TaskCreate("Set blocked_by edges")` → mark in_progress

- Each entry in `child_data` where `blocked_by` or `blocks` non-empty:
  - Translate old child IDs → new flat IDs via `id_map`
  - IDs outside `id_map` (external blockers): keep as-is
  - `todo_update(todo_id=blocked_id, blocked_by_set=[...<blocker-ids>])` for each translated edge
  - Log failures as warnings; continue (non-fatal)

Mark completed.

---

## Step 4 — Verify new todos exist

`TaskCreate("Verify new todos exist")` → mark in_progress

- Each `id` in `created_ids`: `todo_get(id)` → confirm exists + has `group:<parent_id>` tag
- Any missing → ABORT: "Verification failed: todo <id> not found after creation."

Mark completed.

---

## Step 5 — Todoist: verify new tasks → delete originals  [ABORT on failure]

`TaskCreate("Todoist: verify new tasks → delete originals")` → mark in_progress

- Todoist not in integrations → skip (mark completed, continue)
- Each `id` in `created_ids`: `todoist_find_tasks` → confirm synced to Todoist
  - Sync missing → ABORT: "Todoist sync failed for todo <id>. Original children NOT deleted. Manual cleanup needed."
- Delete original child todos: `todo_delete(child.id)` for each in `child_data`
  - Todoist delete hook fails → ABORT: "Todoist sync failed during delete. Original children NOT deleted. Manual cleanup needed."

Mark completed.

---

## Step 6 — Trello: verify new cards → archive originals  [WARN on failure]

`TaskCreate("Trello: verify new cards → archive originals")` → mark in_progress

- Trello not in integrations → skip (mark completed, continue)
- Each `id` in `created_ids`: `trello_get_card` → confirm card exists
  - Missing → WARN: "Trello card missing for todo <id>. Skipping Trello archive for originals." → continue
- Archive original child cards: `trello_archive_card` for each original child
  - Failure → WARN inline, continue (do not abort)

Mark completed.

---

## Step 7 — Jira: verify new issues → transition originals  [WARN on failure]

`TaskCreate("Jira: verify new issues → transition originals")` → mark in_progress

- Jira not in integrations → skip (mark completed, continue)
- Each `id` in `created_ids`: `jira_get_issue` → confirm issue exists
  - Missing → WARN: "Jira issue missing for todo <id>. Skipping Jira transition for originals." → continue
- Transition original child issues to Done/Closed: `jira_update_issues` w/ status transition
  - Failure → WARN inline, continue (do not abort)

Mark completed.

---

## Step 8 — Delete original children + log failures

`TaskCreate("Delete original children + log failures")` → mark in_progress

- Skip children already deleted in Step 5 (Todoist path)
- `todo_delete(child.id)` each remaining original child ID
- Failure → WARN: "Failed to delete original child <id>. Manual cleanup needed." → continue (non-fatal)

Mark completed.

---

## Step 9 — Write decompose_result to parent notes

`TaskCreate("Write decompose_result to parent notes")` → mark in_progress

- `todo_notes_append(parent_id, 'decompose_result: {"created_ids": [<created_ids>], "id_map": {<id_map>}}')`

Mark completed.

---

## Step 10 — Git flush

`TaskCreate("Git flush")` → mark in_progress

- `tracking_git_flush(commit_message="flatten-children: <parent_id>")`

Mark completed.

---

## Err Handling

- Todoist failure → ABORT entire operation; report succeeded steps so far
- Trello/Jira failure → WARN inline, continue
- Missing integration → skip silently
- Already-migrated children (have `group:<parent_id>` tag) → skip w/ note
- Rollback on todo_add failure: delete created IDs in reverse order before aborting

## Prerequisites

- Active project loaded (`proj_session_context` first)
- Valid parent todo ID w/ children

## Output

Summary table after completion:

```
Flattened <N> children of todo <parent_id>:
- Created: <created_ids>
- Skipped (already migrated): <skipped_ids or "none">
- Deleted originals: <deleted_ids>
- Warnings: <any WARN msgs or "none">
```
