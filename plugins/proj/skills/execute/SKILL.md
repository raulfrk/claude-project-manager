---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
allowed-tools: mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, mcp__proj__tracking_git_flush, mcp__proj__proj_session_context, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, mcp__proj__config_load, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, Task, TaskCreate, TaskList, Skill, EnterPlanMode, ExitPlanMode, AskUserQuestion
argument-hint: "[todo-id | range] [--no-verify] [--full-context] [--trust 0-3] [--resume] [--no-pipeline] [--fast|--careful] [--force-plan] [--batch-approve] [--worktree] [--no-worktree] [--max-parallel N] [--no-tasks] e.g. 1 or 2-4"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Execute todo(s): $ARGUMENTS

**Scope from $ARGUMENTS:**
- Parse `--no-verify` → skip verification (4a).
- Parse `--full-context` → include CLAUDE.md/NOTES.md in agent ctx.
- Parse `--trust N` (0-3). Unset → `mcp__proj__config_load` → `team_mode.trust_level` (default 1).
 - Trust 0 (supervised): per-todo approval, sequential.
 - Trust 1 (guided): sequential plan approval + bulk confirm before exec. Default Pattern A.
 - Trust 2 (autonomous): auto-approve plans, skip `ExitPlanMode` review.
 - Trust 3 (full-auto): skip Phase 1 entirely. Agents get ctx only, no plans.
- Parse `--resume` → resume from checkpoint. See Resume checkpoint below.
- Parse `--no-pipeline` → disable plan-while-executing pipeline (default: enabled).
- Parse `--fast`/`--careful` — mutually exclusive, last wins, default `--careful`.
- `--balanced` → ERROR: "balanced removed, use --careful"
- `--paranoid` → ERROR: "paranoid removed, use --careful --max-parallel 1"
- Parse `--force-plan` → force FULL REVIEW despite complexity.
- Parse `--batch-approve` → auto-approve all speculative plans.
- Parse `--worktree` / `--no-worktree` → enable/disable worktree isolation.
- `--no-tasks`: disable all TaskCreate calls. Use when you want clean output without task tracking.

Derive: `tasks_enabled = "--no-tasks" not in ARGUMENTS`
Derive: `worktree_enabled` from flags + config (`worktree_isolation` default).
Derive: `quality_level` from flags.

Worktree lifecycle (Phase 1.5/2.5/5 cleanup) orchestrated by `/proj:run`. Direct execute w/ `--worktree` → caller manages lifecycle. Standalone → use `/proj:run`.

**Quality Level Param Mapping:**

| Parameter | --fast | --careful |
|-----------|--------|-----------|
| gate_override | auto-execute (tag-immune) | smart-gate + full-review |
| batch_approve | auto | disabled |
| speculative_planning | enabled | disabled |
| verification_mode | skip | enhanced |
| max_parallel | 20 | 10 |
| satisfaction | skip (auto-complete) | per-todo |
| preflight | N/A (run-only) | N/A (run-only) |
| refine | N/A (run-only) | N/A (run-only) |
| pattern_detection | auto-approve | disabled |
| worktree | from config (worktree_isolation) | from config (worktree_isolation) |
| overlap_action | auto-proceed | auto-serialize |

Derive: `pipeline_enabled = not no_pipeline_flag`

**Flag compatibility:**
- `--fast --force-plan` → ERROR: "Cannot combine --fast with --force-plan."
- `--careful --batch-approve` → careful wins, batch approve disabled (warn).
- `--force-plan --batch-approve` → ERROR: "Cannot combine --force-plan with --batch-approve."
- `--no-verify --careful` → WARNING: "--no-verify overrides --careful's enhanced verification." Verification skipped.
- `--fast --steps refine` → ERROR (execute lacks refine).
- `--batch-approve --no-pipeline` → Allowed.
- `--careful --no-pipeline` → Allowed.
- `--fast --no-pipeline` → Redundant warning.
- `--force-plan --careful` → Redundant warning.
- `--no-verify --fast` → Redundant.
- `--force-plan --trust 3` → ERROR: "Cannot combine --force-plan with --trust 3."
- `--worktree --no-interactive` → Allowed. Auto-resolve conflicts only.
- `--fast --worktree` → Allowed: coexist.
- Empty → `mcp__proj__todo_list(status="in_progress")`; if none, `todo_list(status="ready")`. Show results, proceed w/ first (or ask if multiple).
- Single ID (e.g. `1`) → execute that todo
- Range (e.g. `2-4`) → execute those todos

**Single todo:**

> Worktree-isolated parallel exec → use `/proj:run <range> --from execute`. Direct execute runs on main.

**1.** `mcp__proj__todo_check_executable(todo_id)` — starts w/ "⚠️" → display, **stop**.
**2.** `mcp__proj__proj_get_todo_context(todo_id, include_parent=true)` — returns todo, reqs, research, parent.
**3.** `mcp__proj__proj_search_knowledge(query=<todo title>, scope=all)`. Snippets → "### Related Context" section. None → skip.

> Pre-execute preflight: via `/proj:run` only (Phase C0.5/C0.5b). Direct `/proj:execute` skips preflight. See `plugins/proj/skills/run/SKILL.md` Phase C0.5.

