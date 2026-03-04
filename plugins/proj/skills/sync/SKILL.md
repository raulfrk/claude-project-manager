---
name: sync
description: Manually trigger a full bidirectional Todoist sync. Always runs regardless of auto_sync setting. Use when the user says "sync with Todoist", "sync todos", or "pull from Todoist".
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__todo_add, mcp__proj__todo_delete, mcp__proj__config_load, mcp__proj__proj_find_archived_by_title
---

Full bidirectional Todoist sync for the active project.

## Field Mapping

| Local field | Todoist field |
|---|---|
| `title` | `content` |
| `status` (done) | `checked` (true) |
| `priority` low/medium/high | `priority` p4/p3/p2 |
| `notes` | `description` |
| `tags` | `labels` |
| `due_date` (ISO date string, e.g. `"2026-03-15"`) | `dueString` (natural language or ISO date) |
| `parent` (dot-notation ID) | `parentId` (Todoist task ID of parent) |

## Priority Mapping

- local `high` → Todoist `p2`
- local `medium` → Todoist `p3`
- local `low` → Todoist `p4`

## Todoist Tool Resolution

The Todoist MCP server name is configurable. **Before making any Todoist tool call**, read
`todoist.mcp_server` from the config (via `mcp__proj__config_load`) and substitute it as the
prefix. All `mcp__claude_ai_Todoist__<tool>` references below are templates — replace
`claude_ai_Todoist` with the actual server name.

Example: if `todoist.mcp_server` is `sentry`, call `mcp__sentry__find-tasks` not
`mcp__claude_ai_Todoist__find-tasks`.

## Steps

1. **Setup**: Call `mcp__proj__proj_get_active` — get active project with `todoist_project_id`.
   - If no `todoist_project_id`, ask: "This project isn't linked to Todoist. Create a Todoist project for it?"
   - If yes: call `mcp__claude_ai_Todoist__add-projects` and store the returned ID via `mcp__proj__proj_update_meta`.
   - If no: stop.

2. **Fetch both sides**:
   - Call `mcp__claude_ai_Todoist__find-tasks` with `projectId` (use `limit: 100`). This returns **open (uncompleted) tasks only**. Collect all tasks (paginate if `hasMore: true`).
   - Call `mcp__proj__todo_list` — get active local todos (pending + in_progress).
   - Build lookup maps:
     - `todoist_by_id`: Todoist task ID → Todoist task object (open tasks only)
     - `local_by_todoist_id`: `todoist_task_id` → local todo
     - `local_unlinked`: local todos where `todoist_task_id` is null
     - `local_open_with_todoist_id`: local todos where `status != done` AND `todoist_task_id` is not null

3. **Todoist → Local (pull)**:

   For each Todoist task:
   - **Not in local** (no `todoist_task_id` match): This is a new task added in Todoist.
     - **Ghost check**: Before creating, call `mcp__proj__proj_find_archived_by_title` with the Todoist task's `content` as the title.
       - If result has `exact_match` or `fuzzy_matches` is non-empty: display prompt:
         ```
         ⚠️  Ghost detected: Todoist task "<title>" may already be done locally.
             Closest match in archive: "<archive-title>" (exact|fuzzy, ratio: X.XX)

         1. Skip → Complete the Todoist task and skip creating locally
         2. Create → Create as new local todo anyway
         ```
       - If user picks **Skip**: call `mcp__claude_ai_Todoist__complete-tasks` for this Todoist task ID. Track as `ghost_closed += 1`. Skip to the next Todoist task.
       - If user picks **Create**: proceed with `todo_add` as normal.
       - If no match found: proceed with `todo_add` as normal.
     - Call `mcp__proj__todo_add` to create locally. Set title, priority (map from Todoist), notes from description, tags from labels.
     - Then call `mcp__proj__todo_update` to set `todoist_task_id` to this Todoist task's ID. If the Todoist task has a due date (`due.date`), also set `due_date` to that ISO date string (e.g. `"2026-03-15"`).
     - Track as: created_locally += 1

   - **In local** (matched by `todoist_task_id`): Potential update.
     - Compare `todo.updated` (local ISO date string, e.g. "2026-02-27") vs Todoist `updated_at` (ISO datetime — truncate to date for comparison).
     - **If Todoist is newer** (Todoist date > local date): overwrite local with Todoist values — call `mcp__proj__todo_update` with title, priority, tags (from Todoist `labels`, full replacement), and `due_date` (from Todoist `due.date` if present, or `null` to clear if absent). For `notes`/`description`, use the sync-link logic below. If Todoist task is checked and local is not done, call `mcp__proj__todo_complete`. Track as: updated_locally += 1.
     - **If local is newer or equal**: local wins — skip (local will be pushed in step 4).

   **Notes/description sync-link logic** (apply whenever pulling a Todoist description):
   - Let `new_desc` = Todoist task's `description` (empty string if absent).
   - Let `synced` = local todo's `todoist_description_synced` field.
   - If `new_desc == synced`: description unchanged since last pull — do NOT touch local `notes`.
   - If `new_desc != synced` (Todoist description changed):
     - If local `notes` is empty: set `notes = new_desc`.
     - If local `notes` is non-empty: append `"\n\n---\n" + new_desc` to `notes`.
   - Always update `todoist_description_synced = new_desc` via `mcp__proj__todo_update`.
   - (When creating a new local todo from a Todoist task in the "Not in local" branch above, set `notes = description` and `todoist_description_synced = description` in one `todo_update` call.)

