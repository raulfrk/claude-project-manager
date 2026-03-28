---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, TeamCreate, TeamDelete, SendMessage
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive] [--no-verify] [--team] [--no-team] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--refine]"
---

Run workflow for: $ARGUMENTS

**1.** Parse and validate

Extract from $ARGUMENTS:
- **Input mode**: single ID (`1`), range (`2-5`), or comma list (`1,3,5`)
- **`--steps <csv>`**: explicit step list (reordered to workflow order)
- **`--from <step>`**: slice from that step onward (`--steps` takes precedence)
- **`--iter N`**: prep iteration count (default 5, positive integer)
- **`--no-interactive`**: run autonomously with no user prompts
- **`--no-verify`**: skip verification step in execute (passed through to execute skill)
- **`--team`**: force team mode ON (overrides config)
- **`--no-team`**: force team mode OFF (overrides config)
- **`--full-context`**: when using team mode, include CLAUDE.md and NOTES.md in each agent's context
- **`--trust N`** (N = 0-3): override trust level for execution phases. If not specified, use `team_mode.trust_level` from config (default 1 if unset). Trust levels:
  - **Trust 0 (supervised)**: per-todo approval — each plan presented individually, user approves one at a time.
  - **Trust 1 (guided)**: bulk approval + parallel execution — all plans presented, user approves in bulk. Default.
  - **Trust 2 (autonomous)**: auto-approve plans — skip `ExitPlanMode` user review. Plans created and automatically approved.
  - **Trust 3 (full-auto)**: no plan phase — skip planning entirely. Agents execute with context only (requirements + research + parent context).
- **`--resume`**: resume execution from the most recent checkpoint. See **Resume checkpoint** sections below.
- **`--no-pipeline`**: disable plan-while-executing pipeline (default: pipeline enabled)
- **`--refine`**: enable requirement refinement with 3 review agents after last prep iteration (default: off)

Derive: `pipeline_enabled = not no_pipeline_flag`

If no todo ID, stop with: "Todo ID required. Usage: `/proj:run <id> [--steps define,execute] [--from <step>]`"

Default step order: `[define, preflight, decompose, refine, execute]`.
Apply `--steps` or `--from` to filter/slice. Error if any step name is invalid.

For **single ID**: call `mcp__proj__todo_get` to confirm it exists. Continue to step 2.
For **range or comma list**: parse into a deduplicated list. Skip to **"Batch mode"** below.

> **Read failure policy**: Any `Read` call on a sibling SKILL.md file that fails must be treated as a hard stop.

---

## Single-ID mode

**2.** Display

```
Running workflow on todo **<id>** — <title>
Steps: <step1> → <step2> → ... (x<N> iterations)
```

Split into: `prep_steps` = all except `execute`, `has_execute` = whether `execute` is in steps.

**3.** Iteration loop (repeat up to N times)

If N > 1, announce: `Iteration <i>/<N>`

Build descendant list: call `mcp__proj__todo_tree`, flatten depth-first.

**For each prep step:**

Read the sibling `<step>/SKILL.md` file. Extract instructions after the second `---`.

