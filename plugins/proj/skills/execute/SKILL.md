---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
allowed-tools: mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, mcp__proj__tracking_git_flush, mcp__proj__proj_session_context, Task, Skill, EnterPlanMode, ExitPlanMode
argument-hint: "[todo-id | range] [--no-verify] e.g. 1 or 2-4"
---

Execute todo(s): $ARGUMENTS

**Determine scope from $ARGUMENTS:**
- Parse `--no-verify` flag from $ARGUMENTS if present (strip it before interpreting the rest).
  When set, skip the verification step (4a) entirely.
- Empty → call `mcp__proj__todo_list` with `status="in_progress"` to find any in-progress todo;
  if none, call `mcp__proj__todo_list` with `status="ready"`. Display the results and proceed
  with the first (or ask the user if multiple).
- Single ID (e.g. `1`) → execute that todo
- Range (e.g. `2-4`) → execute those todos

**For a single todo:**

**1.** Call `mcp__proj__todo_check_executable` with the todo ID.
   - If the result starts with "⚠️", display it as-is and **stop** — do not implement.
   - If the result is JSON, continue normally.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
   This returns the todo, its requirements, its research, and (if present) the parent todo in one call.
**3.** Call `EnterPlanMode`. Read all loaded context (requirements.md, research.md, notes) and explore the relevant source files. Create an implementation plan covering:
   - Files to modify/create
   - Key changes per file
   - Implementation order
   - Testing approach

   Call `ExitPlanMode` to present the plan for user review. The user will approve or request changes before you proceed.
**4.** Before implementing: call `mcp__proj__todo_update` with `status="in_progress"` to mark the todo as in_progress. Then review all context and implement the task. If the todo has a non-empty `notes` field, treat it as additional implementation context (e.g. constraints or design decisions) — it should inform your implementation approach.
**4a.** **Verification** (skip entirely if `--no-verify` was passed in $ARGUMENTS):

   Run three check categories, then report results. If a check's prerequisites are missing, skip it gracefully with a note — never fail the whole step.

   **A. Automated checks (Bash)**
   Detect and run test/lint tooling in the project's content directory:
   - **Tests**: if `pyproject.toml` exists with a `[tool.pytest]` section → `uv run pytest --tb=short -q`; elif `package.json` exists with a non-empty `"test"` field in `"scripts"` → `npm test`; else skip with "No test runner detected".
   - **Lint** (ruff for Python, eslint for JS): if `pyproject.toml` with a `[tool.ruff]` section → `uv run ruff check` on modified files; elif `.eslintrc*` exists → `npx eslint` on modified files; else skip.
   Record: pass/fail, summary (e.g. "14 tests passed", "2 tests failed: test_x, test_y").

   **B. Spec validation**
   1. Call `mcp__proj__content_get_requirements` with the todo ID.
      - If no requirements exist → skip with "No requirements.md found".
   2. Extract acceptance criteria (lines matching `- [ ]` or `- [x]` pattern).
   3. Run `git diff HEAD~1` via Bash to get the implementation diff.
   4. For each criterion, assess whether the diff addresses it. Categorize as: **met**, **unmet**, or **unverifiable** (criterion is subjective or requires runtime testing).

   **C. Diff review**
   1. From the approved plan (step 3), extract the "Files to modify/create" list.
      - If no plan is available (e.g. `--no-interactive` was used) → skip with "No plan available for diff review".
   2. Run `git diff --name-only HEAD~1` via Bash to get actually modified files.
   3. Compare:
      - Files in plan but not in diff → "planned but not touched"
      - Files in diff but not in plan → "unplanned modification"
      - Files in both → "matches plan"

   **Report** — Display results in this format:
   ```
   ### Verification Report — Todo <id>

   **Automated checks**: PASS (14 tests passed) | FAIL (2 tests failed: test_x, test_y)
   **Spec validation**: 4/4 criteria met | 3/4 criteria met (1 unverifiable)
   **Diff review**: Plan matches | 1 planned file not touched, 1 unplanned file modified
   ```

   **Persist** — Write the report (with timestamp) to `todos/<id>/verification-report.md` in the tracking dir using `mcp__proj__notes_append` or direct file write. Overwrite any previous report for this todo.

   **Prompt** — After displaying the report, ask:
   > Fix these issues? (1) Fix (2) Proceed (3) Skip
   - **Fix**: spawn a `general-purpose` Task agent with: (1) the verification report, (2) todo details + requirements.md + research.md + parent context (via `proj_get_todo_context`), (3) the approved implementation plan from step 3, and (4) instructions to fix the failures. After the agent completes, re-run verification on this todo (max 2 retries total). If still failing after retries, display the updated report and re-prompt.
   - **Proceed**: continue to the satisfaction loop (step 5) despite failures.
   - **Skip**: skip remaining verification for this session and go directly to step 5.

   If all checks pass, display the report and proceed to step 5 without prompting.

