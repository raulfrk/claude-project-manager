---
name: todoist-sync
description: Manually trigger a full bidirectional Todoist sync. Always runs regardless of auto_sync setting. Use when the user says "sync with Todoist", "sync todos", or "pull from Todoist".
argument-hint: "[all | everything]"
allowed-tools: mcp__proj__proj_session_context, mcp__proj__todo_list, mcp__proj__proj_todoist_diff, mcp__proj__proj_todoist_apply, mcp__proj__tracking_git_flush
context: fork
agent: general-purpose
---

Full bidirectional Todoist sync for the active project using batched operations.

**1.** Setup: Call `mcp__proj__proj_session_context` to get config, project metadata, and integration settings in one call.
   - Extract `integrations.todoist.enabled` and `integrations.todoist.project_id` (= `todoist_project_id`).
   - If `todoist.enabled` is false, stop with: "Todoist sync not enabled. Run `/proj:init-plugin` to enable it."
   - If no `todoist_project_id`, stop with: "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first."

**2.** Fetch Todoist tasks:
   - Call `mcp__todoist__todoist_find_tasks` with `project_id`. Collect all returned tasks.
   - This returns **open (uncompleted) tasks only**.

**3.** Compute sync plan + auto-apply pulls (single call):
   - Call `mcp__proj__proj_todoist_diff` with `todoist_tasks_json` set to the JSON-stringified array of ALL Todoist tasks collected in step 1, and `auto_apply` set to `true`.
   - This returns a JSON object with:
     - `plan`: the sync plan with `push_create`, `push_update`, `push_complete`, `ghost_close`, `root_only_cleanup`, and summary counts.
     - `auto_applied`: counts of pull operations already applied locally (created, updated, completed).
     - `project_info`: `todoist_project_id`.
   - **Pull operations (pull_create, pull_update, pull_complete) are already applied locally by this call.** No separate `proj_todoist_apply` is needed for pulls.
   - If all summary counts are zero: output "Todoist sync complete. Everything up to date." and stop.
   - If only pull counts are non-zero and push counts are all zero: output the pull summary and stop (pulls already applied).

**3b.** Resolve potential links (only if `plan.potential_links` is non-empty):
   - For each entry in `potential_links`, display:
     ```
     Local: "<todo title>" ↔ Todoist: "<task content>" (similarity: <score as %>%)
     ```
   - Prompt the user with:
     ```
     1. Link — connect this local todo to this Todoist task (set todoist_task_id)
     2. Link to other — enter a different Todoist task ID to link to
     3. Skip — leave both as-is (they'll diverge)
     4. Create new — ignore the match; push_create and pull_create as separate tasks
     ```
   - Handle each choice:
     - **Option 1 (Link)**: add `{ todo_id, todoist_task_id }` to `link_todoist_ids` for writeback. Remove the local todo from `push_create` and the Todoist task from `pull_create`.
     - **Option 2 (Link to other)**: prompt for the Todoist task ID, add `{ todo_id, <entered todoist_task_id> }` to `link_todoist_ids`. Remove the local todo from `push_create`.
     - **Option 3 (Skip)**: remove the local todo from `push_create` (don't create a duplicate in Todoist); the existing Todoist task stays as-is.
     - **Option 4 (Create new)**: put the local todo back in `push_create` and the Todoist task back in `pull_create` (both proceed independently).
   - All potential links must be resolved before proceeding to step 4.

**4.** Execute Todoist-side changes (batch calls, parallel where independent):

   a. **Ghost close** (if `ghost_close` is non-empty):
      - Call `mcp__todoist__todoist_complete_tasks` with `ids` = the `ghost_close` array.

   b. **Push create — Phase 1 (roots)** (if `push_create` is non-empty):
      - Call `mcp__todoist__todoist_add_tasks` with `push_create` (root todos only) as `tasks`.
        Each entry has: `content`, `priority`, `description`, `labels`, and optionally `dueString`, `parentId`.
      - The tool returns created tasks with their IDs. Build a `link_todoist_ids` array mapping each `todo_id` (from push_create) to the returned Todoist task ID.
      - Also build a `parent_id_map`: for each returned task, map `todo_id` → Todoist task ID.
      - If any entry had `complete_after_create: true`, collect those Todoist task IDs for completion.

   b-phase2. **Push create — Phase 2 (children)** (if `push_create_phase2` is non-empty):
      - For each entry in `push_create_phase2`:
        - Look up `entry["_parent_local_id"]` in `parent_id_map` to get the Todoist parent task ID.
        - Set `entry["parentId"]` = that Todoist task ID.
      - Call `mcp__todoist__todoist_add_tasks` with the updated `push_create_phase2` entries.
      - Add returned task IDs to `link_todoist_ids`.
      - If any entry had `complete_after_create: true`, collect those Todoist task IDs for completion.

   c. **Push update** (if `push_update` is non-empty):
      - Call `mcp__todoist__todoist_update_tasks` with the `push_update` array as `tasks`.
        Each entry has: `id`, `content`, `priority`, `description`, `labels`, and optionally `dueString`.

   d. **Push complete + ghost close completions** (if `push_complete` is non-empty or there are complete_after_create IDs):
      - Call `mcp__todoist__todoist_complete_tasks` with `ids` = combined array.

   e. **Root-only cleanup** (if `root_only_cleanup` is non-empty):
      - For each entry: call `mcp__todoist__todoist_delete` with `id=todoist_task_id`.
      - Collect the `todo_id` values as `cleared_todoist_ids`.

**5.** Link IDs locally (only if step 4b, 4b-phase2, or 4e produced results):
   - Build the `apply_json` object with ONLY:
     - `link_todoist_ids`: the mapping built in steps 3b, 4b, and 4b-phase2 (from potential_links resolution and push_create results).
     - `cleared_todoist_ids`: todo IDs from step 4e (root_only cleanup).
   - All other fields (`created_locally`, `updated_locally`, `completed_locally`) should be empty arrays -- pulls were already applied in step 3.
   - Call `mcp__proj__proj_todoist_apply` with the JSON-stringified object.
   - **Skip this step entirely** if there were no push_creates, no push_create_phase2, no potential_links resolutions, and no root_only_cleanup.

**6.** Summary: Display only if any changes occurred:
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

**7.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Sync: Todoist"`.

Suggested next: `1. /proj:status` -- see updated project overview

---

## Trello Sync

If `trello.enabled` is true in the config, after completing the Todoist sync above, output:
"Todoist sync complete. Trello sync is enabled -- run `/proj:trello-sync` to also sync root todos with Trello."

If the user invoked this skill with "sync all" or "sync everything", also output:
"To sync Trello too, run `/proj:trello-sync` separately."

## Prerequisites

- An active project must be loaded.
- Todoist sync must be enabled (`todoist.enabled: true` in config).
- Project must have a `todoist_project_id` set.

## Error Handling

- **No active project**: displays error from `proj_session_context` and stops.
- **Todoist not enabled**: displays "Todoist sync not enabled. Run `/proj:init-plugin` to enable it." and stops.
- **No todoist_project_id**: displays "Project not linked to Todoist. Set `todoist_project_id` via `mcp__proj__proj_update_meta` first." and stops.
- **Todoist API errors**: displays error from the specific Todoist tool call.
- **Partial push failures**: individual failures reported in the summary.

## Output

Sync summary: pulled from Todoist (created, updated, closed counts), pushed to Todoist (created, updated, completed counts). If ghost close or root-only cleanup occurred, those counts shown separately. If everything up to date: `Todoist sync complete. Everything up to date.`