**If `define`** — sequential, interactive:
- For each todo in descendant list (in dependency order via `mcp__proj__proj_identify_batches`):
  - Announce: `Define: <id> — <title>`
  - Execute the define skill interactively (Q&A + research in main conversation)
  - If current iteration > 1, pass `--skip-bg-prep` to define (codebase hasn't changed between iterations, background prep would be redundant).

**Quality gate check** (after define phase):
For each todo defined non-interactively (agent-driven):
- Read the self-assessment from define output
- If any section has confidence ≤ 2 (speculative or inferred), add to flagged_todos

If flagged_todos is non-empty, display:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

If Re-define: run interactive define on each flagged todo, then resume from decompose.

**If `preflight`** — inline, main conversation:

<!-- TODO: skip if --fast quality level is set (see todo 280) -->

For each todo in descendant list:
1. Read requirements.md via `content_get_requirements`. If not found: hard fail with "No requirements found. Run define first." (counts as all 5 checks failing).
2. Read research.md via `content_get_research`. If not found: mark check 3 as FAIL, continue other checks.
3. Run 5 structural checks:

   | # | Check | Pass condition |
   |---|-------|---------------|
   | 1 | Testable acceptance criteria | "Acceptance Criteria" section exists with >= 1 item, no vague language ("should be fast", "works well", "properly", "good", "clean", "efficient") |
   | 2 | Out-of-scope section | "Out of Scope" section exists with >= 1 bullet |
   | 3 | Research approach options | research.md contains >= 2 approach options (section headers or numbered options under "Approach Options") |
   | 4 | Testing strategy coverage | "Testing Strategy" section mentions >= 2 of: unit, integration, e2e, manual |
   | 5 | Edge cases documented | "Edge Cases" section has >= 2 bullets or list items |

4. If all pass: silent, proceed to next step.
5. If any fail AND NOT `--no-interactive`: display table and prompt:

   ```
   ### Preflight Check — <N> issue(s) found

   | # | Check | Status |
   |---|-------|--------|
   | 1 | Testable criteria | PASS |
   | 2 | Out of scope | FAIL — <message> |
   ...

   1. **Fix** — Re-run define on this todo to address failures
   2. **Continue** — Proceed to decompose anyway
   3. **Stop** — Exit workflow
   ```

   Fix → re-run define on the failing todo, then re-run preflight.

6. If any fail AND `--no-interactive`: log warnings to notes via `notes_append`, auto-continue to next step.

**If `decompose`** — parallel Task agents:
- For each batch in dependency order:
  - Spawn one `general-purpose` Task agent per todo. Each runs decompose autonomously.
  - Wait for batch completion. Report failures.
- After completion: refresh descendant list via `mcp__proj__todo_tree`.

**3a.** Capture iteration snapshots (only when N > 1)

**Before iteration 1 starts** (after building the initial descendant list but before running any prep steps), capture the pre-existing state as `snapshot_0`:
- For each todo in the descendant list (including root): read `content_get_requirements` and `content_get_research`
- Record the descendant list structure: child IDs, titles, and blocked_by for each
- If descendant list exceeds 15 todos, read content for root-level children only.

**After each iteration's prep steps complete**, capture the current state as `snapshot_<i>` using the same method.

**4.** Between-iteration prompt (skip if last iteration or `--no-interactive`)

**4a.** Convergence assessment

Compare `snapshot_<i>` with `snapshot_<i-1>` across four dimensions:

- **Requirements**: Compare requirements.md text for each todo. Ignore whitespace/formatting/minor rewording. Flag new acceptance criteria, changed goals, or changed testing strategy.
- **Research**: Compare research.md text. Flag changed recommended approach, new options, or significant new findings.
- **Structure**: Compare descendant lists. Check for new/removed children or title changes.
- **Dependencies**: Compare blocked_by relationships. Check for new/removed blocking edges.

Display:

```
### Convergence Assessment (Iteration <i>)

**Requirements**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Research**: [Stable | Minor changes | Significant changes] — <1-line summary>
**Structure**: [Stable | Changed] — <summary>
**Dependencies**: [Stable | Changed] — <summary>

**Recommendation**: [Ready to execute — prep has converged] OR [Continue iterating — <reason>]
```

Recommend "Ready to execute" when ALL dimensions are Stable or Minor changes with no new structural additions. Otherwise recommend "Continue iterating".

**4b.** Next action prompt

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** — Start iteration <i+1>
2. **Skip to execute** — Prep has converged, proceed to execute
3. **Redefine** — Re-run interactive define on specific todos (enter IDs)
4. **Stop** — Exit workflow now (completed steps are saved)
```

When the user picks option 2, skip all remaining iterations and jump directly to step 5 (Execute).
When the user picks option 3: prompt for todo IDs, run interactive define on each, then resume from decompose step.

**4.5** Refine (if `--refine` flag set AND `refine` in steps AND NOT `--no-interactive`)

<!-- TODO: auto-enable for --careful/--paranoid quality levels (see todo 280) -->
<!-- TODO: skip for --fast quality level (see todo 280) -->

Read the sibling `refine/SKILL.md` file. For each todo in descendant list:
  Execute the refine sub-skill with the todo's ID.
  The sub-skill spawns 3 review agents (Skeptic, Edge-Case Finder, Architecture Reviewer), synthesizes a Refinement Report, and prompts Apply/Edit/Skip/Stop.
  If Apply: requirements/research are updated and preflight re-runs automatically.

**5.** Execute (only if `has_execute`)

Refresh todo via `mcp__proj__todo_get`. Determine `has_children = len(children) > 0`.

If NOT `--no-interactive`, prompt:

```
### Prep complete — Execute?

1. **Proceed** — Run execute
2. **Redefine** — Re-run interactive define on specific todos (enter IDs)
3. **Stop** — Exit (prep saved)
```

**If no children** — execute parent only (step 5i).
**If has children** — execute all (parent + descendants) via step 5ii.

**5i. Single execute:**
1. Call `mcp__proj__todo_check_executable` — if manual-tagged: display warning and stop.
2. Read `execute/SKILL.md`.
3. Execute the step (plan mode is built into the execute skill — it calls EnterPlanMode/ExitPlanMode).

**5ii. Execute-all (parent + descendants):**

Read `execute/SKILL.md` instructions once.
Build full list: `[todo_id] + all_descendants` (from todo_tree, flattened depth-first).
Call `mcp__proj__proj_identify_batches` for dependency order.

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine execution mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 3+ total (non-manual) descendants: use **Team-based execution** below.
- Otherwise: use **Task agent execution** below.

**--- Team-based execution (5ii-T) ---**

**Phase 1 — Plan (sequential, main conversation):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

If `--no-interactive`: skip Phase 1, proceed directly to Phase 2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
4. `EnterPlanMode`. Read context and explore relevant source files. Create an implementation plan covering files to modify/create, key changes, implementation order, testing approach. Include any Related Context from step 3.
5. Plan approval (respects trust level):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
6. Store approved plan in `approved_plans[todo_id]`.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

After all plans are stored (trust 0-1): present a bulk approval summary showing all todo IDs and their plan summaries.

**File-Overlap Detection** (after Phase 1, before Phase 2, skip if trust 3):
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

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", description="Run: executing descendants of todo {parent_id} in {N} batches")`
1a. **Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo across all batches:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the same execution set, use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop handles proj todo completion.

2. For each batch in dependency order (excluding `manual_skipped_ids`):
   - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo in this batch with `team_name`. Each agent receives: the approved plan (or context only if trust 3) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content. Each implements the approved plan. Agents do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report failures: `Agent for todo <id> failed: <error>`.
   - **Write checkpoint** after each batch to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**--- Task agent execution (5ii-F, fallback) ---**

**Phase 1 — Plan (sequential, main conversation):**

Skip Phase 1 entirely if **trust level is 3** — go directly to Phase 2 with context only (no plans).

If `--no-interactive`: skip Phase 1, proceed directly to Phase 2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
4. `EnterPlanMode`. Read context and explore relevant source files. Create an implementation plan covering files to modify/create, key changes, implementation order, testing approach. Include any Related Context from step 3.
5. Plan approval (respects trust level):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
6. Store approved plan in `approved_plans[todo_id]`.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**Phase 2 — Execute (parallel Task agents):**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

For each batch in dependency order (excluding `manual_skipped_ids`):
1. Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one `general-purpose` Task agent per todo. Each receives: todo details, requirements.md, research.md, parent context, AND the approved plan (or context only if trust 3, or execute instructions if `--no-interactive`). Each implements the approved plan. Agents do NOT call `todo_complete`.
3. Wait for batch completion. Report failures: `Agent for todo <id> failed: <error>`.

**--- Common post-execute (both modes) ---**

**Verification** (skip entirely if `--no-verify` was passed):

For each completed todo across all batches (excluding failed agents and `manual_skipped_ids`), run the verification checks from execute step 4a:
- **A. Automated checks** (detect test runner, run tests/lint)
- **B. Spec validation** (check acceptance criteria against git diff)
- **C. Diff review** (compare approved plan files vs actual changes)

Verify ALL todos first, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist each todo's report to `todos/<id>/verification-report.md` in the tracking dir (with timestamp, overwrite previous).

If any todo has failures, prompt:
> N passed, M failed. Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with: (1) the verification report, (2) todo details + requirements.md + research.md + parent context (via `proj_get_todo_context`), (3) the approved implementation plan, and (4) instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). Update the combined report and re-prompt if still failing.
- **Proceed**: continue to satisfaction check despite failures.
- **Skip**: skip remaining verification for this session.