**3a. Smart gate scoring** (skip if quality_level == fast w/ auto-execute, or --force-plan):

 File-impact estimation (for dims 1-2 w/o speculative plan):
 Spawn `subagent_type="file-discovery"` read-only Task agent w/: todo ctx, reqs, research.
 Agent estimates: files modified/created, dirs involved.
 Wait. Use results for dims 1 (file count), 2 (dir spread).
 Agent fails → score dims 1-2 as 0.

 Complexity score (0-14), 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

 Eval order: Tag overrides FIRST → complexity score → critical-path guard as FINAL FLOOR.

 Tag overrides (pre-score): `auto-execute` → force AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → force FULL REVIEW (even --fast, tag-immune). Most restrictive wins.

 Critical-path guard (FINAL FLOOR): planned file matches `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json` → min LIGHT REVIEW even if score 0-3.

 Gate routing:
 - AUTO-EXECUTE (0-3): git tag `pre-auto-execute-{todo_id}`. Skip plan, exec w/ ctx.
 - LIGHT REVIEW (4-7): 1-line summary + `Proceed? [Y/n]` (default yes).
 - FULL REVIEW (8-14): Full `EnterPlanMode`/`ExitPlanMode`.

 `--force-plan` → always FULL REVIEW.

**3b. Plan creation** (respects trust, skipped if AUTO-EXECUTE):
(only if tasks_enabled) `TaskCreate(title="Phase C1: Plan — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C1", "kind": "phase_task"})` → store as `task_C1_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C1_id` to agents spawned in this phase.
 - `mcp__proj__proj_decision_log(action="search", decision=<todo title>, project_name=<project>)`. Results → "### Prior Decisions" in plan ctx.
 - Trust 0-2: `EnterPlanMode`. Read ctx (reqs, research, notes, Related Context). Explore source. Plan: files to modify/create, key changes, impl order, testing.
 - Trust 0-1: `ExitPlanMode` for user review. Approve before proceeding.
 - Trust 2: Skip `ExitPlanMode`. Display: `Plan auto-approved (trust 2): <1-line summary>`.
 - After approval (trust 0-2): `proj_decision_log(action="add", decision=<approach summary>, tags="plan", todo_id)`.
 - Trust 3: Skip 3b entirely → step 4 w/ ctx only.

After plan approved/skipped: (only if tasks_enabled) `TaskUpdate(task_C1_id, status="completed")`.

(only if tasks_enabled) `TaskCreate(title="Phase C2: Execute — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C2", "kind": "phase_task"})` → store as `task_C2_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C2_id` to agents spawned in this phase.

Create per-todo Task (only if tasks_enabled):
```
TaskCreate(
  title="Implement todo {id} — {title}",
  description="{notes[:300] if notes else ''}",
  activeForm="Implementing {title}",
  metadata={
    "proj_todo_id": "{id}",
    "phase": "C2",
    "kind": "todo_task",
    "parent_task_id": "<task_C2_id>",
    "proj": {
      "id": "{id}",
      "priority": "{priority}",
      "tags": [...],
      "parent_id": "{parent or null}"
    }
  }
) → store as `todo_task_id`
TaskUpdate(status="in_progress")
```
Pass `todo_task_id` to implementer agent prompt:
```
task_id: {todo_task_id}  ← agent uses for TaskUpdate + subtask creation
```

**4.** `mcp__proj__todo_update(status="in_progress")`. Review ctx, implement. Non-empty `notes` field → additional impl ctx (constraints/design decisions).

After impl complete: (only if tasks_enabled) `TaskUpdate(task_C2_id, status="completed")`. Failure → `TaskUpdate(task_C2_id, status="failed")`.

**4a. Verification** (skip if `--no-verify`; no TaskCreate when skipped):

(only if tasks_enabled) `TaskCreate(title="Phase C2a: Verification — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C2a", "kind": "phase_task"})` → store as `task_C2a_id` → `TaskUpdate(status="in_progress")`

 Mode by quality_level:
 - `skip` (--fast): Skip entirely.
 - `enhanced` (--careful): automated checks + spec validation + diff review + manual test checklist from acceptance criteria.

 Three check categories; missing prereqs → skip gracefully w/ note.

 **A. Automated checks (Bash)**
 Detect test/lint tooling in content dir:
 - Tests: `pyproject.toml` w/ `[tool.pytest]` → `uv run pytest --tb=short -q`; `package.json` w/ `"test"` script → `npm test`; else skip.
 - Lint: `pyproject.toml` w/ `[tool.ruff]` → `uv run ruff check` on modified files; `.eslintrc*` → `npx eslint` on modified files; else skip.
 Record: pass/fail, summary.

 **B. Spec validation**
 1. `mcp__proj__content_get_requirements(todo_id)`. None → skip.
 2. Extract acceptance criteria (`- [ ]`/`- [x]` lines).
 3. `git diff HEAD~1` for impl diff.
 4. Each criterion → met / unmet / unverifiable.

 **C. Diff review**
 1. From plan (3b), extract "Files to modify/create". No plan → skip.
 2. `git diff --name-only HEAD~1` for modified files.
 3. Compare: planned but not touched / unplanned modification / matches plan.

 **Report:**
   ```
   ### Verification Report — Todo <id>

   **Automated checks**: PASS (14 tests passed) | FAIL (2 tests failed: test_x, test_y)
   **Spec validation**: 4/4 criteria met | 3/4 criteria met (1 unverifiable)
   **Diff review**: Plan matches | 1 planned file not touched, 1 unplanned file modified
   ```

 **Persist** — Write report (w/ timestamp) to `todos/<id>/verification-report.md` in tracking dir via `mcp__proj__notes_append` or direct write. Overwrite prev report.

 **Prompt:**
 > Fix these issues? (1) Fix (2) Proceed (3) Skip
 - Fix: spawn `subagent_type="verification-fixer"` Task agent w/: verification report, todo ctx + reqs + research + parent ctx (`proj_get_todo_context`), approved plan, fix instructions. After completion, re-run verification (max 2 retries). Still failing → display updated report, re-prompt.
 - Proceed: continue to satisfaction (step 5) despite failures.
 - Skip: skip remaining verification, go to step 5.

 All pass → display report, → step 5 w/o prompt.