4. **Local → Todoist (push)**:

   **Resolve `effective_root_only`** before iterating:
   - From `config_load`, read `todoist.root_only` (global default).
   - From `proj_get_active`, read `project.todoist.root_only` (per-project override, may be null/absent).
   - `effective_root_only = project.todoist.root_only ?? global.todoist.root_only ?? false`

   **If `effective_root_only` is true — cleanup existing child todos in Todoist**:
   - Scan `todoist_by_id` (all open Todoist tasks fetched in step 2) for tasks that have a `parentId` set (i.e., they are subtasks in Todoist).
   - For each such Todoist task that also has a matching local todo with a `parent` set (i.e., it is a child locally): call `mcp__claude_ai_Todoist__delete-object` with `type="task"` and `id=<todoist_task_id>`, then call `mcp__proj__todo_update` to clear `todoist_task_id` (set to null) on the local todo. Track as: deleted_from_todoist += 1.

   For each local todo:
   - **If `effective_root_only` is true and todo has a `parent`**: skip — do not push child todos to Todoist.
   - **No `todoist_task_id`** (unlinked): New local todo — push to Todoist.
     - If it has a `parent`, ensure the parent's Todoist task ID is known (from `todoist_by_id` or just created). Set `parentId` on the new Todoist task.
     - Process root todos before child todos (sort: todos with no parent first).
     - Call `mcp__claude_ai_Todoist__add-tasks` with content, priority, description (from notes), labels (from tags), parentId (if child), and `dueString` set to `due_date` if the local todo has a `due_date` set.
     - Call `mcp__proj__todo_update` to store the returned Todoist task ID as `todoist_task_id`.
     - If todo is done, also call `mcp__claude_ai_Todoist__complete-tasks`.
     - Track as: created_in_todoist += 1

   - **Has `todoist_task_id`** and local is newer (local date > Todoist date): Push local changes.
     - Call `mcp__claude_ai_Todoist__update-tasks` with updated content, priority, description, labels (from local tags, full replacement), and `dueString` set to `due_date` if set (omit `dueString` entirely if `due_date` is null/absent — do not pass an empty string).
     - If local status is done and Todoist is not checked: call `mcp__claude_ai_Todoist__complete-tasks`.
     - Track as: updated_in_todoist += 1

5. **Closed/deleted propagation**:

   - **Possibly closed or deleted in Todoist** (local open todo has `todoist_task_id` but that ID is not in `todoist_by_id`):
     - For each such todo in `local_open_with_todoist_id`: call `mcp__claude_ai_Todoist__fetch-object` with `id=todoist_task_id` and `type="task"`.
     - If fetch succeeds and task has `checked: true` (completed): call `mcp__proj__todo_complete` to mark local done. Track as: closed_locally += 1.
     - If fetch fails or task not found (deleted from Todoist): call `mcp__proj__todo_complete` to mark local done. Track as: closed_locally += 1.
     - Do NOT call `find-completed-tasks` at any point during normal sync.

   - **Deleted locally** (Todoist task ID appears in Todoist but has no matching local todo in `local_by_todoist_id` AND is not in `local_unlinked` — i.e., it was previously synced but the local record is gone):
     - This case cannot be reliably detected without tombstones. Skip — treat unmatched Todoist tasks as "new" (already handled in step 3). Document this limitation to the user if relevant.

6. **Summary**: Display only if any changes occurred:
   ```
   Todoist sync complete.
   ← Pulled from Todoist: {created_locally} created, {updated_locally} updated, {closed_locally} closed (via secondary fetch)
   ⚠️  Ghosts resolved: {ghost_closed} Todoist tasks closed (matched archived todos)
   → Pushed to Todoist:   {created_in_todoist} created, {updated_in_todoist} updated
   🗑  Removed from Todoist (root_only): {deleted_from_todoist} child tasks deleted
   ```
   (Omit the "Ghosts resolved" line if `ghost_closed == 0`.)
   (Omit the "Removed from Todoist" line if `deleted_from_todoist == 0`.)
   If all counts are zero: "Todoist sync complete. Everything up to date."

💡 Suggested next: /proj:status — see updated project overview

---

## Trello Sync

If `trello.enabled` is true in the config, after completing the Todoist sync above, offer to run a Trello sync:

```
Todoist sync complete. Trello sync is enabled — run /proj:trello-sync to also sync root todos with Trello.
```

Or, if the user invoked this skill with "sync all" or "sync everything", automatically invoke `/proj:trello-sync` after the Todoist sync completes.