If all checks pass, display the report and proceed without prompting.

**Satisfaction check** (sequential, main conversation): For each completed todo in the batch, run the satisfaction loop:
   a. Ask: "Are you satisfied with the outcome of todo <id>, or is there anything else that needs to be done?"
      1. **Satisfied** — mark done: call `mcp__proj__todo_complete`
      2. **Not satisfied** — fix in scope: ask what's missing, create new todo (`todo_add`), run full workflow (`/proj:run <new_id> --iter 5`), then re-ask satisfaction on original todo
      3. **Redefine** — refine requirements and re-run workflow: run interactive define on the todo, then re-run `/proj:run <id> --from decompose`

Auto-complete parent: if `manual_skipped_ids` is empty, run the satisfaction loop (3-option: Satisfied / Not satisfied / Redefine) for the parent todo before calling `mcp__proj__todo_complete` on parent. Otherwise display warning.

Clear `executing_agents = {}` before proceeding to the next batch.

**6.** Complete

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

Call `mcp__proj__notes_append` with brief summary.

**7.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

Suggested next: `1. /proj:status` -- see updated project overview

---

## Batch mode

*(Range or comma list input — all steps run autonomously)*

**a.** Setup
- Load step list, apply `--steps`/`--from` flags.
- `run_define_interactive` = `define` in steps (always interactive — define requires user input even in batch mode)
- `has_execute` = `execute` in steps
- `agent_steps` = steps excluding `define` (if interactive) and `execute`
- Read SKILL.md for each step in `agent_steps`. Store as `step_instructions[step]`.
- If `run_define_interactive`: also read `define/SKILL.md` once.