After verification: (only if tasks_enabled) `TaskUpdate(task_C2a_id, status="completed")`. Failure → `TaskUpdate(task_C2a_id, status="failed")`.

(only if tasks_enabled) `TaskCreate(title="Phase SAT: Satisfaction — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "SAT", "kind": "phase_task"})` → store as `task_SAT_id` → `TaskUpdate(status="in_progress")`

**5. Satisfaction loop:**
 a. Ask: "Are you satisfied with outcome of todo <id>?"
 1. Satisfied → step 5d
 2. Not satisfied → describe fixes needed
 3. Redefine → refine reqs, re-run workflow
 b. Not satisfied:
 - Ask what's missing, fix in cur scope
 - `proj_decision_log(action="add", decision=<feedback>, tags="correction,quality", context="execute:satisfaction:{todo_id}", todo_id)`
 - Re-ask (→ 5a)
 c. Redefine:
 - `Skill("proj:define", args="<id>")` (existing reqs/research kept — non-destructive)
 - After define: if decomposable → `Skill("proj:decompose", args="<id>")`
 - `Skill("proj:execute", args="<id>")`
 - Satisfaction-driven recursive run: enforce `--no-pipeline --careful --no-worktree`. Max recursion depth: 2.
 - Re-ask on orig todo (→ 5a)
 d. `mcp__proj__todo_complete`
 - Update CLAUDE.md if relevant: `mcp__proj__claudemd_write`
 - Append progress note: `mcp__proj__notes_append`
 After satisfaction: (only if tasks_enabled) `TaskUpdate(task_SAT_id, status="completed")`.

**Range w/ independent todos (no blocked_by between them):**

**Mode selection:** 3+ independent non-manual todos → **Pattern A**. Otherwise → **Pattern B**.


**Pattern A — Parallel exec (independent todos):**

**Phase C0 — Speculative planning** (if quality_level != careful AND trust != 0 AND trust != 3; no TaskCreate when skipped):

(only if tasks_enabled) `TaskCreate(title="Phase C0: Speculative Planning — batch", metadata={"phase": "C0", "kind": "phase_task"})` → store as `task_C0_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C0_id` to agents spawned in this phase.

Each todo → `subagent_type="speculative-planner"` read-only Agent w/ `run_in_background=true`:
- Output: JSON `{prose: string, actions: [{type: "create"|"modify"|"delete"|"test", file: string}]}`
- PLAN_ESCALATION: agents CANNOT call EnterPlanMode/ExitPlanMode. Agent returns `{status: "plan_escalation", plan: "<plan>"}`. Parent reads result → EnterPlanMode → ExitPlanMode → user approves/rejects → spawns new Agent w/ resolution ctx if rejected.

Agent fails → exclude todo, fall back to sequential planning.
Store in `speculative_plans[todo_id]`.

`--batch-approve` → auto-approve all. Display: `Batch-approved N speculative plans.`

Wait for all agents (auto-notified on completion).
After speculative planning: (only if tasks_enabled) `TaskUpdate(task_C0_id, status="completed")`. Failure → `TaskUpdate(task_C0_id, status="failed")`.

**Phase 1 — Plan (sequential, main conversation):**

Skip if trust 3 → Phase 2 w/ ctx only.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

(only if tasks_enabled) `TaskCreate(title="Phase C1: Plan — batch", metadata={"phase": "C1", "kind": "phase_task"})` → store as `task_C1_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C1_id` to agents spawned in this phase.

