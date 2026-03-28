---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
allowed-tools: mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, mcp__proj__tracking_git_flush, mcp__proj__proj_session_context, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, mcp__proj__config_load, Task, TaskCreate, TaskList, Skill, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage
argument-hint: "[todo-id | range] [--no-verify] [--team] [--no-team] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--fast|--balanced|--careful|--paranoid] [--force-plan] [--batch-approve] e.g. 1 or 2-4"
---

Execute todo(s): $ARGUMENTS

**Determine scope from $ARGUMENTS:**
- Parse `--no-verify` flag from $ARGUMENTS if present (strip it before interpreting the rest).
  When set, skip the verification step (4a) entirely.
- Parse `--team` flag: force team mode ON for this execution (overrides config).
- Parse `--no-team` flag: force team mode OFF for this execution (overrides config).
- Parse `--full-context` flag: when using team mode, include CLAUDE.md and NOTES.md in each agent's context.
- Parse `--trust N` flag (N = 0-3). If not specified, call `mcp__proj__config_load` and use `team_mode.trust_level` (default 1 if unset). Determines the approval workflow:
  - **Trust 0 (supervised)**: per-todo approval — each plan presented individually, user approves one at a time before the next plan is created.
  - **Trust 1 (guided)**: bulk approval + parallel execution — all plans presented sequentially, user approves each, then bulk confirmation before execution. This is the default for Pattern A.
  - **Trust 2 (autonomous)**: auto-approve plans — plans are created but `ExitPlanMode` user review is skipped. Plans are automatically stored in `approved_plans` and execution proceeds without user confirmation.
  - **Trust 3 (full-auto)**: no plan phase — Phase 1 is skipped entirely. Agents execute with context only (requirements + research + parent context). No plans are created.
- Parse `--resume` flag: resume execution from the most recent checkpoint. See **Resume checkpoint** below.
- Parse `--no-pipeline` flag: disable plan-while-executing pipeline (default: pipeline enabled).
- Parse `--fast`/`--balanced`/`--careful`/`--paranoid` flags. Mutually exclusive, last wins, default `--balanced`.
- Parse `--force-plan` flag: force FULL REVIEW regardless of complexity score.
- Parse `--batch-approve` flag: auto-approve all speculative plans without review.

Derive: `quality_level` from flags (fast/balanced/careful/paranoid).

**Quality Level Parameter Mapping:**

| Parameter | --fast | --balanced | --careful | --paranoid |
|-----------|--------|-----------|-----------|-----------|
| gate_override | auto-execute (tag-immune) | smart-gate | full-review | full-review |
| batch_approve | auto | smart-gate | disabled | disabled |
| speculative_planning | enabled | enabled | disabled | disabled |
| verification_mode | skip | standard | enhanced | full |
| max_parallel | 20 | 6 | 3 | 1 |
| satisfaction | skip (auto-complete) | per-batch | per-todo | per-todo + re-verify |
| pattern_detection | auto-approve | enabled | disabled | disabled |

Derive: `pipeline_enabled = not no_pipeline_flag`