**b.** Dependency order
Call `mcp__proj__proj_identify_batches` with all todo IDs. Error on cycles.

**Iteration loop** (repeat up to `--iter N` times, default 5):

If N > 1: announce `Iteration <i>/<N>`

**Phase A — Define (if `run_define_interactive`):**
For each todo in dependency order:
- Announce: `Define: <id> — <title>`
- Execute define interactively in main conversation
- If current iteration > 1, pass `--skip-bg-prep` to define (codebase hasn't changed between iterations, background prep would be redundant).

**Quality gate check** (after define phase):
For each todo defined non-interactively (agent-driven):
- Read the self-assessment from define output
- If any section has confidence ≤ 2 (speculative or inferred), add to flagged_todos

If flagged_todos is non-empty, display:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

If Re-define: run interactive define on each flagged todo, then resume from decompose.

**Phase A.5 — Preflight checklist:**

<!-- TODO: skip if --fast quality level is set (see todo 280) -->

For each todo in dependency order:
  Run the 5 preflight checks (same as single-ID mode above).
  Collect all failures.

If any failures AND NOT `--no-interactive`:
  Display combined table:

  ```
  ### Preflight Check — <N> issues across <M> todos

  | Todo | Check | Status |
  |------|-------|--------|
  | <id> | <check name> | FAIL — <message> |
  ...

  1. **Fix** — Re-run define on failing todos
  2. **Continue** — Proceed to decompose for all
  3. **Stop** — Exit workflow
  ```

  Fix → re-run define on failing todos, then re-run preflight on those todos.

If any failures AND `--no-interactive`: log warnings to notes, auto-continue.
If all pass: silent, proceed to Phase B.

**Phase B — Remaining steps (parallel agents):**

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 3+ non-manual todos in the batch: use **Team mode** below.
- Otherwise: use **Task agent mode** below.

**Team mode:**
1. `TeamCreate(name="run-decompose-{project}-{timestamp}", description="Run: decomposing todos {id1}, {id2}, ...")`
2. For each batch in dependency order:
   - Spawn one Agent per todo in this batch with `team_name`. Each runs `agent_steps` autonomously. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content. If agents hit an issue, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report failures.
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml`.

**Task agent mode (fallback):**
For each batch in dependency order:
- Spawn one `general-purpose` Task agent per todo. Each runs `agent_steps` autonomously.
- Wait for batch completion. Report failures.

After Phase B completes (either mode): refresh descendant lists via `mcp__proj__todo_tree`.

**Phase B.5 — Convergence check** (skip if `--no-interactive`, only when N > 1)

**Before iteration 1 starts** (after dependency order but before Phase A), capture pre-existing state as `snapshot_0` for each todo in the input list (requirements, research, tree structure).
**After each iteration**, capture current state as `snapshot_<i>`.

Compare `snapshot_<i>` with `snapshot_<i-1>` and display:

```
### Convergence Assessment (Iteration <i>) — Batch

| Todo | Requirements | Research | Structure |
|------|-------------|----------|-----------|
| <id> | Stable/Minor/Significant | ... | ... |

**Overall**: [Ready to execute | Continue iterating] — <reason>
```

Then show the between-iteration prompt (same 4 options as single-ID mode).

**Phase B.75 — Refine (if `--refine` flag set AND `refine` in steps AND NOT `--no-interactive`):**

<!-- TODO: auto-enable for --careful/--paranoid quality levels (see todo 280) -->
<!-- TODO: skip for --fast quality level (see todo 280) -->

Read the sibling `refine/SKILL.md` file. For each todo in dependency order:
  Execute the refine sub-skill per-todo (3 agents each, 3*N total for N todos).
  Present per-todo refinement reports sequentially.
  If Apply on any todo: requirements/research updated, preflight re-runs on that todo.

**Phase C — Execute (after iteration loop):**

If `has_execute` is false: skip to summary.

If NOT `--no-interactive`, prompt:
```
### Prep complete — Execute?

1. **Execute all** — Plan and execute all todos
2. **Stop** — Exit (prep saved)
```

Read `execute/SKILL.md` instructions once.

**Phase C1 — Plan (sequential, main conversation):**

Skip Phase C1 entirely if **trust level is 3** — go directly to Phase C2 with context only (no plans).

If `--no-interactive`: skip Phase C1, proceed directly to Phase C2 with execute instructions only.

Store `approved_plans = {}`, `executing_agents = {}`, and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: skip with warning.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. Call `mcp__proj__proj_search_knowledge` with `query=<todo title>` and `scope=all`. If snippets are returned, include them as a "### Related Context" section when creating the implementation plan below. If no snippets are returned, skip silently.
4. `EnterPlanMode` — create implementation plan. Include any Related Context from step 3.
5. Plan approval (respects trust level):
   - **Trust 0**: `ExitPlanMode` for user review. User approves this plan before the next todo's plan is created.
   - **Trust 1**: `ExitPlanMode` for user review. User approves this plan, then move to the next todo. After all plans: present a bulk approval summary for final confirmation.
   - **Trust 2**: Skip `ExitPlanMode` user review. Display: `Plan auto-approved (trust 2): <1-line summary>`. Store and move to the next todo.
6. Store approved plan.
7. IF `pipeline_enabled` AND trust level is NOT 3:
     Spawn a background `general-purpose` Task agent with: todo details, requirements.md, research.md, parent context, and the approved plan. Instruction: implement the approved plan, do NOT call `todo_complete`. Store handle in `executing_agents[todo_id]`.

**File-Overlap Detection** (after Phase C1, before Phase C2, skip if trust 3):
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

**Phase C2 — Execute:**

**Mode selection:** Call `mcp__proj__config_load` to read `team_mode.enabled`. Determine mode:
- If `--team` flag was passed, OR (`config_load().team_mode.enabled` is true AND `--no-team` was NOT passed) AND there are 3+ non-manual todos: use **Team mode** below.
- Otherwise: use **Task agent mode** below.

**Resume checkpoint** (applies when `--resume` is passed):
1. Look for the most recent checkpoint file in `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. If found and not stale (created within the last 24 hours):
   - Read the checkpoint. Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
   - Use the stored `approved_plans` from the checkpoint.
   - Skip to the `batch_index` in Phase C2 (all prior batches are treated as complete).
3. If the checkpoint is stale (older than 24 hours) or references todos that no longer exist:
   - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
   - If Restart: ignore checkpoint and start from Phase C1.
   - If Use anyway: proceed with the stale checkpoint data.
4. If no checkpoint found: display `No checkpoint found — starting fresh` and proceed normally.

**Team mode:**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

1. `TeamCreate(name="run-exec-{project}-{timestamp}", description="Run: executing todos {id1}, {id2}, ... in {N} batches")`
1a. **Task Mapping** (one-way — tasks mirror todos for coordination only):
   For each todo across all batches:
   - Call `TaskCreate` with:
     - `title`: todo title
     - `description`: `"Implement todo {id} — {title}"`
     - `metadata`: `{"proj_todo_id": "{todo.id}", "team_name": "{team_name}"}`
   - If the todo has `blocked_by` relationships with other todos in the same execution set, use `addBlockedBy` to map the blocking relationships (using the Task IDs returned from previous `TaskCreate` calls).

   Agents discover their assigned tasks via `TaskList(metadata={"team_name": team_name})` (pull model — agents are not assigned tasks directly).

   **One-way only**: Task completion does NOT auto-complete the proj todo. The satisfaction loop handles proj todo completion.

2. For each batch in dependency order (excluding `manual_skipped_ids`):
   - Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
   - Spawn one Agent per todo in this batch with `team_name`. Each agent receives: the approved plan (or context only if trust 3, or execute instructions if `--no-interactive`) + requirements.md + research.md + parent context. If `--full-context` flag was passed, also include CLAUDE.md and NOTES.md content.
   - Agents execute the approved plan as-is. They do NOT call `todo_complete`. If they hit an issue not covered by the plan, they report via `SendMessage` to the team lead rather than improvising.
   - Wait for this batch to complete before starting the next batch. Report failures.
   - **Write checkpoint** after each batch to `<tracking_dir>/<project>/.team-state/<team-name>/checkpoint.yaml`:
     ```yaml
     team_name: run-exec-{project}-{timestamp}
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
3. After all batches complete: `TeamDelete(team_name)`
4. If any agents failed, log the failures to `tracking/{project}/.team-state/failed-teams.yaml` (create the directory if needed).

**Task agent mode (fallback):**

IF `pipeline_enabled`:
    Wait for all `executing_agents` in this batch to complete. Report any failures.
    -- batch failure short-circuit --
    IF all agents in this batch failed: display "All N agents failed. (1) Retry batch (2) Skip to next batch (3) Stop." Handle user choice; skip individual satisfaction loops.
ELSE:

For each batch in dependency order (excluding `manual_skipped_ids`):
- Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
- Spawn one `general-purpose` Task agent per todo with approved plan (or context only if trust 3, or execute instructions if `--no-interactive`). Each receives: todo details, requirements.md, research.md, parent context. Agents do NOT call `todo_complete`.
- Wait for completion. Report failures.

**Phase C2a — Verification** (skip entirely if `--no-verify` was passed):

For each completed todo across all batches (excluding `manual_skipped_ids` and failed agents), run the verification checks from execute step 4a:
- **A. Automated checks** (detect test runner, run tests/lint)
- **B. Spec validation** (check acceptance criteria against git diff)
- **C. Diff review** (compare approved plan files vs actual changes)

Verify ALL todos first, then display a combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| <id> | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| <id> | FAIL (2 failed) | 2/3 met | 1 extra file | FAIL |
```

Persist each todo's report to `todos/<id>/verification-report.md` in the tracking dir (with timestamp, overwrite previous).

If any todo has failures, prompt:
> N passed, M failed. Fix failed todos? (1) Fix (2) Proceed (3) Skip
- **Fix**: spawn one `general-purpose` Task agent per failed todo with: (1) the verification report, (2) todo details + requirements.md + research.md + parent context (via `proj_get_todo_context`), (3) the approved implementation plan, and (4) instructions to fix the failures. After agents complete, re-run verification on fixed todos only (max 2 retries). Update the combined report and re-prompt if still failing.
- **Proceed**: continue to summary despite failures.
- **Skip**: skip remaining verification for this session.

If all checks pass, display the report and proceed without prompting.

**Satisfaction check** (sequential, main conversation):
For each completed todo (excluding `manual_skipped_ids`), run the satisfaction loop:
   a. Ask: "Are you satisfied with the outcome of todo <id>, or is there anything else that needs to be done?"
      1. **Satisfied** — mark done: call `mcp__proj__todo_complete`
      2. **Not satisfied** — fix in scope: ask what's missing, fix, re-ask
      3. **Redefine** — refine requirements and re-run workflow

Clear `executing_agents = {}` before proceeding to the next batch.

**d.** Summary

Display per-batch breakdown and overall count. Call `mcp__proj__notes_append`.

**e.** Git tracking flush: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

## Prerequisites

- An active project must be loaded.
- A valid todo ID, range, or comma list must be provided.

## Error Handling

- **No todo ID**: displays `Todo ID required.` with usage and stops.
- **Todo not found**: displays error from `todo_get` and stops.
- **Invalid step name**: displays error and stops.
- **Manual-tagged todo**: skips with warning `Todo <id> [manual] — skipped`.
- **Quality gate failure (define phase)**: presents low-confidence definitions and offers Continue/Re-define/Stop.
- **Verification failures (execute phase)**: presents combined report with Fix/Proceed/Skip options.
- **Agent failures (team/task mode)**: reports failed agents. Logged to `failed-teams.yaml`.
- **Read failure on sibling SKILL.md**: treated as a hard stop.
- **Stale checkpoint (--resume)**: asks user whether to restart or use stale data.

## Output

- **Single-ID**: Workflow progress through each step (define, decompose, execute), convergence assessments between iterations, verification report, satisfaction loop, completion confirmation.
- **Batch mode**: Per-todo define (interactive), parallel decompose, parallel execute with batched verification, satisfaction loop for each completed todo, overall summary.

Suggested next: `1. /proj:status` -- see updated project overview
