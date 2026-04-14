---
name: execute
description: Execute one or more todos. Reads requirements and research before implementing. For independent todos in a range, spawns parallel agents. Use when asked "execute 1", "work on 2-4", or "implement the active task".
allowed-tools: mcp__proj__todo_list, mcp__proj__todo_check_executable, mcp__proj__proj_get_todo_context, mcp__proj__todo_update, mcp__proj__todo_complete, mcp__proj__claudemd_write, mcp__proj__notes_append, mcp__proj__tracking_git_flush, mcp__proj__proj_session_context, mcp__proj__proj_search_knowledge, mcp__proj__proj_decision_log, mcp__proj__config_load, mcp__proj__todo_notes_patch, mcp__proj__todo_notes_append, mcp__worktree__wt_create, mcp__worktree__wt_lock, mcp__worktree__wt_unlock, mcp__worktree__wt_remove, mcp__worktree__wt_prune, mcp__worktree__wt_list_repos, mcp__plugin_sandbox_sandbox__sandbox_add_allow, mcp__plugin_sandbox_sandbox__sandbox_cleanup_stale, Task, TaskCreate, TaskList, Skill, EnterPlanMode, ExitPlanMode, AskUserQuestion
argument-hint: "[todo-id | range] [--no-verify] [--resume] [--fast|--careful] [--max-parallel N] [--no-tasks] e.g. 1 or 2-4"
---


> **Output**: caveman ultra. Drop articles, abbrev, fragments, arrows. Code/tables unchanged.

Execute todo(s): $ARGUMENTS

> Flags + quality param mapping + flag compat checks: see `plugins/proj/skills/_shared/flags.md`

**Scope from $ARGUMENTS:**
- Parse `--no-verify` → skip verification (4a).
- Parse `--resume` → resume from checkpoint.
- Parse `--fast`/`--careful` — mutually exclusive, last wins, default `--careful`.
- `--balanced` → ERROR: "balanced removed, use --careful"
- `--paranoid` → ERROR: "paranoid removed, use --careful --max-parallel 1"
- `--no-tasks`: disable all TaskCreate calls.

Derive: `tasks_enabled = "--no-tasks" not in ARGUMENTS`
Derive: `worktree_enabled` from config (`worktree_isolation` default).
Derive: `quality_level` from flags.

Worktree lifecycle (Phase 1.5/2.5/5 cleanup) orchestrated by `/proj:run`. Direct execute w/ worktree → caller manages lifecycle. Standalone → use `/proj:run`.

**Quality Level Param Mapping** (execute-specific):

| Parameter | --fast | --careful |
|-----------|--------|-----------|
| gate_override | auto-execute (tag-immune) | smart-gate + full-review |
| verification_mode | skip | enhanced |
| max_parallel | 20 | 10 |
| satisfaction | skip (auto-complete) | per-todo |
| worktree | from config | from config |
| overlap_action | auto-proceed | auto-serialize |

Empty → `mcp__proj__todo_list(status="in_progress")`; if none, `todo_list(status="ready")`. Show results, proceed w/ first (or ask if multiple).

> Pre-execute preflight: via `/proj:run` only (Phase C0.5/C0.5b). Direct `/proj:execute` skips preflight. See `plugins/proj/skills/run/SKILL.md` Phase C0.5.

## Single Todo

> Worktree-isolated parallel exec → use `/proj:run <range> --from execute`. Direct execute runs on main.

**1.** `mcp__proj__todo_check_executable(todo_id)` — starts w/ "⚠️" → display, **stop**.
**2.** `mcp__proj__proj_get_todo_context(todo_id, include_parent=true)` — returns todo, reqs, research, parent.
**3.** `mcp__proj__proj_search_knowledge(query=<todo title>, scope=all)`. Snippets → "### Related Context". None → skip.

