---
name: run
description: Run the full workflow (define → decompose → execute) on a todo interactively, prompting between each step. Use when asked "run 1", "full workflow on 1", or "proj:run 1".
allowed-tools: mcp__proj__config_load, mcp__proj__content_get_requirements, mcp__proj__content_get_research, mcp__proj__content_set_requirements, mcp__proj__content_set_research, mcp__proj__notes_append, mcp__proj__proj_get_todo_context, mcp__proj__proj_identify_batches, mcp__proj__proj_search_knowledge, mcp__proj__todo_add_child, mcp__proj__todo_block, mcp__proj__todo_check_executable, mcp__proj__todo_complete, mcp__proj__todo_get, mcp__proj__todo_list, mcp__proj__todo_set_content_flag, mcp__proj__todo_tree, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append, mcp__proj__tracking_git_flush, Read, Task, TaskCreate, TaskList, EnterPlanMode, ExitPlanMode, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__worktree__wt_add_repo, mcp__proj__proj_session_context, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, mcp__proj__proj_decision_log, AskUserQuestion
argument-hint: "<todo-id> [--steps define,execute] [--from <step>] [--iter N] [--no-interactive] [--no-verify] [--resume] [--fast|--careful] [--max-parallel N] [--with-adversarial-review] [--no-tasks]"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Run workflow for: $ARGUMENTS

**1.** Parse & validate

Extract from $ARGUMENTS:
- Input: single ID (`1`). Range/comma list → dispatched to `/proj:run-batch`.
- `--no-verify`: skip verification in execute (passed through)
- `--resume`: resume from most recent checkpoint. See Resume checkpoint sections.
- `--fast`: minimize review gates, auto-exec low-complexity todos, skip verification. Tag immunity: `security`/`breaking-change`/`migration` still get FULL REVIEW.
- `--careful`: default. Full review all plans, auto-enable refine, enhanced verification. For sequential exec, combine w/ `--max-parallel 1`.
- `--max-parallel N`: override max_parallel (e.g. `--careful --max-parallel 1` for former `--paranoid` behavior).
- Quality levels mutually exclusive (last wins, default: `--careful`).
- `--with-adversarial-review`: re-enables Phase A.5b (adversarial review — define) + Phase C0.5b (adversarial review — pre-execute). Default: off.
- `--no-tasks`: disable all TaskCreate calls. Use when you want clean output without task tracking.

Derive: `tasks_enabled = "--no-tasks" not in ARGUMENTS`
Derive: `adversarial_review_enabled = "--with-adversarial-review" in ARGUMENTS`

Derive `quality_level` from flags. If no quality flag, call `mcp__proj__config_load` and read `config.quality_level`, defaulting to `--careful` if unset/unrecognized.

**Quality Level Parameter Mapping:**

| Parameter | --fast | --careful (default) |
|-----------|--------|---------------------|
| gate_override | auto-execute (tag-immune) | full-review |
| verification_mode | skip | enhanced |
| max_parallel | 30 | 10 |
| satisfaction | skip (auto-complete) | per-todo |
| preflight | skip | enabled |
| preflight_structural | skip | enabled |
| pre_execute_preflight | skip | enabled |
| refine | skip | auto-enabled (per iteration) |
| overlap_action | auto-proceed | auto-serialize |

**Former `--paranoid` behavior**: `--careful --max-parallel 1` (sequential exec).

**Recommended cap**: 10 for CPU-bound/API-rate-limited workloads. `--fast` ceiling of 30 tuned for I/O-bound work; override via `--max-parallel` or `config.team_mode.max_agents`.

**Flag compatibility check** (validate before proceeding):
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification skipped.
- `--no-verify --fast` → Redundant.

No todo ID → stop: "Todo ID required. Usage: `/proj:run <id> [--steps define,execute] [--from <step>]`"

Default step order: `[define, preflight, decompose, refine, execute]`.
Apply `--steps`/`--from` to filter/slice. Error on invalid step name.

**Single ID**: `mcp__proj__todo_get` to confirm exists. If input has `:level` suffix (e.g. `1:fast`), parse error: "Cannot use `:level` annotation in single-ID mode. Use `--fast` (or appropriate quality flag) instead."
**Range/comma list** → invoke `skill: "proj:run-batch"` w/ same $ARGUMENTS.

**2.** Display

```
Running workflow on todo **<id>** — <title>
Steps: <step1> → <step2> → ... (x<N> iterations)
```

Split: `prep_steps` = all except `execute`, `has_execute` = `execute` in steps.

**3.** Iteration loop (repeat up to N times)

N > 1 → announce: `Iteration <i>/<N>`

Build descendant list: `mcp__proj__todo_tree`, flatten depth-first.

**Each prep step:**