**Flag compatibility check** (validate before proceeding):
- `--fast --force-plan` → ERROR: "Cannot combine --fast with --force-plan."
- `--careful --batch-approve` → careful wins, batch approve disabled (warn).
- `--paranoid --batch-approve` → paranoid wins, batch approve disabled (warn).
- `--force-plan --batch-approve` → ERROR: "Cannot combine --force-plan with --batch-approve."
- `--no-verify --paranoid` → ERROR: "Cannot combine --no-verify with --paranoid."
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification is skipped.
- `--fast --steps refine` → ERROR (execute doesn't have refine, but document for consistency).
- `--batch-approve --no-pipeline` → Allowed.
- `--paranoid --no-pipeline` → Redundant warning.
- `--careful --no-pipeline` → Allowed.
- `--fast --no-pipeline` → Redundant warning.
- `--force-plan --careful` → Redundant warning.
- `--force-plan --paranoid` → Redundant warning.
- `--no-verify --balanced` → --no-verify wins.
- `--no-verify --fast` → Redundant.
- `--force-plan --trust 3` → ERROR: "Cannot combine --force-plan with --trust 3."
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
**3.** Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
**3a.** **Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

   **File-impact estimation** (for dimensions 1-2 when no speculative plan exists):
   Spawn a lightweight read-only Task agent with: todo context, requirements, research. Tools: Read, Glob, Grep only.
   Agent estimates: which files will be modified/created, which directories are involved.
   Wait for agent. Use results to score dimensions 1 (file count) and 2 (directory spread).
   If agent fails: score dimensions 1-2 as 0 (assume simple).

   Compute complexity score (0-14) from 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

   Evaluation order: Tag overrides FIRST → complexity score → critical-path file guard as FINAL FLOOR.

   **Tag overrides** (checked before score): `auto-execute` tag → force AUTO-EXECUTE. `security`, `breaking-change`, `migration`, `needs-review` tags → force FULL REVIEW regardless of score. This applies even in `--fast` mode (tag immunity). Most restrictive wins when multiple tags apply.

   **Critical-path file guard** (FINAL FLOOR): If any planned file matches a critical path pattern (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW, even if score is 0-3.

   Gate routing:
   - **AUTO-EXECUTE (0-3)**: Create git tag `pre-auto-execute-{todo_id}`. Skip plan, execute with context.
   - **LIGHT REVIEW (4-7)**: 1-line summary + `Proceed? [Y/n]` (default yes).
   - **FULL REVIEW (8-14)**: Full EnterPlanMode/ExitPlanMode.

   If `--force-plan`: always route to FULL REVIEW.

**3b.** **Plan creation** (respects trust level, skipped if gate routed to AUTO-EXECUTE):
   - **Trust 0-2**: Call `EnterPlanMode`. Read all loaded context (requirements.md, research.md, notes, and any Related Context from step 3) and explore the relevant source files. Create an implementation plan covering:
     - Files to modify/create
     - Key changes per file
     - Implementation order
     - Testing approach
   - **Trust 0-1**: Call `ExitPlanMode` to present the plan for user review. The user will approve or request changes before you proceed.
   - **Trust 2**: Skip `ExitPlanMode` user review. The plan is automatically approved and stored. Display a brief summary: `Plan auto-approved (trust 2): <1-line summary>`.
   - **Trust 3**: Skip step 3b entirely — no plan is created. Proceed directly to step 4 with context only.
**4.** Before implementing: call `mcp__proj__todo_update` with `status="in_progress"` to mark the todo as in_progress. Then review all context and implement the task. If the todo has a non-empty `notes` field, treat it as additional implementation context (e.g. constraints or design decisions) — it should inform your implementation approach.
**4a.** **Verification** (skip entirely if `--no-verify` was passed in $ARGUMENTS):

   Verification mode (determined by quality_level):
   - `skip` (--fast): Skip verification entirely.
   - `standard` (--balanced): Current behavior (automated checks + spec validation + diff review).
   - `enhanced` (--careful): Standard + generate manual test checklist from acceptance criteria.
   - `full` (--paranoid): Enhanced + spawn an independent review agent that reads the implementation diff, requirements.md, and the approved plan. Agent produces an assessment with a risk rating (LOW/MEDIUM/HIGH). If risk is HIGH, flag for user attention before satisfaction prompt.

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
   1. From the approved plan (step 3b), extract the "Files to modify/create" list.
      - If no plan is available (e.g. `--no-interactive` was used, or AUTO-EXECUTE gate) → skip with "No plan available for diff review".
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

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine execution mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 3+ independent (non-manual) todos in the batch: use **Pattern A (Team-based execution)** below.
- Otherwise: use **Pattern B (Task agent execution)** below.

---

**Pattern A — Team-based execution (independent todos):**

**Phase C0 — Speculative planning** (if quality_level != careful/paranoid AND trust != 0 AND trust != 3):

For each todo in the current batch, spawn a read-only Task agent:
- Tools: Read, Glob, Grep, proj_get_todo_context, proj_explore_codebase, content_get_requirements, content_get_research (NO write tools)
- Output: structured JSON plan `{prose: string, actions: [{type: "create"|"modify"|"delete"|"test", file: string}]}`

If agent fails: exclude todo, fall back to sequential planning for that todo.
Store in `speculative_plans[todo_id]`.

If `--batch-approve`: auto-approve all speculative plans without review. Display: `Batch-approved N speculative plans.`

**Phase 1 — Plan (sequential, main conversation):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

Initialize `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in the range:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
**3a.** **Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

   Compute complexity score (0-14) from 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

   Evaluation order: Tag overrides FIRST → complexity score → critical-path file guard as FINAL FLOOR.

   **Tag overrides** (checked before score): `auto-execute` tag → force AUTO-EXECUTE. `security`, `breaking-change`, `migration`, `needs-review` tags → force FULL REVIEW regardless of score. This applies even in `--fast` mode (tag immunity). Most restrictive wins when multiple tags apply.

   **Critical-path file guard** (FINAL FLOOR): If any planned file matches a critical path pattern (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW, even if score is 0-3.

   Gate routing:
   - **AUTO-EXECUTE (0-3)**: Create git tag `pre-auto-execute-{todo_id}`. Skip plan, execute with context.
   - **LIGHT REVIEW (4-7)**: 1-line summary + `Proceed? [Y/n]` (default yes).
   - **FULL REVIEW (8-14)**: Full EnterPlanMode/ExitPlanMode.

   If `--force-plan`: always route to FULL REVIEW.

**3b.** Call `EnterPlanMode`. Create an implementation plan for this todo covering files to modify/create, key changes, implementation order, and testing approach. Include any Related Context from step 3. (Skipped if gate routed to AUTO-EXECUTE.)
**4.** Plan approval (respects trust level):
   - **Trust 0**: Call `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: Call `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
**5.** Store the approved plan in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel`, wait for at least one executing agent to complete.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

After all plans are stored (trust 0-1): present a bulk approval summary showing all todo IDs and their plan summaries.

**Cross-review** (if quality_level == paranoid AND N > 1):
After all plans are generated, each plan is cross-reviewed by an independent read-only agent.
Agent i reviews plan (i+1) % N. For N=1, cross-review is skipped.
Each cross-review agent receives: the plan to review + that todo's requirements + the reviewer's own todo context for perspective.
Cross-review output: risk rating (LOW/MEDIUM/HIGH) + concerns list.
If any HIGH risk: flag for user attention before proceeding to execution.

**File-Overlap Detection** (before Phase 2, skip if trust 3):
1. For each approved plan in `approved_plans`, extract the "Files to modify/create" list from the plan text.
2. Build an overlap matrix: for each pair of plans, check if their file lists intersect.
3. If overlaps are found, display:

```
### File Overlap Warning

| File | Touched by |
|------|-----------|
| models.py | todo 1, todo 3 |
| config.py | todo 1, todo 3 |

Options:
1. **Serialize** — Move conflicting todos to a separate sequential batch (executed one at a time after parallel batch completes, using the same team)
2. **Proceed** — Execute in parallel anyway (risk of conflicts)
3. **Cancel** — Stop execution
```

4. If user selects **Serialize**: remove conflicting todos from their parallel batch, add them to a new sequential batch at the end.
5. If user selects **Proceed**: continue as-is.
6. If user selects **Cancel**: stop, display "Execution cancelled. Plans are saved."
7. If no overlaps detected: skip silently.

**Resume checkpoint** (applies when `--resume` is passed):
1. Look for the most recent checkpoint file in `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. If found and not stale (created within the last 24 hours):
   - Read the checkpoint. Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
   - Use the stored `approved_plans` from the checkpoint.
   - Skip to the `batch_index` in Phase 2 (all prior batches are treated as complete).
3. If the checkpoint is stale (older than 24 hours) or references todos that no longer exist:
   - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
   - If Restart: ignore checkpoint and start from Phase 1.
   - If Use anyway: proceed with the stale checkpoint data.
4. If no checkpoint found: display `No checkpoint found — starting fresh` and proceed normally.

**Phase 2 — Execute (parallel with Team):**

Enforce max_parallel from quality_level parameter mapping. Do not spawn more agents than max_parallel allows.

**1.** `TeamCreate(name="execute-{project}-{timestamp}", description="Executing todos {id1}, {id2}, ...")`
**1a. Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo in the current batch:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the same batch, use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop in Phase 3 handles proj todo completion.

**2.** For the single batch of independent todos:
   IF `pipeline_enabled`:
       Wait for all `executing_agents` in this batch to complete. Report any failures.
       -- batch failure short-circuit --
       IF all agents in this batch failed: display "All N agents in batch failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
   ELSE:
   - Display: `Executing batch: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo with `team_name`. Each agent receives: the approved plan (or context only if trust 3) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content.
   - IF todo was part of a pattern group: Include in the agent prompt: "This todo is part of a pattern group (N similar todos). The common pattern is: <normalized pattern>. Implement consistently with the group."
   - Agents execute the approved plan as-is. They do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for batch completion. Report any failures.
   - **Write checkpoint** after batch completion to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: execute-{project}-{timestamp}
     batch_index: 1
     total_batches: 1
     completed_todos: [<completed todo IDs>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
**3.** After all agents complete: `TeamDelete(team_name)`
**4.** If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**Phase 2a — Verification** (skip entirely if `--no-verify` was passed in $ARGUMENTS):
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

**Phase 3 — Satisfaction check (sequential, main conversation):**
For each completed todo (excluding manual-skipped and failed):
**1.** Review the agent's output
**2.** Run the satisfaction loop (same as step **5a.**–**5d.** above)
Clear `executing_agents = {}` after satisfaction checks complete.
Main conversation reports summary, including any skipped manual todos and any failed agent todos.

---

**Pattern B — Task agent execution (independent todos, fallback):**

Phase 1 — Plan (sequential, in main conversation):

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

Initialize `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in the range:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
**3a.** **Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

   Compute complexity score (0-14) from 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

   Evaluation order: Tag overrides FIRST → complexity score → critical-path file guard as FINAL FLOOR.

   **Tag overrides** (checked before score): `auto-execute` tag → force AUTO-EXECUTE. `security`, `breaking-change`, `migration`, `needs-review` tags → force FULL REVIEW regardless of score. This applies even in `--fast` mode (tag immunity). Most restrictive wins when multiple tags apply.

   **Critical-path file guard** (FINAL FLOOR): If any planned file matches a critical path pattern (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW, even if score is 0-3.

   Gate routing:
   - **AUTO-EXECUTE (0-3)**: Create git tag `pre-auto-execute-{todo_id}`. Skip plan, execute with context.
   - **LIGHT REVIEW (4-7)**: 1-line summary + `Proceed? [Y/n]` (default yes).
   - **FULL REVIEW (8-14)**: Full EnterPlanMode/ExitPlanMode.

   If `--force-plan`: always route to FULL REVIEW.

**3b.** Call `EnterPlanMode`. Create an implementation plan for this todo covering files to modify/create, key changes, implementation order, and testing approach. Include any Related Context from step 3. (Skipped if gate routed to AUTO-EXECUTE.)
**4.** Plan approval (respects trust level):
   - **Trust 0**: Call `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: Call `ExitPlanMode` for user review. User approves this plan, then move to the next todo.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
**5.** Store the approved plan in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel`, wait for at least one executing agent to complete.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**Cross-review** (if quality_level == paranoid AND N > 1):
After all plans are generated, each plan is cross-reviewed by an independent read-only agent.
Agent i reviews plan (i+1) % N. For N=1, cross-review is skipped.
Each cross-review agent receives: the plan to review + that todo's requirements + the reviewer's own todo context for perspective.
Cross-review output: risk rating (LOW/MEDIUM/HIGH) + concerns list.
If any HIGH risk: flag for user attention before proceeding to execution.

Phase 2 — Execute (parallel Task agents):

Enforce max_parallel from quality_level parameter mapping. Do not spawn more agents than max_parallel allows.

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents in batch failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:
After all plans are approved (or skipped for trust 3), spawn one `general-purpose` Task agent per todo (excluding manual-skipped ones).
Each agent receives: the todo details, its requirements.md, its research.md, parent context, AND the approved implementation plan (or context only if trust 3).
IF todo was part of a pattern group: Include in the agent prompt: "This todo is part of a pattern group (N similar todos). The common pattern is: <normalized pattern>. Implement consistently with the group."
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
Clear `executing_agents = {}` after satisfaction checks complete.
Main conversation reports summary, including any skipped manual todos.

**For a range with dependencies:**

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine execution mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 3+ total (non-manual) todos in the range: use **Pattern A (Team-based execution with dependencies)** below.
- Otherwise: use **Pattern B (Sequential execution with dependencies)** below.

---

**Pattern A — Team-based execution (with dependencies):**

**Phase C0 — Speculative planning** (if quality_level != careful/paranoid AND trust != 0 AND trust != 3):

For each todo in the current batch, spawn a read-only Task agent:
- Tools: Read, Glob, Grep, proj_get_todo_context, proj_explore_codebase, content_get_requirements, content_get_research (NO write tools)
- Output: structured JSON plan `{prose: string, actions: [{type: "create"|"modify"|"delete"|"test", file: string}]}`

If agent fails: exclude todo, fall back to sequential planning for that todo.
Store in `speculative_plans[todo_id]`.

If `--batch-approve`: auto-approve all speculative plans without review. Display: `Batch-approved N speculative plans.`

**Phase 1 — Plan (sequential, in dependency order):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

Initialize `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

Group todos into dependency batches (topological order). Todos within the same batch have no blocked_by relationships between them and can run in parallel. Batches themselves execute sequentially. For each todo across all batches:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
**3a.** **Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

   Compute complexity score (0-14) from 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

   Evaluation order: Tag overrides FIRST → complexity score → critical-path file guard as FINAL FLOOR.

   **Tag overrides** (checked before score): `auto-execute` tag → force AUTO-EXECUTE. `security`, `breaking-change`, `migration`, `needs-review` tags → force FULL REVIEW regardless of score. This applies even in `--fast` mode (tag immunity). Most restrictive wins when multiple tags apply.

   **Critical-path file guard** (FINAL FLOOR): If any planned file matches a critical path pattern (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW, even if score is 0-3.

   Gate routing:
   - **AUTO-EXECUTE (0-3)**: Create git tag `pre-auto-execute-{todo_id}`. Skip plan, execute with context.
   - **LIGHT REVIEW (4-7)**: 1-line summary + `Proceed? [Y/n]` (default yes).
   - **FULL REVIEW (8-14)**: Full EnterPlanMode/ExitPlanMode.

   If `--force-plan`: always route to FULL REVIEW.

**3b.** Call `EnterPlanMode`. Create an implementation plan for this todo. Include any Related Context from step 3. (Skipped if gate routed to AUTO-EXECUTE.)
**4.** Plan approval (respects trust level):
   - **Trust 0**: Call `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: Call `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
**5.** Store the approved plan in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel`, wait for at least one executing agent to complete.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

After all plans are stored (trust 0-1): present a bulk approval summary showing all todo IDs, their batch assignments, and plan summaries.

**Cross-review** (if quality_level == paranoid AND N > 1):
After all plans are generated, each plan is cross-reviewed by an independent read-only agent.
Agent i reviews plan (i+1) % N. For N=1, cross-review is skipped.
Each cross-review agent receives: the plan to review + that todo's requirements + the reviewer's own todo context for perspective.
Cross-review output: risk rating (LOW/MEDIUM/HIGH) + concerns list.
If any HIGH risk: flag for user attention before proceeding to execution.

**File-Overlap Detection** (before Phase 2, skip if trust 3):
1. For each approved plan in `approved_plans`, extract the "Files to modify/create" list from the plan text. For dependency-batched execution, check overlaps **within each batch** (across-batch overlaps are acceptable since batches run sequentially).
2. Build an overlap matrix: for each pair of plans within the same batch, check if their file lists intersect.
3. If overlaps are found, display:

```
### File Overlap Warning

| File | Touched by | Batch |
|------|-----------|-------|
| models.py | todo 1, todo 3 | 1 |
| config.py | todo 1, todo 3 | 1 |

Options:
1. **Serialize** — Move conflicting todos to a separate sequential batch (executed one at a time after parallel batch completes, using the same team)
2. **Proceed** — Execute in parallel anyway (risk of conflicts)
3. **Cancel** — Stop execution
```

4. If user selects **Serialize**: remove conflicting todos from their parallel batch, add them to a new sequential batch at the end.
5. If user selects **Proceed**: continue as-is.
6. If user selects **Cancel**: stop, display "Execution cancelled. Plans are saved."
7. If no overlaps detected: skip silently.

**Resume checkpoint** (applies when `--resume` is passed):
1. Look for the most recent checkpoint file in `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. If found and not stale (created within the last 24 hours):
   - Read the checkpoint. Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
   - Use the stored `approved_plans` from the checkpoint.
   - Skip to the `batch_index` in Phase 2 (all prior batches are treated as complete).
3. If the checkpoint is stale (older than 24 hours) or references todos that no longer exist:
   - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
   - If Restart: ignore checkpoint and start from Phase 1.
   - If Use anyway: proceed with the stale checkpoint data.
4. If no checkpoint found: display `No checkpoint found — starting fresh` and proceed normally.

**Phase 2 — Execute (batches sequential, within-batch parallel with Team):**

Enforce max_parallel from quality_level parameter mapping. Do not spawn more agents than max_parallel allows.

**1.** `TeamCreate(name="execute-{project}-{timestamp}", description="Executing todos {id1}, {id2}, ... in {N} batches")`
**1a. Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo across all batches:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the range (same or different batch), use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop in Phase 3 handles proj todo completion.

**2.** For each batch in dependency order:
   IF `pipeline_enabled`:
       Wait for all `executing_agents` in this batch to complete. Report any failures.
       -- batch failure short-circuit --
       IF all agents in this batch failed: display "All N agents in batch failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
   ELSE:
   - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo in this batch with `team_name`. Each agent receives: the approved plan (or context only if trust 3) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content.
   - IF todo was part of a pattern group: Include in the agent prompt: "This todo is part of a pattern group (N similar todos). The common pattern is: <normalized pattern>. Implement consistently with the group."
   - Agents execute the approved plan as-is. They do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report any failures.
   - **Write checkpoint** after each batch to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: execute-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
**3.** After all batches complete: `TeamDelete(team_name)`
**4.** If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**Phase 2a — Verification** (skip entirely if `--no-verify` was passed in $ARGUMENTS):
After all batches complete, verify each completed todo sequentially. For each todo, run the verification checks from step **4a.** (Automated checks, Spec validation, Diff review). Collect all results, then display a combined batch report:

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

**Phase 3 — Satisfaction check (sequential, main conversation):**
For each completed todo (excluding manual-skipped and failed), run the satisfaction loop (step 5a-5d) before calling `todo_complete`.
Clear `executing_agents = {}` after satisfaction checks complete.
Main conversation reports summary, including any skipped manual todos and any failed agent todos.

---

**Pattern B — Sequential execution (with dependencies, fallback):**

Phase 1 — Plan (sequential, in dependency order):

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

Initialize `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

Execute in topological order (respect blocked_by chains). For each todo:
**1.** Call `mcp__proj__todo_check_executable` — if the result starts with "⚠️", skip with `⚠️ Todo <id> [manual] — skipped execute` and move to the next todo.
**2.** Call `mcp__proj__proj_get_todo_context` with `todo_id=<id>` and `include_parent=true`.
**3.** Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
**3a.** **Smart gate scoring** (skip if quality_level == fast with auto-execute, or if --force-plan):

   Compute complexity score (0-14) from 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

   Evaluation order: Tag overrides FIRST → complexity score → critical-path file guard as FINAL FLOOR.

   **Tag overrides** (checked before score): `auto-execute` tag → force AUTO-EXECUTE. `security`, `breaking-change`, `migration`, `needs-review` tags → force FULL REVIEW regardless of score. This applies even in `--fast` mode (tag immunity). Most restrictive wins when multiple tags apply.

   **Critical-path file guard** (FINAL FLOOR): If any planned file matches a critical path pattern (e.g., `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json`) → minimum LIGHT REVIEW, even if score is 0-3.

   Gate routing:
   - **AUTO-EXECUTE (0-3)**: Create git tag `pre-auto-execute-{todo_id}`. Skip plan, execute with context.
   - **LIGHT REVIEW (4-7)**: 1-line summary + `Proceed? [Y/n]` (default yes).
   - **FULL REVIEW (8-14)**: Full EnterPlanMode/ExitPlanMode.

   If `--force-plan`: always route to FULL REVIEW.

**3b.** Call `EnterPlanMode`. Create an implementation plan for this todo. Include any Related Context from step 3. (Skipped if gate routed to AUTO-EXECUTE.)
**4.** Plan approval (respects trust level):
   - **Trust 0**: Call `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: Call `ExitPlanMode` for user review. User approves this plan, then move to the next todo.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
**5.** Store the approved plan in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust level is NOT 3:
     Before spawning: if `len(executing_agents) >= max_parallel`, wait for at least one executing agent to complete.
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**Cross-review** (if quality_level == paranoid AND N > 1):
After all plans are generated, each plan is cross-reviewed by an independent read-only agent.
Agent i reviews plan (i+1) % N. For N=1, cross-review is skipped.
Each cross-review agent receives: the plan to review + that todo's requirements + the reviewer's own todo context for perspective.
Cross-review output: risk rating (LOW/MEDIUM/HIGH) + concerns list.
If any HIGH risk: flag for user attention before proceeding to execution.

Phase 2 — Execute (sequential, in dependency order):

Enforce max_parallel from quality_level parameter mapping. Do not spawn more agents than max_parallel allows.

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents in batch failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:
Execute each todo according to its approved plan (or context only if trust 3), one at a time (respecting blocked_by chains). Each todo: mark in_progress, implement per plan.
IF todo was part of a pattern group: Include in the agent prompt: "This todo is part of a pattern group (N similar todos). The common pattern is: <normalized pattern>. Implement consistently with the group."

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
Clear `executing_agents = {}` after satisfaction checks complete.

**Note:** Root todo execution does NOT auto-recurse into children. To execute children, specify their IDs explicitly.

**6.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Execute: {todo-id}"`.

## Prerequisites

- An active project must be loaded.
- A valid todo ID or range must be provided (or an in-progress/ready todo must exist).

## Error Handling

- **No active project**: displays error and stops.
- **Manual-tagged todo**: displays warning from `todo_check_executable` and stops (does not implement).
- **Blocked todo**: displays error and stops.
- **Verification failures**: presents combined report and offers Fix/Proceed/Skip options.
- **Agent failures (team/task mode)**: reports failed agents per todo. Logged to `failed-teams.yaml`.
- **Stale checkpoint (--resume)**: asks user whether to restart or use stale data.

## Output

- **Single todo**: Implementation result, verification report (if enabled), satisfaction loop outcome, completion confirmation.
- **Range/batch**: Per-batch execution progress, combined verification summary table, satisfaction loop for each completed todo, overall summary.

Suggested next: `1. /proj:save` -- save session and reconcile git | `2. /proj:status` -- see updated project overview