**3a. Smart gate scoring** (skip if quality_level == fast w/ auto-execute):

 File-impact estimation (dims 1-2): spawn `subagent_type="file-discovery"` read-only Task agent w/ todo ctx, reqs, research. Agent estimates files modified/created, dirs involved. Wait. Use results for dims 1-2. Agent fails → score dims 1-2 as 0.

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

 Eval order: Tag overrides FIRST → complexity score → critical-path guard FINAL FLOOR.

 Tag overrides: `auto-execute` → force AUTO-EXECUTE. `security`/`breaking-change`/`migration`/`needs-review` → force FULL REVIEW (even --fast, tag-immune). Most restrictive wins.

 Critical-path guard (FINAL FLOOR): planned file matches `*.env*`, `*auth*`, `*secret*`, `*credential*`, `Dockerfile`, `.github/workflows/*`, `pyproject.toml`, `settings.json` → min LIGHT REVIEW even if score 0-3.

 Gate routing:
 - AUTO-EXECUTE (0-3): git tag `pre-auto-execute-{todo_id}`. Skip plan, exec w/ ctx.
 - LIGHT REVIEW (4-7): 1-line summary + `Proceed? [Y/n]` (default yes).
 - FULL REVIEW (8-14): Full `EnterPlanMode`/`ExitPlanMode`.

**3b. Plan creation** (respects trust, skipped if AUTO-EXECUTE):
(only if tasks_enabled) `TaskCreate(title="Phase C1: Plan — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C1", "kind": "phase_task"})` → store as `task_C1_id` → `TaskUpdate(status="in_progress")`
 - `mcp__proj__proj_decision_log(action="search", decision=<todo title>, project_name=<project>)`. Results → "### Prior Decisions" in plan ctx.
 - Trust 0-2: `EnterPlanMode`. Read ctx (reqs, research, notes, Related Context). Explore source. Plan: files to modify/create, key changes, impl order, testing.
 - Trust 0-1: `ExitPlanMode` for user review. Approve before proceeding.
 - Trust 2: Skip `ExitPlanMode`. Display: `Plan auto-approved (trust 2): <1-line summary>`.
 - After approval: `proj_decision_log(action="add", decision=<approach summary>, tags="plan", todo_id)`.
 - Trust 3: Skip 3b → step 4 w/ ctx only.

After plan: (only if tasks_enabled) `TaskUpdate(task_C1_id, status="completed")`.

(only if tasks_enabled) `TaskCreate(title="Phase C2: Execute — todo {id}", metadata={"proj_todo_id": "{id}", "phase": "C2", "kind": "phase_task"})` → `task_C2_id` → `TaskUpdate(status="in_progress")`

Per-todo task (only if tasks_enabled):
```
TaskCreate(
  title="Implement todo {id} — {title}",
  description="{notes[:300] if notes else ''}",
  activeForm="Implementing {title}",
  metadata={
    "proj_todo_id": "{id}", "phase": "C2", "kind": "todo_task",
    "parent_task_id": "<task_C2_id>",
    "proj": {"id": "{id}", "priority": "{priority}", "tags": [...], "parent_id": "{parent or null}"}
  }
) → todo_task_id → TaskUpdate(status="in_progress")
```
Pass `todo_task_id` to implementer agent: `task_id: {todo_task_id}  ← agent uses for TaskUpdate + subtask creation`

**4.** `mcp__proj__todo_update(status="in_progress")`. Review ctx, implement. Non-empty `notes` → additional impl ctx.

After impl: (only if tasks_enabled) `TaskUpdate(task_C2_id, status="completed")`. Failure → `TaskUpdate(task_C2_id, status="failed")`.

**4a. Verification** (skip if `--no-verify`):

(only if tasks_enabled) `TaskCreate(title="Phase C2a: Verification — todo {id}", ...)` → `task_C2a_id` → `TaskUpdate(status="in_progress")`