Each todo in range:
**1.** `todo_check_executable` — "⚠️" → skip: `⚠️ Todo <id> [manual] — skipped execute`.
**2.** `proj_get_todo_context(todo_id, include_parent=true)`.
**3.** `proj_search_knowledge(query=<todo title>, scope=all)`. Snippets → "### Related Context". None → skip.
**3a. Smart gate scoring** (skip if fast+auto-execute or --force-plan):

 Complexity score (0-14), 7 dimensions:

   | Dimension | 0 points | 1 point | 2 points |
   |-----------|----------|---------|----------|
   | File count (from plan) | 1 file | 2-4 files | 5+ files |
   | Directory spread | 1 dir | 2-3 dirs | 4+ dirs |
   | Requirements quality | detailed | basic | none/vague |
   | Research quality | detailed | basic | none |
   | Risk tags | none | general risk | security/breaking/migration |
   | Children count | 0 (leaf) | 1-3 | 4+ |
   | Blocked-by deps | 0 | 1 | 2+ |

 Eval order: Tag overrides FIRST → score → critical-path guard FINAL FLOOR.

 Tag overrides: `auto-execute` → AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → FULL REVIEW (tag-immune, even --fast). Most restrictive wins.

 Critical-path guard: planned file matches `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json` → min LIGHT REVIEW.

 Gate: AUTO-EXECUTE (0-3) → git tag, skip plan. LIGHT REVIEW (4-7) → 1-line + `Proceed? [Y/n]`. FULL REVIEW (8-14) → `EnterPlanMode`/`ExitPlanMode`. `--force-plan` → always FULL.

**3b.** `proj_decision_log(action="search", decision=<todo title>, project_name)`. Results → "### Prior Decisions".
`EnterPlanMode`. Plan: files, changes, order, testing. Include Related Context + Prior Decisions. (Skip if AUTO-EXECUTE.)
**4.** Plan approval by trust:
 - Trust 0: `ExitPlanMode` → user approves before next plan.
 - Trust 1: `ExitPlanMode` → user approves, next todo. After all: bulk approval summary.
 - Trust 2: Skip `ExitPlanMode`. Display: `Plan auto-approved (trust 2): <summary>`.
**4a.** After approval: `proj_decision_log(action="add", decision=<approach>, tags="plan", todo_id)`.
**5.** Store in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust != 3:
 `len(executing_agents) >= max_parallel` → wait for one to complete.
 Spawn background `subagent_type="implementer"` Agent w/ `run_in_background=true`: todo, reqs, research, parent ctx, plan. Instruction: implement plan, do NOT call `todo_complete`. Store in `executing_agents[todo_id]`.

After all plans (trust 0-1): bulk approval summary w/ all IDs + plan summaries.

After plan phase: (only if tasks_enabled) `TaskUpdate(task_C1_id, status="completed")`.

**Cross-review** (careful AND N > 1):
One `subagent_type="drift-reviewer"` Agent per plan w/ `run_in_background=true`. Agent i reviews plan (i+1) % N. N=1 → skip. Each agent gets: plan + reqs + reviewer's own ctx. Output: risk rating (LOW/MEDIUM/HIGH) + concerns. HIGH → flag user. Wait for all agents.

**File-Overlap Detection** (before Phase 2, skip if trust 3):
1. Extract "Files to modify/create" from each plan.
2. Build overlap matrix: check file list intersections per pair.
3. Overlaps found:

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

4. Serialize → remove conflicting todos from parallel batch, add sequential batch at end.
5. Proceed → continue.
6. Cancel → stop: "Execution cancelled. Plans are saved."
7. No overlaps → skip.

