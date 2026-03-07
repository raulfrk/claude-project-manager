---
name: sync
description: Manually trigger a full bidirectional Todoist sync. Always runs regardless of auto_sync setting. Use when the user says "sync with Todoist", "sync todos", or "pull from Todoist".
argument-hint: "[all | everything]"
disable-model-invocation: "true"
allowed-tools: mcp__proj__proj_get_active, mcp__proj__todo_list, mcp__proj__proj_todoist_diff, mcp__proj__proj_todoist_apply, mcp__proj__config_load
context: fork
agent: general-purpose
---

Full bidirectional Todoist sync for the active project using batched operations.

## Todoist Tool Resolution

The Todoist MCP server name is configurable. **Before making any Todoist tool call**, read
`todoist.mcp_server` from the config (via `mcp__proj__config_load`) and substitute it as the
prefix. All `mcp__claude_ai_Todoist__<tool>` references below are templates -- replace
`claude_ai_Todoist` with the actual server name.

Example: if `todoist.mcp_server` is `sentry`, call `mcp__sentry__find-tasks` not
`mcp__claude_ai_Todoist__find-tasks`.

## Steps

0. **Setup** (parallel):
   - Call `mcp__proj__config_load` -- check `todoist.enabled`, get `todoist.mcp_server`.
   - Call `mcp__proj__proj_get_active` -- get `todoist_project_id`.
   - If `todoist.enabled` is false: stop with "Todoist sync is not enabled. Set todoist.enabled: true in ~/.claude/proj.yaml to use /proj:sync."
   - If no `todoist_project_id`: stop with "Project not linked to Todoist. Set todoist_project_id via mcp__proj__proj_update_meta first."

1. **Fetch Todoist tasks**:
   - Call `mcp__claude_ai_Todoist__find-tasks` with `projectId` and `limit: 100`. Collect all tasks (paginate with `cursor` if `hasMore: true`).
   - This returns **open (uncompleted) tasks only**.

2. **Compute sync plan + auto-apply pulls** (single call):
   - Call `mcp__proj__proj_todoist_diff` with `todoist_tasks_json` set to the JSON-stringified array of ALL Todoist tasks collected in step 1, and `auto_apply` set to `true`.
   - This returns a JSON object with:
     - `plan`: the sync plan with `push_create`, `push_update`, `push_complete`, `ghost_close`, `root_only_cleanup`, and summary counts.
     - `auto_applied`: counts of pull operations already applied locally (created, updated, completed).
     - `project_info`: `mcp_server` and `todoist_project_id`.
   - **Pull operations (pull_create, pull_update, pull_complete) are already applied locally by this call.** No separate `proj_todoist_apply` is needed for pulls.
   - If all summary counts are zero: output "Todoist sync complete. Everything up to date." and stop.
   - If only pull counts are non-zero and push counts are all zero: output the pull summary and stop (pulls already applied).

3. **Execute Todoist-side changes** (batch calls, parallel where independent):

   a. **Ghost close** (if `ghost_close` is non-empty):
      - Call `mcp__claude_ai_Todoist__complete-tasks` with `ids` = the `ghost_close` array.

   b. **Push create** (if `push_create` is non-empty):
      - Call `mcp__claude_ai_Todoist__add-tasks` with the `push_create` array as `tasks`.
        Each entry has: `content`, `priority`, `description`, `labels`, and optionally `dueString`, `parentId`.
      - The tool returns created tasks with their IDs. Build a `link_todoist_ids` array mapping each `todo_id` (from push_create) to the returned Todoist task ID.
      - If any entry had `complete_after_create: true`, collect those Todoist task IDs for completion.

   c. **Push update** (if `push_update` is non-empty):
      - Call `mcp__claude_ai_Todoist__update-tasks` with the `push_update` array as `tasks`.
        Each entry has: `id`, `content`, `priority`, `description`, `labels`, and optionally `dueString`.

   d. **Push complete + ghost close completions** (if `push_complete` is non-empty or there are complete_after_create IDs):
      - Call `mcp__claude_ai_Todoist__complete-tasks` with `ids` = combined array.

   e. **Root-only cleanup** (if `root_only_cleanup` is non-empty):
      - For each entry: call `mcp__claude_ai_Todoist__delete-object` with `type="task"` and `id=todoist_task_id`.
      - Collect the `todo_id` values as `cleared_todoist_ids`.

4. **Link IDs locally** (only if step 3b or 3e produced results):
   - Build the `apply_json` object with ONLY:
     - `link_todoist_ids`: the mapping built in step 3b (from push_create results).
     - `cleared_todoist_ids`: todo IDs from step 3e (root_only cleanup).
   - All other fields (`created_locally`, `updated_locally`, `completed_locally`) should be empty arrays -- pulls were already applied in step 2.
   - Call `mcp__proj__proj_todoist_apply` with the JSON-stringified object.
   - **Skip this step entirely** if there were no push_creates and no root_only_cleanup.

5. **Summary**: Display only if any changes occurred:
   ```
   Todoist sync complete.
   <- Pulled from Todoist: {pull_create_count} created, {pull_update_count} updated, {pull_complete_count} closed
   -> Pushed to Todoist:   {push_create_count} created, {push_update_count} updated, {push_complete_count} completed
   ```
   Add these lines only if the counts are non-zero:
   ```
   Ghosts resolved: {ghost_close_count} Todoist tasks closed (matched archived todos)
   Removed from Todoist (root_only): {root_only_cleanup_count} child tasks deleted
   ```

Suggested next: /proj:status -- see updated project overview

---

## Trello Sync

If `trello.enabled` is true in the config, after completing the Todoist sync above, output:
"Todoist sync complete. Trello sync is enabled -- run /proj:trello-sync to also sync root todos with Trello."

If the user invoked this skill with "sync all" or "sync everything", also output:
"To sync Trello too, run /proj:trello-sync separately."