Mode: `skip` (--fast) → skip entirely. `enhanced` (--careful) → automated + spec + diff + manual test checklist.

 **A. Automated checks**: detect `pyproject.toml` w/ `[tool.pytest]` → `uv run pytest --tb=short -q`; `package.json` w/ `"test"` → `npm test`; `[tool.ruff]` → `uv run ruff check`; `.eslintrc*` → `npx eslint`. Missing prereqs → skip w/ note.

 **B. Spec validation**: `content_get_requirements` → extract `- [ ]`/`- [x]` criteria → `git diff HEAD~1` → each criterion: met/unmet/unverifiable.

 **C. Diff review**: extract planned files from 3b → `git diff --name-only HEAD~1` → compare planned vs touched.

 **Report:**
   ```
   ### Verification Report — Todo <id>

   **Automated checks**: PASS (14 tests passed) | FAIL (2 tests failed: test_x, test_y)
   **Spec validation**: 4/4 criteria met | 3/4 criteria met (1 unverifiable)
   **Diff review**: Plan matches | 1 planned file not touched, 1 unplanned file modified
   ```

 Persist to `todos/<id>/verification-report.md` (timestamped, overwrite prev).

 Prompt: `Fix these issues? (1) Fix (2) Proceed (3) Skip`
 - Fix: spawn `subagent_type="verification-fixer"` w/ report + ctx + reqs + research + plan. Re-verify (max 2 retries). Still failing → re-prompt.
 - Proceed/Skip: continue to satisfaction.

After verification: (only if tasks_enabled) `TaskUpdate(task_C2a_id, status="completed")`. Failure → `failed`.

(only if tasks_enabled) `TaskCreate(title="Phase SAT: Satisfaction — todo {id}", ...)` → `task_SAT_id` → `TaskUpdate(status="in_progress")`

**5. Satisfaction loop:**
 a. Ask: "Are you satisfied with outcome of todo <id>?"
 1. Satisfied → step 5d
 2. Not satisfied → describe fixes needed → fix in cur scope → `proj_decision_log(action="add", decision=<feedback>, tags="correction,quality", ...)` → re-ask
 3. Redefine → `Skill("proj:define")` → if decomposable → `Skill("proj:decompose")` → `Skill("proj:execute")`. Enforce `--careful`. Max recursion depth 2.
 d. `mcp__proj__todo_complete` → `mcp__proj__claudemd_write` if relevant → `mcp__proj__notes_append`

After satisfaction: (only if tasks_enabled) `TaskUpdate(task_SAT_id, status="completed")`.

## Range Execution

**Mode selection:** 3+ independent non-manual todos → **Pattern A** (parallel). Otherwise → **Pattern B** (sequential).

### Shared: Smart Gate Scoring (all patterns)

Same 7-dimension table + eval order + tag overrides + critical-path guard as single todo (§3a). In range context, file-impact estimation via file-discovery agent per todo or skip dims 1-2 if trust 3.

### Shared: Plan Phase (all patterns)

Init `approved_plans = {}`, `manual_skipped_ids = []`. Skip if trust 3 → execute w/ ctx only.

Each todo:
1. `todo_check_executable` — "⚠️" → add to `manual_skipped_ids`, skip.
2. `proj_get_todo_context(todo_id, include_parent=true)`.
3. `proj_search_knowledge(query=<title>, scope=all)` → "### Related Context".
4. Smart gate scoring (§3a). `proj_decision_log(action="search", ...)` → "### Prior Decisions".
5. `EnterPlanMode`. Plan w/ Related Context + Prior Decisions. (Skip if AUTO-EXECUTE.)
6. Approval: Trust 0 → approve before next. Trust 1 → approve, next. Trust 2 → auto-approve.
7. `proj_decision_log(action="add", ..., tags="plan", todo_id)`.
8. Store in `approved_plans[todo_id]`.

After all plans (trust 0-1): bulk approval summary w/ IDs + summaries.

**File-Overlap Detection** (before execute phase, skip if trust 3):
1. Extract "Files to modify/create" from each plan.
2. Build overlap matrix. Dep-mode: check within same batch only (cross-batch = sequential = OK).
3. Overlaps:

```
### File Overlap Warning

| File | Touched by | Batch |
|------|-----------|-------|
| models.py | todo 1, todo 3 | 1 |

Options:
1. **Serialize** — Move conflicting todos to sequential batch
2. **Proceed** — Execute in parallel anyway (risk of conflicts)
3. **Cancel** — Stop execution
```

Serialize → remove conflicting from parallel, add sequential batch at end. Cancel → "Execution cancelled. Plans are saved."

