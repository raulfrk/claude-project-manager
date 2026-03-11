---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
disable-model-invocation: "true"
allowed-tools: mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__tracking_git_flush, Read, Task, EnterPlanMode, ExitPlanMode
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive]"
---

Run workflow for: $ARGUMENTS

**1. Parse and validate**

Extract from $ARGUMENTS:
- **Input mode**: single ID (`1`), range (`2-5`), or comma list (`1,3,5`)
- **`--steps <csv>`**: explicit step list (reordered to workflow order)
- **`--from <step>`**: slice from that step onward (`--steps` takes precedence)
- **`--iter N`**: prep iteration count (default 1, positive integer)
- **`--no-interactive`**: run autonomously with no user prompts

If no todo ID: stop with `Todo ID required. Usage: /proj:run <id> [--steps define,execute] [--from <step>]`

Default step order: `[define, decompose, execute]`.
Apply `--steps` or `--from` to filter/slice. Error if any step name is invalid.

For **single ID**: call `mcp__proj__todo_get` to confirm it exists. Continue to step 2.
For **range or comma list**: parse into a deduplicated list. Skip to **"Batch mode"** below.

> **Read failure policy**: Any `Read` call on a sibling SKILL.md file that fails must be treated as a hard stop.

---

## Single-ID mode

**2. Display**

```
Running workflow on todo **<id>** — <title>
Steps: <step1> → <step2> → ... (x<N> iterations)
```

Split into: `prep_steps` = all except `execute`, `has_execute` = whether `execute` is in steps.

**3. Iteration loop** (repeat up to N times)

If N > 1, announce: `Iteration <i>/<N>`

Build descendant list: call `mcp__proj__todo_tree`, flatten depth-first.

**For each prep step:**

Read the sibling `<step>/SKILL.md` file. Extract instructions after the second `---`.

**If `define`** — sequential, interactive:
- For each todo in descendant list (in dependency order via `mcp__proj__proj_identify_batches`):
  - Announce: `Define: <id> — <title>`
  - Execute the define skill interactively (Q&A + research in main conversation)

**If `decompose`** — parallel Task agents:
- For each batch in dependency order:
  - Spawn one `general-purpose` Task agent per todo. Each runs decompose autonomously.
  - Wait for batch completion. Report failures.
- After completion: refresh descendant list via `mcp__proj__todo_tree`.

**3.5. Capture iteration snapshots** (only when N > 1)

**Before iteration 1 starts** (after building the initial descendant list but before running any prep steps), capture the pre-existing state as `snapshot_0`:
- For each todo in the descendant list (including root): read `content_get_requirements` and `content_get_research`
- Record the descendant list structure: child IDs, titles, and blocked_by for each
- If descendant list exceeds 15 todos, read content for root-level children only.

**After each iteration's prep steps complete**, capture the current state as `snapshot_<i>` using the same method.

**4. Between-iteration prompt** (skip if last iteration or `--no-interactive`)

**4a. Convergence assessment**

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

**4b. Next action prompt**

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** — Start iteration <i+1>
2. **Skip to execute** — Prep has converged, proceed to execute
3. **Edit** — Modify this iteration's output
4. **Stop** — Exit workflow now (completed steps are saved)
```

When the user picks option 2, skip all remaining iterations and jump directly to step 5 (Execute).

**5. Execute** (only if `has_execute`)

Refresh todo via `mcp__proj__todo_get`. Determine `has_children = len(children) > 0`.

If NOT `--no-interactive`, prompt:

```
### Prep complete — Execute?

1. **Proceed** — Run execute
2. **Edit** — Modify prep output
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

**Phase 1 — Plan (sequential, main conversation):**

Store `approved_plans = {}` and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: display `Todo <id> [manual] — skipped`, add to `manual_skipped_ids`, continue.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. `EnterPlanMode`. Read context and explore relevant source files. Create an implementation plan covering files to modify/create, key changes, implementation order, testing approach.
4. `ExitPlanMode` for user review. User approves or requests changes.
5. Store approved plan in `approved_plans[todo_id]`.

If `--no-interactive`: skip Phase 1, proceed directly to Phase 2 with execute instructions only.

**Phase 2 — Execute (parallel Task agents):**

For each batch in dependency order (excluding `manual_skipped_ids`):
1. Display: `Executing batch <N>/<total>: todos <id1>, <id2>, ...`
2. Spawn one `general-purpose` Task agent per todo. Each receives: todo details, requirements.md, research.md, parent context, AND the approved plan (or execute instructions if `--no-interactive`). Each implements and calls `todo_complete`.
3. Wait for batch completion. Report failures: `Agent for todo <id> failed: <error>`.

Auto-complete parent: if `manual_skipped_ids` is empty, call `mcp__proj__todo_complete` on parent + Todoist complete if applicable. Otherwise display warning.

**6. Complete**

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

Call `mcp__proj__notes_append` with brief summary.

7. **Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

Suggested next: /proj:status — see updated project overview

---

## Batch mode

*(Range or comma list input — all steps run autonomously)*

**a. Setup**
- Load step list, apply `--steps`/`--from` flags.
- `run_define_interactive` = `define` in steps AND NOT `--no-interactive`
- `has_execute` = `execute` in steps
- `agent_steps` = steps excluding `define` (if interactive) and `execute`
- Read SKILL.md for each step in `agent_steps`. Store as `step_instructions[step]`.
- If `run_define_interactive`: also read `define/SKILL.md` once.

**b. Dependency order**
Call `mcp__proj__proj_identify_batches` with all todo IDs. Error on cycles.

**Iteration loop** (repeat up to `--iter N` times, default 1):

If N > 1: announce `Iteration <i>/<N>`

**Phase A — Define (if `run_define_interactive`):**
For each todo in dependency order:
- Announce: `Define: <id> — <title>`
- Execute define interactively in main conversation

**Phase B — Remaining steps (parallel agents):**
For each batch in dependency order:
- Spawn one `general-purpose` Task agent per todo. Each runs `agent_steps` autonomously.
- Wait for batch completion. Report failures.

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

Store `approved_plans = {}` and `manual_skipped_ids = []`.

For each todo in dependency order:
1. Call `mcp__proj__todo_check_executable` — if manual: skip with warning.
2. Call `mcp__proj__proj_get_todo_context` with `include_parent=true`.
3. `EnterPlanMode` — create implementation plan.
4. `ExitPlanMode` — user reviews and approves.
5. Store approved plan.

If `--no-interactive`: skip Phase C1.

**Phase C2 — Execute (parallel Task agents):**
For each batch in dependency order (excluding `manual_skipped_ids`):
- Spawn one agent per todo with approved plan (or execute instructions if `--no-interactive`).
- Wait for completion. Report failures.

**d. Summary**

Display per-batch breakdown and overall count. Call `mcp__proj__notes_append`.

**e. Git tracking flush**: Call `mcp__proj__tracking_git_flush` with `commit_message="Run: {todo-id}"`.

Suggested next: /proj:status — see updated project overview
