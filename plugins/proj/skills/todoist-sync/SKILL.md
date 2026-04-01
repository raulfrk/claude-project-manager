---
name: todoist-sync
description: Manually trigger a full bidirectional Todoist sync. Always runs regardless of auto_sync setting. Use when the user says "sync with Todoist", "sync todos", or "pull from Todoist".
argument-hint: "[all | everything]"
allowed-tools: mcp__proj__proj_session_context, mcp__proj__proj_todoist_full_sync, mcp__proj__tracking_git_flush
context: fork
agent: general-purpose
---

Full bidirectional Todoist sync using a single server-side call.

**1.** Setup: Call `mcp__proj__proj_session_context` to get config, project metadata, and integration settings.
   - If `integrations.todoist.enabled` is false, stop with: "Todoist sync not enabled. Run `/proj:init-plugin` to enable it."
   - If no `integrations.todoist.project_id`, stop with: "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first."

**2.** Sync: Call `mcp__plugin_proj_proj__proj_todoist_full_sync` (pass `project_name` if available from session context).

**3.** Handle response:

- **`status == "needs_confirmation"`**: Display each entry in `potential_links`:
  ```
  Local: "<todo title>" ↔ Todoist: "<task content>" (similarity: <score>%)
  ```
  Prompt per link:
  ```
  1. Link — connect this local todo to this Todoist task
  2. Skip — leave both as-is
  3. Create new — push and pull as separate tasks
  ```
  Build a `confirmed_links` array from user choices. Re-call `mcp__plugin_proj_proj__proj_todoist_full_sync` with `confirmed_links` as JSON.

- **`status == "partial_success"`**: Display the summary and list each error. Offer one retry: re-call `mcp__plugin_proj_proj__proj_todoist_full_sync` with `retry_failures` set to the response's `retry_token`. If retry also returns `partial_success`, show remaining errors and stop.

- **`status == "error"`**: Display the error message and stop.

- **`status == "success"`**: Display the summary:
  - If `up_to_date` is true: "Todoist sync complete. Everything up to date."
  - Otherwise show pulled/pushed counts:
    ```
    Todoist sync complete.
    <- Pulled from Todoist: {pulled.created} created, {pulled.updated} updated, {pulled.completed} closed
    -> Pushed to Todoist:   {pushed.created} created, {pushed.updated} updated, {pushed.completed} completed
    ```

**4.** Git flush: Call `mcp__plugin_proj_proj__tracking_git_flush` with `commit_message="Sync: Todoist"`.

**5.** Trello note: If `integrations.trello.enabled` is true in the session context, output:
"Trello sync is enabled -- run `/proj:trello-sync` to also sync root todos with Trello."

Suggested next: `1. /proj:status` -- see updated project overview

---

## Prerequisites

- An active project must be loaded.
- Todoist sync must be enabled (`todoist.enabled: true` in config).
- Project must have a `todoist_project_id` set.

## Error Handling

- **No active project**: displays error from `proj_session_context` and stops.
- **Todoist not enabled**: displays "Todoist sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **No todoist_project_id**: displays "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first." and stops.
- **API/sync errors**: handled via `status == "error"` or `status == "partial_success"` responses.

## Output

Sync summary with pulled/pushed counts. If everything up to date: `Todoist sync complete. Everything up to date.`