**If `define`** — sequential, interactive:
(only if tasks_enabled) `TaskCreate(title="Phase A: Define — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "A", "kind": "phase_task"})` → store as `task_A_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_A_id` to agents spawned in this phase.
Each todo in descendant list (dependency order via `mcp__proj__proj_identify_batches`):
 - Announce: `Define: <id> — <title>`
 - `skill: "proj:define", args: "<id>"` (iteration > 1 → append `--skip-bg-prep`).

**Quality gate check** (after define):
Each agent-driven define → read self-assessment. Confidence ≤ 2 (speculative/inferred) → add to flagged_todos.

If flagged_todos non-empty:

```
### Low-confidence definitions detected

| Todo | Low-confidence sections |
|------|------------------------|
| <id> | <section> (<score>/5) |

1. **Continue anyway** — proceed to decompose
2. **Re-define** — run interactive define on flagged todos
3. **Stop** — exit workflow
```

Re-define → run interactive define on each flagged, resume from decompose.

After define complete (or skipped): (only if tasks_enabled) `TaskUpdate(task_A_id, status="completed")`.

**If `preflight`** — inline, main conversation:

fast quality → skip preflight entirely. (No TaskCreate for skipped phases.)

(only if tasks_enabled) `TaskCreate(title="Phase A.5: Preflight — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "A.5", "kind": "phase_task"})` → store as `task_A5_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_A5_id` to agents spawned in this phase.

**Preflight versioning & grandfather rule**: each todo carries `preflight_version` meta. Unset (existing todos) → **legacy mode** w/ 5 checks (1-5). `preflight_version: 2` → expanded 10-check v2. New todos default v2. Manual upgrade: `todo update <id> preflight_version=2`. Bulk migration tracked separately.

**Fix-loop cap**: max 3 re-runs per todo per `/proj:run`. 4th attempt → auto-demote remaining BLOCKING to WARNING: "3 fix attempts exhausted — (1) Continue anyway (2) Stop".

**`--no-interactive` demotion**: BLOCKING auto-demoted to WARNING, logged via `notes_append` tag `preflight:auto-demoted`, decision log entry per demotion. Run auto-continues.

