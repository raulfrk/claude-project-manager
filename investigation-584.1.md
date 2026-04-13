# Investigation: Todo 584.1 — Todoist Sync Duplicate Root Cause

## Confirmed Failure Points

### 1. `_call_todoist_tool` discards `_hooks` field (todoist_full_sync.py:1038-1049)

**Confirmed.** `_call_todoist_tool` unwraps the `{"ok": True, "result": ...}` envelope from the HTTP handler, then parses the inner JSON string. However, the hook dispatch wrapper (`_wrap_tool_fn` in `dispatch.py:557-577`) injects a `_hooks` field into the tool result *before* it reaches the HTTP handler envelope. When `_call_todoist_tool` parses the inner result, it returns the full dict — which *does* include `_hooks` if hooks fired. But crucially, **no caller of `_call_todoist_tool` inspects the `_hooks` field**. The `_hooks.errors` and `_hooks.structured_errors` are silently discarded.

**Impact**: If `todoist_add_tasks` partially fails (e.g., some tasks succeed, some fail), the hook error metadata is available in the response but never checked by `_execute_push_creates`.

### 2. `_execute_push_creates` ignores hook errors (todoist_full_sync.py:1090-1155)

**Confirmed.** At line 1091, the function calls `_call_todoist_tool("todoist_add_tasks", {"tasks": add_payloads})`. It then inspects the result for `successes` and `failures` fields (lines 1094-1098), but:

- It never checks for `_hooks` field in the result dict
- It never checks for `_hooks.errors` or `_hooks.structured_errors`
- When a created task has an empty `id` field (line 1108-1113), it falls through to the `_find_existing_todoist_task` dedup guard rather than checking if hook errors explain the missing ID
- When the response is shorter than expected (lines 1134-1155), same fallback to `_find_existing_todoist_task`

**Impact**: Hook failures (auth errors, timeouts, rate limits) during `todoist_add_tasks` are invisible to the full sync orchestrator.

### 3. `todoist-on-todo-add` hook has feedback_mapping but full sync bypasses it (default-hooks.yaml:15-17)

**Partially confirmed — the issue is different than speculated.** The `todoist-on-todo-add` hook in `plugins/todoist/.claude-plugin/default-hooks.yaml:15-17` *does* have a feedback_mapping:

```yaml
feedback_tool: todo_update
feedback_mapping:
  successes.0.id: todoist_task_id
```

This maps `successes.0.id` from the Todoist response back to `todoist_task_id` via `todo_update`. The feedback mechanism in `fire.py:486-534` resolves this path and calls `todo_update` to write back the ID.

**However**, the full sync (`proj_todoist_full_sync`) calls `todoist_add_tasks` *directly via UDS* (`_call_todoist_tool`), NOT through the hook dispatch system. This means:

- The `todoist-on-todo-add` hook feedback path is never triggered during full sync
- Full sync has its own ID writeback: `link_ops` built at lines 1895-1900, applied via `apply_changes` at line 1922
- The two writeback paths are completely independent

