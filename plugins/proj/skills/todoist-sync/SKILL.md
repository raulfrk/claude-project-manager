---
name: todoist-sync
description: Manually trigger a full bidirectional Todoist sync. Always runs regardless of auto_sync setting. Use when the user says "sync with Todoist", "sync todos", or "pull from Todoist".
argument-hint: "[all | everything]"
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_todoist_full_sync, mcp__proj__tracking_git_flush
context: fork
agent: general-purpose
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Full bidirectional Todoist sync via single server-side call.

**1.** `mcp__proj__proj_session_context` → get config, project metadata, integration settings.
 - `integrations.todoist.enabled` false → stop: "Todoist sync not enabled. Run `/proj:init-plugin` to enable it."
 - No `integrations.todoist.project_id` → stop: "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first."

**2.** `mcp__plugin_proj_proj__proj_todoist_full_sync` (pass `project_name` if available).

**3.** Handle response:

- **`status == "needs_confirmation"`**: Show each `potential_links` entry:
  ```
  Local: "<todo title>" ↔ Todoist: "<task content>" (similarity: <score>%)
  ```
 Prompt per link:
  ```
  1. Link — connect this local todo to this Todoist task
  2. Skip — leave both as-is
  3. Create new — push and pull as separate tasks
  ```
 Build `confirmed_links` array from user choices. Re-call `mcp__plugin_proj_proj__proj_todoist_full_sync` w/ `confirmed_links` as JSON.

- **`status == "partial_success"`**: Show summary + each err. One retry: re-call `mcp__plugin_proj_proj__proj_todoist_full_sync` w/ `retry_failures` = response's `retry_token`. Retry also `partial_success` → show remaining errs, stop.

- **`status == "error"`**: Show err msg, stop.

- **`status == "success"`**:
 - `up_to_date` true: "Todoist sync complete. Everything up to date."
 - Otherwise show pulled/pushed counts:
    ```
    Todoist sync complete.
    <- Pulled from Todoist: {pulled.created} created, {pulled.updated} updated, {pulled.completed} closed
    -> Pushed to Todoist:   {pushed.created} created, {pushed.updated} updated, {pushed.completed} completed
    ```

**4.** `mcp__plugin_proj_proj__tracking_git_flush` w/ `commit_message="Sync: Todoist"`.

**5.** If `integrations.trello.enabled` true → output:
"Trello sync is enabled -- run `/proj:trello-sync` to also sync root todos with Trello."

Suggested next: `1. /proj:status` -- see updated project overview


## Prerequisites

- Active project loaded
- Todoist sync enabled (`todoist.enabled: true`)
- Project has `todoist_project_id` set

## Err Handling

- No active project → err from `proj_session_context`, stop
- Todoist not enabled → "Todoist sync not enabled. Run `/proj:init-plugin` to enable it.", stop
- No `todoist_project_id` → "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first.", stop
- API/sync errs → handled via `status == "error"` or `status == "partial_success"`

## Output

Sync summary w/ pulled/pushed counts. All up to date: `Todoist sync complete. Everything up to date.`