Each todo in descendant list:
1. Read requirements.md via `content_get_requirements`. Not found → hard fail "No requirements found. Run define first." (all checks fail).
2. Read research.md via `content_get_research`. Not found → mark research-dependent checks FAIL, continue others.
3. Structural checks. Legacy = checks 1-5; v2 = all 10:

   | # | Check | Data read | Pass condition | Version |
   |---|-------|-----------|---------------|---------|
   | 1 | Testable acceptance criteria | requirements.md, "Acceptance Criteria" | section exists w/ >= 1 item | v1+v2 |
   | 2 | Out-of-scope section | requirements.md, "Out of Scope" | section exists w/ >= 1 bullet | v1+v2 |
   | 3 | Research approach options | research.md, "Approach Options" or top-level headers | >= 2 options | v1+v2 |
   | 4 | Testing strategy coverage | requirements.md, "Testing Strategy" | mentions >= 2 of: unit, integration, e2e, manual | v1+v2 |
   | 5 | Edge cases documented | requirements.md, "Edge Cases" | >= 2 bullets/list items | v1+v2 |
   | 6 | Vague language (expanded) | requirements.md, "Goal" + "Acceptance Criteria" ONLY | no tokens from expanded vague-phrase list | v2 only |
   | 7 | Acceptance criterion verifiability | requirements.md, "Acceptance Criteria" | each criterion has >= 1 of: file path, fn/class name, CLI cmd, test name, numeric threshold, explicit observable outcome | v2 only |
   | 8 | Research file-path anchor | research.md, "Recommended Approach"/"Key Dependencies" + repo filesystem | >= 1 path ref resolving to existing file | v2 only |
   | 9 | Research option distinctness | research.md, "Approach Options" | when >= 2 options, differ by >= 1 of: library/tool, file/module placement, data-flow direction | v2 only |
   | 10 | Failure-mode coverage | requirements.md, "Edge Cases" | >= 1 explicit failure mode (err path, invalid input, network failure, missing file, permission err, concurrency, timeout) | v2 only |

 **Expanded vague-phrase list (v2, check 6)** — scoped ONLY to "Goal" + "Acceptance Criteria" of requirements.md. Excluded by policy (concrete engineering meanings): "reasonable", "simple", "efficient", "fast", "good", "clean", "lightweight", "proper", "correct", "elegant". List covers only unmeasurable marketing/handwave terms:

   ```
   robust, seamless, scalable, modern, state-of-the-art, best-in-class,
   user-friendly, intuitive, ideal, optimal, blazing, lightning-fast,
   enterprise-grade, world-class, next-generation, performant,
   cutting-edge, turnkey, revolutionary, game-changing, industry-leading,
   bulletproof, frictionless
   ```

 **23 phrases** (exceeds min 20). Self-validated against requirements.md of todos 487, 503-505, 507-510 w/ **zero false positives** in Goal/Acceptance Criteria (only hit: todo 503's own requirements.md where phrases appear as quoted examples — expected meta self-match, not defect).

 Match fails check 6: `Vague term "<token>" in <section> section — replace with a measurable criterion or remove`. Whole-word, case-insensitive.

 **Examples**:
 - FAIL (6): Goal "Build robust, scalable ingestion pipeline." — `robust` + `scalable` match.
 - PASS (6): Goal "Build ingestion pipeline that handles 10k events/sec with <1% drop rate." — measurable, no vague terms.
 - FAIL (7): "Users can log in smoothly" — no path, fn, CLI, test, threshold, or observable outcome.
 - PASS (7): "`POST /api/login` returns 200 with valid JWT in `token` field for valid credentials" — API endpoint + observable outcome.
 - FAIL (8): research.md "Recommended Approach" is pure prose, no file refs.
 - PASS (8): research.md refs `plugins/proj/server/server/tools/todo.py` in "Key Dependencies".

4. All pass → silent, next step.
5. Any fail AND NOT `--no-interactive` (fix-loop < 3):

   ```
   ### Preflight Check — <N> issue(s) found (attempt <k>/3)

   | # | Check | Status |
   |---|-------|--------|
   | 1 | Testable criteria | PASS |
   | 6 | Vague language | FAIL — "robust" in Goal section |
   ...

   1. **Fix** — Re-run define on this todo to address failures
   2. **Continue** — Proceed to decompose anyway
   3. **Stop** — Exit workflow
   ```

 Fix → re-run define on failing todo, re-run preflight (increment counter).
 Attempt 4 → auto-demote remaining BLOCKING to WARNING, prompt only `(1) Continue anyway (2) Stop`.

6. Any fail AND `--no-interactive` → demote BLOCKING to WARNING, log via `notes_append` tag `preflight:auto-demoted`, decision log per demotion, auto-continue.

After preflight complete: (only if tasks_enabled) `TaskUpdate(task_A5_id, status="completed")`. Failure → `TaskUpdate(task_A5_id, status="failed")`.

> Adversarial review phases (A.5b, C0.5b) removed by default. Re-enable via `--with-adversarial-review`.

**If `decompose`** — parallel agents:
(only if tasks_enabled) `TaskCreate(title="Phase B: Decompose — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "B", "kind": "phase_task"})` → store as `task_B_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_B_id` to agents spawned in this phase.

Each batch in dep order:
 - If child IDs already known (from prior step), write TodoWrite to track progress before spawning:
   ```
   TodoWrite([
     {content: "<child-id>: <title>", status: "pending"},
     ...
   ])
   ```
   (Skip pre-spawn TodoWrite if no children known yet.)
 - One `subagent_type="decomposer"` Agent per todo w/ `run_in_background=true`. Each runs decompose autonomously. Decompose agents append result via `todo_notes_append(parent_id, 'decompose_result: {"created_ids": [...]}')`.
 - Wait for batch (auto-notified on completion). Report failures.

After agents complete — collect created IDs (replaces `todo_tree` refresh):
1. `mcp__proj__todo_get(parent_id)` → read `.notes` → find last line matching `decompose_result:` → parse JSON → extract `created_ids` → store as `decomposed_ids`.
2. Fallback (no `decompose_result` found): `mcp__proj__todo_list(status="pending")` → filter by `group:<parent_id>` tag → store as `decomposed_ids`.

Update TodoWrite: mark each `decomposed_ids` entry as `in_progress` when its execute agent launches; mark `completed` when merged.

After decompose complete: (only if tasks_enabled) `TaskUpdate(task_B_id, status="completed")`. Failure → `TaskUpdate(task_B_id, status="failed")`.

**If `refine`** — after decompose, within iteration (if `quality_level == careful` AND `refine` in steps AND NOT `--no-interactive`):

fast → skip refine. careful → auto-enable. (No TaskCreate when skipped.)

(only if tasks_enabled) `TaskCreate(title="Phase B.75: Refine — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "B.75", "kind": "phase_task"})` → store as `task_B75_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_B75_id` to agents spawned in this phase.

Each todo: `skill: "proj:refine", args: "<id>"`.
 Apply → requirements/research updated, preflight re-runs automatically.
After refine complete: (only if tasks_enabled) `TaskUpdate(task_B75_id, status="completed")`.

**4.** Between-iteration prompt (skip if last iteration or `--no-interactive`)

**4a.** Next action prompt

```
### Iteration <i>/<N> complete — Next Action?

1. **Continue** — Start iteration <i+1>
2. **Skip to execute** — Prep has converged, proceed to execute
3. **Redefine** — Re-run interactive define on specific todos (enter IDs)
4. **Stop** — Exit workflow now (completed steps are saved)
```

Option 2 → skip remaining iterations, jump to step 5 (Execute).
Option 3 → prompt for todo IDs, interactive define on each, resume from decompose.

**5.** Execute (only if `has_execute`)

(only if tasks_enabled) `TaskCreate(title="Phase C: Execute — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C", "kind": "phase_task"})` → store as `task_C_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C_id` to agents spawned in this phase.

Refresh todo via `mcp__proj__todo_get`. Use `decomposed_ids` (from Phase B) if available; else `has_children = len(children) > 0`.

NOT `--no-interactive` → prompt:

```
### Prep complete — Execute?

1. **Proceed** — Run execute
2. **Redefine** — Re-run interactive define on specific todos (enter IDs)
3. **Stop** — Exit (prep saved)
```

No `decomposed_ids` + no children → exec parent directly.
Has `decomposed_ids` → invoke `skill: "proj:execute"` w/ `decomposed_ids` + same flags. (Fallback: use children from `todo_get` if `decomposed_ids` absent.)

**5a. Execute (single, no children):**

fast → display: "⚡ --fast mode. Auto-executing low-complexity. Tag-immune (security/breaking-change/migration) get full review."
 **Fast-mode safety guardrails**:
 - Minimal syntax check: verify modified files parseable (Python: `py_compile`, JS: basic syntax) even in fast mode.
 - Todos completed under --fast marked `fast_mode: true` via `todo_update`.
 - External sync (Todoist/Trello) deferred until workflow completes.
 - Security-tagged todos that got FULL REVIEW under --fast also get STANDARD verification before completion.

1. `mcp__proj__todo_check_executable` — manual-tagged → warn + stop.
2. `skill: "proj:execute", args: "<id>"`.

fast → after exec: display post-run summary w/ `git diff HEAD~N`.

After execute complete: (only if tasks_enabled) `TaskUpdate(task_C_id, status="completed")`. Failure → `TaskUpdate(task_C_id, status="failed")`.

**6.** Complete

```
Full workflow complete for todo <id>: <title>
Steps completed: <step1>, <step2>, ...
```

`mcp__proj__notes_append` w/ brief summary.

**7.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Run: {todo-id}")`.

Suggested next: `1. /proj:status`


## Prerequisites

- Active project loaded.
- Valid todo ID. Range/comma list dispatched to `/proj:run-batch`.

## Error Handling

- No todo ID → `Todo ID required.` + usage.
- Todo not found → err from `todo_get`.
- Invalid step name → err.
- Manual-tagged → skip w/ warn.
- Quality gate failure (define) → low-confidence display, Continue/Re-define/Stop.
- Verification failures (execute) → combined report, Fix/Proceed/Skip.
- Agent failures → report + log to `failed-agents.yaml`.
- Stale checkpoint → ask restart or use stale.

## Output

- Workflow progress per step, convergence assessments, verification report, satisfaction loop, completion.

Suggested next: `1. /proj:status`


## Preflight Agents Reference

> Adversarial review agents (A.5b, C0.5b) opt-in via `--with-adversarial-review`. Off by default.

Agent defs: `plugins/proj/agents/`. Each includes frontmatter (name, tools, model) + output schema. Load at runtime via `Read` when spawning.

When `adversarial_review_enabled`: 6 agents available. Spawn via named `subagent_type` w/ `run_in_background=true`, read-only tools, 90s timeouts, strict JSON schema. Timeouts/malformed JSON → WARNING (never BLOCKING).

**Phase A.5b** (define-phase, opt-in): `ambiguity-reviewer`, `completeness-reviewer`, `research-validator`
**Phase C0.5b** (pre-execute, opt-in): `file-path-verifier`, `spec-plan-alignment`, `impact-scanner`

All agents via parallel `Agent()` calls w/ `run_in_background=true`. Await all, parse JSON, aggregate into per-todo review table. Apply severity (BLOCKING → prompt, WARNING → show, INFO → show).

**Findings aggregation** — single table keyed by todo:

```
### Preflight Adversarial Review — todo <id>

| Severity | Agent | Finding | Evidence |
|----------|-------|---------|----------|
| BLOCKING | Completeness | Missing auth failure path | requirements.md L23 |
| WARNING  | Ambiguity | Undefined term "downstream" | requirements.md L12 |
```

Severity: BLOCKING → Fix/Continue/Stop (subject to `--no-interactive` demotion + fix-loop cap). WARNING/INFO → shown, non-blocking.

> Agent fallback, escalation protocols, tool availability: see `plugins/proj/skills/_shared/errors.md`