**Resume checkpoint** (`--resume`):
1. Find most recent `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. Found + fresh (< 24h):
 - Display: `Resuming from batch {batch_index}/{total_batches} — {len(completed_todos)} todos already completed`.
 - Use stored `approved_plans`. Skip to `batch_index` in Phase 2.
3. Stale (> 24h) or refs nonexistent todos:
 - Display: `Checkpoint is stale (created {timestamp}). Restart from the beginning? (1) Restart (2) Use anyway`.
 - Restart → ignore, start Phase 1. Use anyway → proceed w/ stale data.
4. Not found: `No checkpoint found — starting fresh`.

**Phase 2 — Execute (parallel agents):**

(only if tasks_enabled) `TaskCreate(title="Phase C2: Execute — batch", metadata={"phase": "C2", "kind": "phase_task"})` → store as `task_C2_id` → `TaskUpdate(status="in_progress")`
Pass `parent_task_id=task_C2_id` to agents spawned in this phase.

Enforce max_parallel from quality_level mapping.

**1a. Task Mapping** (one-way — tasks mirror todos for coordination, only if tasks_enabled):
 Each todo:
 - `TaskCreate(title="Implement todo {id} — {title}", description="Implement todo {id} — {title}", metadata={"proj_todo_id": "{todo.id}", "phase": "C2", "kind": "todo_task", "parent_task_id": "<task_C2_id>", "proj": {"id": "{todo.id}", "priority": "{todo.priority}", "tags": [...], "parent_id": "{todo.parent or null}"}})`
 - `blocked_by` rels → `addBlockedBy` w/ Task IDs from prev `TaskCreate`.
 One-way: Task completion ≠ proj todo completion. Satisfaction loop handles that.

**2.** Single batch of independent todos:
 IF `pipeline_enabled`:
 Wait for all `executing_agents`. Report failures.
 All failed → "All N agents in batch failed. (1) Retry (2) Skip (3) Stop." Handle choice; skip satisfaction.
 ELSE:
 - Display: `Executing batch: todos <id1>, <id2>, ...`
 - N roles per target → N individual agents.
 - Spawn one `subagent_type="implementer"` Agent per todo w/ `run_in_background=true`. Each gets: approved plan (or ctx if trust 3) + reqs + research + parent ctx. `--full-context` → also CLAUDE.md + NOTES.md.
 - `worktree_enabled` + todo has `worktree_path`: include `worktree_path`, `worktree_branch` in ctx. Instruction: exec in worktree dir. Prefix commits `[todo-{id}]`.
 - Pattern group todo → include: "Part of pattern group (N similar). Common pattern: <normalized>. Implement consistently."
 - Agents exec plan as-is. Do NOT call `todo_complete`. Issue not in plan → return `{status: "escalation_needed", issue: "<description>"}`. Do NOT improvise. Parent reads result → `AskUserQuestion` → spawns new Agent w/ resolution ctx.
 - Wait for all agents (auto-notified on completion). Report failures.
 - Write checkpoint to `<tracking_dir>/<project>/.team-state/checkpoint.yaml`:
     ```yaml
     batch_index: 1
     total_batches: 1
     completed_todos: [<completed todo IDs>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
**3.** Failed → log to `tracking/{project}/.team-state/failed-agents.yaml`.
After execute: (only if tasks_enabled) `TaskUpdate(task_C2_id, status="completed")`. Failure → `TaskUpdate(task_C2_id, status="failed")`.

**Phase 2a — Verification** (skip if `--no-verify`; no TaskCreate when skipped):

(only if tasks_enabled) `TaskCreate(title="Phase C2a: Verification — batch", metadata={"phase": "C2a", "kind": "phase_task"})` → store as `task_C2a_id` → `TaskUpdate(status="in_progress")`

Verify each completed todo sequentially. Run checks from 4a (Automated, Spec, Diff). Combined batch report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist each to `todos/<id>/verification-report.md`.

Summary line (e.g. "2 passed, 1 failed"):
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- Fix: 2+ failed → one `subagent_type="verification-fixer"` Agent per failed todo w/ `run_in_background=true`. Wait for all. 1 failed → single agent. Re-verify (max 2 retries). Still failing → display, re-prompt.
- Proceed: continue to Phase 3.
- Skip: go to Phase 3.

All pass → display, proceed w/o prompt.
After verification: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

**Phase 3 — Satisfaction (sequential, main conversation):**

`TaskCreate(title="Phase SAT: Satisfaction — batch", metadata={"phase": "SAT"})` → `TaskUpdate(status="in_progress")`

Each completed todo (excl manual-skipped + failed):
**1.** Review agent output.
**2.** Satisfaction loop (5a-5d).
Clear `executing_agents = {}`. Report summary incl skipped/failed.
After satisfaction: `TaskUpdate(status="completed")`.


**Pattern B — Sequential exec (independent, fallback):**

Phase 1 — Plan (sequential, main conversation):

Skip if trust 3 → Phase 2 w/ ctx only.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

`TaskCreate(title="Phase C1: Plan — batch (fallback)", metadata={"phase": "C1"})` → `TaskUpdate(status="in_progress")`

Each todo:
**1.** `todo_check_executable` — "⚠️" → skip.
**2.** `proj_get_todo_context(todo_id, include_parent=true)`.
**3.** `proj_search_knowledge(query=<title>, scope=all)`. Snippets → "### Related Context".
**3a. Smart gate scoring** (skip if fast+auto-execute or --force-plan):

 Complexity score (0-14), same 7-dimension table.
 Same eval order: Tag overrides → score → critical-path guard.
 Same tag overrides + critical-path guard rules.
 Same gate routing: AUTO-EXECUTE (0-3) / LIGHT (4-7) / FULL (8-14). `--force-plan` → FULL.

**3b.** `proj_decision_log(action="search", ...)`. Results → "### Prior Decisions".
`EnterPlanMode`. Plan w/ Related Context + Prior Decisions. (Skip if AUTO-EXECUTE.)
**4.** Plan approval by trust: Trust 0 → approve before next. Trust 1 → approve, next. Trust 2 → auto-approve.
**4a.** After approval: `proj_decision_log(action="add", ..., tags="plan", todo_id)`.
**5.** Store in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust != 3:
 `len(executing_agents) >= max_parallel` → wait.
 Spawn background `subagent_type="implementer"` Agent w/ `run_in_background=true`: todo, reqs, research, parent, plan. Do NOT `todo_complete`. Store in `executing_agents[todo_id]`.

After plan phase: `TaskUpdate(status="completed")`.

**Cross-review** (careful AND N > 1):
One `subagent_type="drift-reviewer"` Agent per plan w/ `run_in_background=true`. Agent i reviews plan (i+1) % N. N=1 → skip. Output: risk (LOW/MEDIUM/HIGH) + concerns. HIGH → flag user. Wait for all agents.

Phase 2 — Execute (Task agents):

`TaskCreate(title="Phase C2: Execute — batch (fallback)", metadata={"phase": "C2"})` → `TaskUpdate(status="in_progress")`

Enforce max_parallel.

IF `pipeline_enabled`:
 Wait for all `executing_agents`. Report failures.
 All failed → "All N failed. (1) Retry (2) Skip (3) Stop."
ELSE:
After plans approved (or skipped trust 3), spawn one `subagent_type="implementer"` Agent per todo (excl manual-skipped) w/ `run_in_background=true`.
Each gets: todo, reqs, research, parent ctx, plan (or ctx if trust 3).
`worktree_enabled` + `worktree_path` → exec in worktree, prefix commits `[todo-{id}]`.
Pattern group → include pattern info.
Agents impl per plan. Do NOT `todo_complete`.
Wait for all agents (auto-notified on completion).
After execute: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

Phase 2a — Verification (skip if `--no-verify`; no TaskCreate when skipped):

`TaskCreate(title="Phase C2a: Verification — batch (fallback)", metadata={"phase": "C2a"})` → `TaskUpdate(status="in_progress")`

Verify each sequentially. Run checks from 4a. Combined report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist to `todos/<id>/verification-report.md`.

Summary + prompt:
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- Fix: 2+ → one `subagent_type="verification-fixer"` Agent per failed todo w/ `run_in_background=true`. Wait for all. 1 → single agent. Re-verify (max 2 retries).
- Proceed / Skip: same as Pattern A.

All pass → proceed w/o prompt.
After verification: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

Phase 3 — Satisfaction (sequential):

`TaskCreate(title="Phase SAT: Satisfaction — batch (fallback)", metadata={"phase": "SAT"})` → `TaskUpdate(status="in_progress")`

Each completed todo (excl manual-skipped):
**1.** Review agent output.
**2.** Satisfaction loop (5a-5d).
Clear `executing_agents = {}`. Report summary.
After satisfaction: `TaskUpdate(status="completed")`.

**Range w/ dependencies:**

**Mode selection:** 3+ non-manual todos → **Pattern A**. Otherwise → **Pattern B**.


**Pattern A — Parallel exec (w/ deps):**

**Phase C0 — Speculative planning** (quality_level != careful AND trust != 0 AND trust != 3; no TaskCreate when skipped):

`TaskCreate(title="Phase C0: Speculative Planning — deps batch", metadata={"phase": "C0"})` → `TaskUpdate(status="in_progress")`

Each todo → `subagent_type="speculative-planner"` read-only Agent w/ `run_in_background=true`:
- Output: JSON plan `{prose, actions: [{type, file}]}`
- PLAN_ESCALATION: agents CANNOT call EnterPlanMode/ExitPlanMode. Agent returns `{status: "plan_escalation", plan: "<plan>"}`. Parent reads result → EnterPlanMode → ExitPlanMode → user approves/rejects → spawns new Agent w/ resolution ctx if rejected.
Fails → exclude, fall back to sequential. Store in `speculative_plans[todo_id]`.
`--batch-approve` → auto-approve. Wait for all agents.
After speculative planning: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

**Phase 1 — Plan (sequential, dependency order):**

Skip if trust 3 → Phase 2 w/ ctx only.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

`TaskCreate(title="Phase C1: Plan — deps batch", metadata={"phase": "C1"})` → `TaskUpdate(status="in_progress")`

Group todos into dependency batches (topo order). Within-batch = parallel, batches = sequential. Each todo:
**1.** `todo_check_executable` — "⚠️" → skip.
**2.** `proj_get_todo_context(todo_id, include_parent=true)`.
**3.** `proj_search_knowledge(query=<title>, scope=all)`. Snippets → "### Related Context".
**3a. Smart gate scoring** (skip if fast+auto-execute or --force-plan):

 Same 7-dimension table + eval order + tag overrides + critical-path guard + gate routing.

**3b.** `proj_decision_log(action="search", ...)` → "### Prior Decisions".
`EnterPlanMode`. Plan w/ Related Context + Prior Decisions. (Skip if AUTO-EXECUTE.)
**4.** Plan approval by trust: Trust 0 → approve before next. Trust 1 → approve, next; after all → bulk summary. Trust 2 → auto-approve.
**4a.** `proj_decision_log(action="add", ..., tags="plan", todo_id)`.
**5.** Store in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust != 3:
 `len(executing_agents) >= max_parallel` → wait.
 Spawn background `subagent_type="implementer"` Agent w/ `run_in_background=true`. Store in `executing_agents[todo_id]`.

After all plans (trust 0-1): bulk approval summary w/ IDs, batch assignments, summaries.
After plan phase: `TaskUpdate(status="completed")`.

**Cross-review** (careful AND N > 1):
One `subagent_type="drift-reviewer"` Agent per plan w/ `run_in_background=true`. Agent i reviews (i+1) % N. N=1 → skip. Output: risk + concerns. HIGH → flag user. Wait for all agents.

**File-Overlap Detection** (before Phase 2, skip if trust 3):
1. Extract file lists from plans. Deps: check overlaps **within each batch** (cross-batch OK — sequential).
2. Build overlap matrix per pair within same batch.
3. Overlaps:

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

4. Serialize → move conflicting to new sequential batch. 5. Proceed. 6. Cancel: "Execution cancelled. Plans are saved." 7. None → skip.

**Resume checkpoint** (`--resume`):
Same rules as independent Pattern above.

**Phase 2 — Execute (batches sequential, within-batch parallel w/ Team):**

`TaskCreate(title="Phase C2: Execute — deps batch", metadata={"phase": "C2"})` → `TaskUpdate(status="in_progress")`

Enforce max_parallel.

**1a. Task Mapping** (one-way):
 Each todo across all batches:
 - `TaskCreate(title, description="Implement todo {id} — {title}", metadata={"proj_todo_id": "{todo.id}"})`
 - `blocked_by` rels (same or diff batch) → `addBlockedBy`.
 One-way: satisfaction loop handles completion.

**2.** Each batch in dep order:
 IF `pipeline_enabled`:
 Wait for `executing_agents` in batch. Report failures.
 All failed → "(1) Retry (2) Skip (3) Stop."
 ELSE:
 - Display: `Executing batch <N>/<total>: todos <ids>`
 - N roles → N agents.
 - Spawn one `subagent_type="implementer"` Agent per todo w/ `run_in_background=true`. Each gets: plan (or ctx trust 3) + reqs + research + parent. `--full-context` → CLAUDE.md + NOTES.md.
 - `worktree_enabled` + `worktree_path` → exec in worktree, prefix commits `[todo-{id}]`.
 - Pattern group → include pattern info.
 - Agents exec as-is. No `todo_complete`. Plan gap → return `{status: "escalation_needed", issue: "<description>"}`. Parent reads result → `AskUserQuestion` → spawns new Agent w/ resolution ctx.
 - Wait for batch before next (auto-notified on completion). Report failures.
 - Write checkpoint:
     ```yaml
     batch_index: <current batch number>
     total_batches: <total>
     completed_todos: [<all completed todo IDs so far>]
     approved_plans:
       <todo_id>: "<plan text>"
     ```
**3.** Failed → log to `tracking/{project}/.team-state/failed-agents.yaml`.
After execute: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

**Phase 2a — Verification** (skip if `--no-verify`; no TaskCreate when skipped):

`TaskCreate(title="Phase C2a: Verification — deps batch", metadata={"phase": "C2a"})` → `TaskUpdate(status="in_progress")`

Verify each sequentially. Run checks from 4a. Combined report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist to `todos/<id>/verification-report.md`.

Summary + prompt:
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- Fix: 2+ → one `subagent_type="verification-fixer"` Agent per failed todo w/ `run_in_background=true`. Wait for all. 1 → single agent. Re-verify (max 2 retries).
- Proceed / Skip: same.

All pass → proceed w/o prompt.
After verification: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

**Phase 3 — Satisfaction (sequential):**

`TaskCreate(title="Phase SAT: Satisfaction — deps batch", metadata={"phase": "SAT"})` → `TaskUpdate(status="in_progress")`

Each completed todo (excl manual-skipped + failed): satisfaction loop (5a-5d) before `todo_complete`.
Clear `executing_agents = {}`. Report summary.
After satisfaction: `TaskUpdate(status="completed")`.


**Pattern B — Sequential exec (w/ deps, fallback):**

Phase 1 — Plan (sequential, dep order):

Skip if trust 3 → Phase 2 w/ ctx only.

Init `approved_plans = {}`, `executing_agents = {}`, `manual_skipped_ids = []`.

`TaskCreate(title="Phase C1: Plan — deps (fallback)", metadata={"phase": "C1"})` → `TaskUpdate(status="in_progress")`

Topo order (respect blocked_by). Each todo:
**1.** `todo_check_executable` — "⚠️" → skip.
**2.** `proj_get_todo_context(todo_id, include_parent=true)`.
**3.** `proj_search_knowledge(query=<title>, scope=all)`. Snippets → "### Related Context".
**3a. Smart gate scoring** (skip if fast+auto-execute or --force-plan):

 Same 7-dimension table + eval order + tag overrides + critical-path guard + gate routing.

**3b.** `proj_decision_log(action="search", ...)` → "### Prior Decisions".
`EnterPlanMode`. Plan w/ Related Context + Prior Decisions. (Skip if AUTO-EXECUTE.)
**4.** Plan approval by trust: Trust 0 → approve before next. Trust 1 → approve, next. Trust 2 → auto-approve.
**4a.** `proj_decision_log(action="add", ..., tags="plan", todo_id)`.
**5.** Store in `approved_plans[todo_id]`.
**6.** IF `pipeline_enabled` AND trust != 3:
 `len(executing_agents) >= max_parallel` → wait.
 Spawn background `subagent_type="implementer"` Agent w/ `run_in_background=true`. Store in `executing_agents[todo_id]`.

After plan phase: `TaskUpdate(status="completed")`.

**Cross-review** (careful AND N > 1):
One `subagent_type="drift-reviewer"` Agent per plan w/ `run_in_background=true`. Agent i reviews (i+1) % N. N=1 → skip. Output: risk + concerns. HIGH → flag user. Wait for all agents.

Phase 2 — Execute (sequential, dep order):

`TaskCreate(title="Phase C2: Execute — deps (fallback)", metadata={"phase": "C2"})` → `TaskUpdate(status="in_progress")`

Enforce max_parallel.

IF `pipeline_enabled`:
 Wait for all `executing_agents`. Report failures.
 All failed → "(1) Retry (2) Skip (3) Stop."
ELSE:
Exec each per plan (or ctx trust 3), one at time (respect blocked_by). Mark in_progress, impl.
`worktree_enabled` + `worktree_path` → exec in worktree, prefix commits `[todo-{id}]`.
Pattern group → include pattern info.

After execute: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

Phase 2a — Verification (skip if `--no-verify`; no TaskCreate when skipped):

`TaskCreate(title="Phase C2a: Verification — deps (fallback)", metadata={"phase": "C2a"})` → `TaskUpdate(status="in_progress")`

Verify each sequentially. Combined report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
| 2.3  | PASS (8 tests)  | 4/4 met | 1 extra file | WARN |
```

Persist to `todos/<id>/verification-report.md`.

Summary + prompt:
> Fix failed todos? (1) Fix (2) Proceed (3) Skip
- Fix: 2+ → one `subagent_type="verification-fixer"` Agent per failed todo w/ `run_in_background=true`. Wait for all. 1 → single agent. Re-verify (max 2 retries).
- Proceed / Skip: same.

All pass → proceed w/o prompt.
After verification: `TaskUpdate(status="completed")`. Failure → `TaskUpdate(status="failed")`.

Phase 3 — Satisfaction (sequential, dep order):

`TaskCreate(title="Phase SAT: Satisfaction — deps (fallback)", metadata={"phase": "SAT"})` → `TaskUpdate(status="in_progress")`

Each completed todo: satisfaction loop (5a-5d). Batch completion: collect satisfied IDs → 2+ → single `mcp__proj__todo_batch_complete`. 1 → `mcp__proj__todo_complete`.
Clear `executing_agents = {}`.
After satisfaction: `TaskUpdate(status="completed")`.

Root todo exec does NOT auto-recurse into children. Specify child IDs explicitly.

**6.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Execute: {todo-id}")`.

## Agent Escalation (execution agents)

Spawned agents return structured output on issues requiring user input:

1. Agent detects need for user input
2. Agent returns `{status: "escalation_needed", issue: "<description>", options: ["opt1", "opt2"]}`
3. Parent reads Agent result → calls `AskUserQuestion` w/ agent's issue + options
4. User answers
5. Parent spawns new Agent w/ resolution ctx + user's answer

**When to escalate:**
- **Plan gaps** — impl discovers work outside approved plan (new file needed, unexpected dep, missing API)
- **Scope clarifications** — requirements ambiguous for specific impl decision
- **Architectural blockers** — existing code structure conflicts w/ planned approach, multiple valid resolutions
- **Edge cases** — discovered during impl, not covered by requirements, affects correctness

Agents must NOT improvise, guess, or auto-resolve when user input needed. Return escalation output immediately.

## Prerequisites

- Active project loaded.
- Valid todo ID/range (or in-progress/ready todo exists).

## Err Handling

- No active project → err, stop.
- Manual-tagged → warning from `todo_check_executable`, stop.
- Blocked → err, stop.
- Verification failures → combined report + Fix/Proceed/Skip.
- Agent failures → report per todo. Log to `failed-agents.yaml`.
- Stale checkpoint → ask restart or use stale.

### Worktree Failure Handling

| Failure | During | Action |
|---------|--------|--------|
| `wt_create` fails | Setup (Phase 1.5) | Fall back to main for that todo, warn |
| Agent crashes in worktree | Execute (Phase 2) | Leave worktree intact for debugging, report in summary |
| Clean merge | Merge (Phase 2.5) | Commit, continue |
| Auto-resolvable conflict | Merge (Phase 2.5) | Apply per-file ours/theirs strategy, commit |
| Non-auto-resolvable conflict | Merge (Phase 2.5) | Prompt user: manual resolve or abort to serial queue |
| Post-merge test failure (1 merge) | Merge (Phase 2.5) | Revert merge, re-execute on main |
| Post-merge test failure (N merges) | Merge (Phase 2.5) | Git bisect to find breaking merge, offer revert |

## Output

- Single todo: impl result, verification report (if enabled), satisfaction outcome, completion confirm.
- Range/batch: per-batch progress, combined verification table, satisfaction per completed todo, overall summary.

## Agent Fallback

If `subagent_type="<name>"` not found (agent .md file missing/renamed):
1. Log warning via `notes_append`: "Agent definition '<name>' not found, falling back to general-purpose"
2. Use `Agent(subagent_type="general-purpose", prompt=<inline_fallback>)` w/ minimal role desc
3. Fallback prompts (one-line per agent):
   - `speculative-planner`: "Read todo ctx + reqs + research. Draft impl plan as JSON {prose, actions: [{type, file}]}. Read-only — no writes."
   - `drift-reviewer`: "Review plan against reqs. Flag scope drift, missing criteria, unplanned changes. Return risk rating (LOW/MEDIUM/HIGH) + concerns."
   - `implementer`: "Implement approved plan. Read requirements + research, follow plan steps, write code + tests, commit w/ [todo-{id}] prefix."
   - `verification-fixer`: "Fix verification failures. Read report + todo ctx + reqs + plan. Apply targeted fixes, re-run tests."

Suggested next: `1. /proj:save` -- save session, reconcile git | `2. /proj:status` -- updated overview
