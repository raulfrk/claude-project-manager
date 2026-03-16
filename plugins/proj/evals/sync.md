# E2E Eval: sync

## Methodology
This is a TRUE end-to-end eval. The agent MUST:
1. Read `/home/raul/projects/claude-project-manager/plugins/proj/skills/sync/SKILL.md`
2. Extract instructions after the second `---`
3. Follow those instructions step by step, executing every MCP tool call the skill prescribes
4. Do NOT call MCP tools directly — only call what the skill instructions tell you to call

> **API dependency**: All scenarios require a valid Todoist API token and a reachable Todoist MCP server. The MCP server name is read from `todoist.mcp_server` in proj config.

## Setup

1. Call `mcp__proj__config_load` -- verify `todoist.enabled` is `true` and note the `todoist.mcp_server` value.
2. Call `mcp__proj__proj_init` with `name="eval-test-sync"`, `path="/tmp/claude-1000/eval-sync"`.
3. Create a Todoist project for the eval (via `mcp__<todoist_server>__add-projects` with name `"eval-test-sync"`). Record the returned `todoist_project_id`.
4. Call `mcp__proj__proj_update_meta` to set `todoist_project_id` on the eval project.
5. Add local test todos:
   - `mcp__proj__todo_add` with title `"Sync push test A"` (root todo, no todoist_task_id).
   - `mcp__proj__todo_add` with title `"Sync push test B"` (root todo, no todoist_task_id).
   - `mcp__proj__todo_add` with title `"Sync child test"` as a child of todo A (to verify child handling).

## Test Scenarios

### Scenario 1: Push new local todos to Todoist

- **Prompt**: Follow the skill instructions as if user said `/proj:sync`.
- **Expected**: Per SKILL.md:
  - Step 0 (Setup): Calls `config_load` and `proj_get_active` in parallel. Checks `todoist.enabled` and `todoist_project_id`.
  - Step 1: Calls `find-tasks` with `projectId` to fetch Todoist tasks (using resolved MCP server name from config).
  - Step 2: Calls `proj_todoist_diff` with `todoist_tasks_json` and `auto_apply=true`.
  - Step 3: Executes Todoist-side push_create via `add-tasks`. Builds `link_todoist_ids` mapping.
  - Step 4: Calls `proj_todoist_apply` with `link_todoist_ids` to store Todoist task IDs locally.
  - Step 5: Summary output includes "Pushed to Todoist: 2 created".
  - Step 6: Calls `tracking_git_flush` with `commit_message="Sync: Todoist"`.
- **Assert**:
  - Call `mcp__proj__todo_list` -- root todos A and B now have `todoist_task_id` set.
  - Call `mcp__<todoist_server>__find-tasks` with the eval Todoist project ID -- 2 tasks exist with matching titles.

### Scenario 2: Pull changes from Todoist (title update + completion)

- **Prompt**: Manually update a Todoist task title (via `mcp__<todoist_server>__update-tasks` changing "Sync push test A" to "Sync push test A UPDATED"), then complete "Sync push test B" (via `mcp__<todoist_server>__complete-tasks`). Then follow the skill instructions as if user said `/proj:sync`.
- **Expected**: Per SKILL.md:
  - Step 2: `proj_todoist_diff` with `auto_apply=true` detects and auto-applies pull_update and pull_complete locally.
  - Push counts are zero, so step 3 push operations are skipped.
  - Step 4: `proj_todoist_apply` is NOT called (or called only if link/cleanup needed).
  - Summary includes "Pulled from Todoist: ... updated, ... closed".
- **Assert**:
  - Call `mcp__proj__todo_list` -- todo A title is now "Sync push test A UPDATED".
  - Todo B status is `done`.

### Scenario 3: Ghost close -- local todo archived, Todoist task still open

- **Prompt**: Add a new todo "Ghost test", follow the skill instructions to sync it to Todoist (run `/proj:sync`), then archive the local todo via `mcp__proj__proj_archive` or `mcp__proj__todo_complete` + remove from active list. Then follow the skill instructions as if user said `/proj:sync` again.
- **Expected**: Per SKILL.md:
  - Step 2: `proj_todoist_diff` returns `ghost_close` containing the Todoist task ID for "Ghost test".
  - Step 3a: Calls `complete-tasks` with the ghost_close IDs.
  - Summary includes "Ghosts resolved: 1 Todoist tasks closed".
- **Assert**:
  - Call `mcp__<todoist_server>__find-tasks` with the project ID -- "Ghost test" no longer appears in open tasks.

### Scenario 4: Already in sync -- no changes

- **Prompt**: Follow the skill instructions as if user said `/proj:sync` immediately after a successful sync with no intervening changes.
- **Expected**: Per SKILL.md:
  - Step 2: `proj_todoist_diff` returns all-zero counts.
  - Output is "Todoist sync complete. Everything up to date." and stops.
  - No calls to `add-tasks`, `update-tasks`, `complete-tasks`, or `proj_todoist_apply`.
  - Step 6: `tracking_git_flush` is still called.
- **Assert**:
  - No state changes in local todos or Todoist tasks.

### Scenario 5: Todoist disabled -- early exit

- **Prompt**: Temporarily set `todoist.enabled=false` via `mcp__proj__config_update`, then follow the skill instructions as if user said `/proj:sync`.
- **Expected**: Per SKILL.md step 0, skill stops with message: "Todoist sync is not enabled. Set todoist.enabled: true in ~/.claude/proj.yaml to use /proj:sync."
- **Assert**:
  - Output contains the expected message.
  - No Todoist API calls are made.
  - Re-enable `todoist.enabled=true` after the test.

## Cleanup

1. Delete all Todoist tasks in the eval project: call `mcp__<todoist_server>__find-tasks` with the project ID, then `mcp__<todoist_server>__delete-object` for each task (type="task").
2. Delete the Todoist project: `mcp__<todoist_server>__delete-object` with type="project" and the eval project ID.
3. Archive the eval project: `mcp__proj__proj_archive` with project name "eval-test-sync".
4. Remove temp files: `rm -rf /tmp/claude-1000/eval-sync`.