**5.** On completion — **Satisfaction loop**:
   a. Ask: "Are you satisfied with the outcome of todo <id>?"
      1. **Satisfied** — proceed to step 5d
      2. **Not satisfied** — describe what needs fixing
      3. **Redefine** — refine requirements and re-run workflow
   b. If not satisfied:
      - Ask what's missing, fix issues in current scope
      - Re-ask satisfaction (go back to step 5a)
   c. If redefine:
      - Invoke `/proj:define <id>` via Skill tool (existing requirements/research kept as context — non-destructive)
      - After define completes, check if todo has/needs children:
        - If decomposable: invoke `/proj:decompose <id>` via Skill tool
      - Invoke `/proj:execute <id>` via Skill tool
      - Re-ask satisfaction on original todo (go back to step 5a)
   d. Call `mcp__proj__todo_complete`
      - Update CLAUDE.md if relevant: `mcp__proj__claudemd_write`
      - Append a brief progress note: `mcp__proj__notes_append`

**For a range with independent todos (no blocked_by between them):**

Phase 1 — Plan (sequential, in main conversation):
For each todo in the range:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `EnterPlanMode`. Create an implementation plan for this todo covering files to modify/create, key changes, implementation order, and testing approach.
**4.** Call `ExitPlanMode` for user review. The user will approve or request changes before moving to the next todo.

Phase 2 — Execute (parallel Task agents):
After all plans are approved, spawn one `general-purpose` Task agent per todo (excluding manual-skipped ones).
Each agent receives: the todo details, its requirements.md, its research.md, parent context, AND the approved implementation plan.
Each agent implements according to its approved plan. Agents do NOT call `todo_complete`.

Phase 2a — Verification (skip entirely if `--no-verify` was passed in $ARGUMENTS):
After all agents complete, verify each completed todo sequentially in the main conversation. For each todo, run the verification checks from step **4a.** (Automated checks, Spec validation, Diff review). Collect all results, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist each todo's individual report to `todos/<id>/verification-report.md` in the tracking dir.

After the combined report, show a summary line (e.g. "2 passed, 1 failed") and prompt:
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with the verification report + implementation context + instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). If still failing after retries, display the updated report and re-prompt.
- **Proceed**: continue to Phase 3 despite failures.
- **Skip**: skip remaining verification for this session and go directly to Phase 3.

If all checks pass, display the combined report and proceed to Phase 3 without prompting.

Phase 3 — Satisfaction check (sequential, main conversation):
For each completed agent todo (excluding manual-skipped):
**1.** Review the agent's output
**2.** Run the satisfaction loop (same as step **5a.**–**5d.** above)
Main conversation reports summary, including any skipped manual todos.

**For a range with dependencies:**

Phase 1 — Plan (sequential, in dependency order):
Execute in topological order (respect blocked_by chains). For each todo:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `EnterPlanMode`. Create an implementation plan for this todo.
**4.** Call `ExitPlanMode` for user review.

Phase 2 — Execute (sequential, in dependency order):
Execute each todo according to its approved plan, one at a time (respecting blocked_by chains). Each todo: mark in_progress, implement per plan.

Phase 2a — Verification (skip entirely if `--no-verify` was passed in $ARGUMENTS):
After all todos are implemented, verify each completed todo sequentially. For each todo, run the verification checks from step **4a.** (Automated checks, Spec validation, Diff review). Collect all results, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist each todo's individual report to `todos/<id>/verification-report.md` in the tracking dir.

After the combined report, show a summary line (e.g. "2 passed, 1 failed") and prompt:
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with the verification report + implementation context + instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). If still failing after retries, display the updated report and re-prompt.
- **Proceed**: continue to Phase 3 despite failures.
- **Skip**: skip remaining verification for this session and go directly to Phase 3.

If all checks pass, display the combined report and proceed to Phase 3 without prompting.

Phase 3 — Satisfaction check (sequential, in dependency order):
For each completed todo, run the satisfaction loop (step 5a-5d) before calling `todo_complete`.

**Note:** Root todo execution does NOT auto-recurse into children. To execute children, specify their IDs explicitly.

**6.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Execute: {todo-id}"`.

Suggested next: (1) /proj:save — save session and reconcile git  (2) /proj:status — see updated project overview