**The actual gap**: When `todoist_add_tasks` returns a task with an empty `id` (e.g., Todoist API returns 200 but the task object lacks an `id` field — a known edge case with Todoist's batch endpoint), the full sync's writeback path silently skips it (line 1108: `if todoist_id:` is falsy for empty string). The todo gets no `todoist_task_id` linked. On the next sync, `_build_sync_plan` sees the todo as unlinked and adds it to `push_create` again → **duplicate**.

### 4. `_find_existing_todoist_task` fallback may fail with missing project context (todoist_full_sync.py:1391-1436)

**Confirmed.** The dedup guard at lines 1116-1120 and 1138-1142 calls `_find_existing_todoist_task` with project_id derived from:

```python
str(task.get("project_id", "") or "") or (project_todoist_id or "")
```

**Failure scenarios:**
- `project_todoist_id` is `None` (passed as second arg to `_execute_push_creates` at line 1838) when the project has no `todoist_project_id` in metadata — the function receives `None` and the fallback chain evaluates to `""`, causing the guard at line 1405 (`if not project_id`) to return `None` immediately
- Even when project_id is present, `_find_existing_todoist_task` uses `todoist_find_tasks` which returns all tasks in the project. Content matching (line 1419) is exact-string — if Todoist normalizes whitespace or encoding differently, the match fails
- When `parent_id` filtering is active (line 1422-1424), a task created without its parent relationship (common in partial-failure batch creates) won't match

**Impact**: The dedup guard — the last line of defense — fails silently when project context is missing, returning `None` and allowing the error path at line 1126-1133 to mark the task as retryable. The retry at `_retry_failed_ops` (line 1458) calls `_find_existing_todoist_task` again with the same broken context → same failure → task re-created as duplicate.

## Reproduction Path

1. User runs `/proj:todoist-sync` (or auto-sync triggers on `proj_load_session`)
2. `proj_todoist_full_sync` tool fires, entering the full sync flow
3. `_build_sync_plan` identifies unlinked local todos → adds them to `plan.push_create`
4. `_execute_push_creates` calls `todoist_add_tasks` via UDS to Todoist plugin
5. **Failure trigger**: Todoist API returns 200 but one task in the batch has an empty/missing `id` field (intermittent Todoist API issue), OR the Todoist plugin raises an exception that's caught at line 1156
6. For empty-id case: `todoist_id` at line 1108 is empty string → `if todoist_id:` is False → falls through to `_find_existing_todoist_task`
7. `_find_existing_todoist_task` receives `project_todoist_id=None` (line 1838 passes `None` when `_execute_push_creates` was called with `project_todoist_id` as second positional arg, but at line 1836-1838 it actually passes `project_todoist_id` which is set at line ~1790) — OR the content match fails due to whitespace normalization differences
8. Dedup guard returns `None` → error entry created with `retryable: True`
9. Todo never gets `todoist_task_id` linked (no entry in `link_ops` at line 1895-1900 because `result_todoist_id` was never set)
10. `apply_changes` runs without linking this todo
11. **Next sync**: `_build_sync_plan` sees the todo as unlinked (no `todoist_task_id`) → adds to `push_create` again
12. Todoist API creates a second task with the same content → **duplicate**

For the **exception case** (line 1156-1167): all tasks in the batch are marked as errors with `retryable: True`, but `_retry_failed_ops` (if invoked) only retries with dedup guard → same failure path.

## Recommended Fix Points

### Fix 1: Pass `project_todoist_id` to `_execute_push_creates` (todoist_full_sync.py:1836-1838)

**Already done** — `project_todoist_id` is passed as the second argument. But `_execute_push_creates` only uses it as a fallback in the dedup guard (lines 1117, 1139). The real issue is that the dedup guard's fallback chain silently degrades to `""` when both `task.get("project_id")` and `project_todoist_id` are missing.

**Fix**: Add explicit validation at the top of `_execute_push_creates` — if `project_todoist_id` is None, log a warning. Also propagate `project_todoist_id` into each task payload's `project_id` field before the batch call (some tasks may not have it set if meta was missing).

### Fix 2: Check `_hooks.errors` after `_call_todoist_tool` (todoist_full_sync.py:1091)

**Fix**: After calling `_call_todoist_tool`, check if `result` is a dict with a `_hooks` key. If `_hooks.structured_errors` is non-empty, log the errors and include them in the error response. This makes hook failures visible to the full sync orchestrator.

### Fix 3: Make `_find_existing_todoist_task` more resilient (todoist_full_sync.py:1391-1436)

**Fixes**:
- Fuzzy content matching: normalize whitespace before comparison (line 1419)
- When `parent_id` match fails, retry without `parent_id` constraint as a fallback
- Add logging when `project_id` is empty so the silent degradation becomes visible

### Fix 4: Persist partial successes atomically (todoist_full_sync.py:1895-1922)

**Fix**: Currently, `link_ops` is built from `p1_succeeded + p2_succeeded` at lines 1895-1900, then applied via `apply_changes` at line 1922. If some tasks in the batch succeeded (got IDs) but others failed, the successful linkages are correctly persisted. The gap is that if `apply_changes` itself fails (e.g., concurrent write to todos.yaml), ALL linkages are lost — including successful ones. Wrap the apply call in a retry or persist link_ops to a recovery file before attempting apply.

### Fix 5: Add idempotency key to push_create payloads (todoist_full_sync.py:623-638)

**Fix**: Include the local `todo_id` as a label or description prefix in the Todoist task payload. This gives `_find_existing_todoist_task` a more reliable dedup signal than content matching alone.