**Resume checkpoint** (`--resume`):
1. Find most recent `<tracking_dir>/<project>/.team-state/*/checkpoint.yaml`.
2. Fresh (< 24h) → `Resuming from batch {batch_index}/{total_batches} — {N} todos already completed`. Use stored `approved_plans`, skip to `batch_index`.
3. Stale (> 24h) or nonexistent refs → prompt: `(1) Restart (2) Use anyway`.
4. Not found → `No checkpoint found — starting fresh`.

### Shared: Execute Phase (all patterns)

Enforce `max_parallel` from quality_level.

**Task mapping** (one-way, only if tasks_enabled): `TaskCreate` per todo w/ `blocked_by` rels → `addBlockedBy`. Task completion ≠ proj todo completion (satisfaction loop handles that).

**NEVER implement code directly in main conversation — always spawn `Agent(subagent_type="implementer", run_in_background=true)` per todo.**
Spawn one `subagent_type="implementer"` Agent per todo w/ `run_in_background=true`. Each gets: plan (or ctx trust 3) + reqs + research + parent ctx.
`worktree_enabled` + `worktree_path` → exec in worktree, prefix commits `[todo-{id}]`.
Agents exec plan as-is. Do NOT `todo_complete`. Plan gap → return `{status: "escalation_needed", issue: "..."}`. See `_shared/errors.md`.
Wait per batch (auto-notified on completion). Report failures.

Write checkpoint:
```yaml
batch_index: <current batch number>
total_batches: <total>
completed_todos: [<completed todo IDs>]
approved_plans:
  <todo_id>: "<plan text>"
```
Failures → log to `tracking/{project}/.team-state/failed-agents.yaml`.

### Shared: Verification Phase (skip if `--no-verify`)

Verify each completed todo. Run checks from §4a. Combined report:

```
### Verification Summary — Batch

| Todo | Automated | Spec | Diff | Status |
|------|-----------|------|------|--------|
| 2.1  | PASS (14 tests) | 3/3 met | Plan matches | PASS |
| 2.2  | FAIL (2 failed) | 2/3 met | Plan matches | FAIL |
```

Persist each to `todos/<id>/verification-report.md`.

`> Fix failed todos? (1) Fix (2) Proceed (3) Skip`
- Fix: 2+ → one `subagent_type="verification-fixer"` per failed w/ `run_in_background=true`. 1 → single agent. Re-verify (max 2 retries).

### Shared: Satisfaction Phase

Each completed todo (excl manual-skipped + failed): satisfaction loop (§5a-5d) before `todo_complete`.
Batch: collect satisfied IDs → 2+ → `todo_batch_complete`. 1 → `todo_complete`.
Report summary incl skipped/failed.

## Pattern A — Parallel exec

**(only if tasks_enabled) TaskCreate labels:**
- Plan: `"Phase C1: Plan — batch"` (deps: `"Phase C1: Plan — deps batch"`)
- Execute: `"Phase C2: Execute — batch"` (deps: `"Phase C2: Execute — deps batch"`)
- Verify: `"Phase C2a: Verification — batch"` (deps: `"Phase C2a: Verification — deps batch"`)
- Satisfaction: `"Phase SAT: Satisfaction — batch"`

**Dep mode**: `mcp__proj__proj_identify_batches`. Group into topo-ordered batches. Within-batch parallel, batches sequential. Execute per batch in dep order. Cross-batch overlap OK (sequential).

## Pattern B — Sequential exec (fallback)

Same phases as Pattern A. Spawn agents sequentially (or small parallel groups ≤ max_parallel). Respect `blocked_by` order.

## Completion

**6.** Git tracking flush: `mcp__proj__tracking_git_flush(commit_message="Execute: {todo-id}")`.

Root todo exec does NOT auto-recurse into children. Specify child IDs explicitly.

## Error Handling

> See `plugins/proj/skills/_shared/errors.md` for escalation protocol, manual-tagged handling, worktree failure table, agent fallback, and common error conditions.

## Output

- Single todo: impl result, verification report (if enabled), satisfaction outcome, completion confirm.
- Range/batch: per-batch progress, combined verification table, satisfaction per completed todo, overall summary.

Suggested next: `1. /proj:save` -- save session, reconcile git | `2. /proj:status` -- updated overview
